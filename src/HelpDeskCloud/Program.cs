using System.Threading.RateLimiting;
using HelpDeskCloud.Data;
using HelpDeskCloud.Models;
using HelpDeskCloud.Security;
using HelpDeskCloud.Validation;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Npgsql;

var builder = WebApplication.CreateBuilder(args);

builder.Logging.AddJsonConsole();
builder.Services.AddProblemDetails();
var iapOptions = builder.Configuration.GetSection("Iap").Get<IapOptions>() ?? new IapOptions();
// A protected Dev release must fail at startup if its second IAP validation layer is misconfigured.
if (iapOptions.Enabled &&
    (string.IsNullOrWhiteSpace(iapOptions.ExpectedAudience) ||
     string.IsNullOrWhiteSpace(iapOptions.AllowedEmail)))
    throw new InvalidOperationException("IAP enforcement requires an expected audience and an approved email.");
builder.Services.Configure<IapOptions>(builder.Configuration.GetSection("Iap"));
builder.Services.AddHttpClient<IapAssertionValidator>(client => client.Timeout = TimeSpan.FromSeconds(5));
builder.Services.AddHealthChecks().AddCheck<DatabaseHealthCheck>("postgresql", tags: ["ready"]);
builder.Services.AddRateLimiter(options =>
{
    options.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
    options.GlobalLimiter = PartitionedRateLimiter.Create<HttpContext, string>(context =>
        RateLimitPartition.GetFixedWindowLimiter(
            context.Connection.RemoteIpAddress?.ToString() ?? "unknown",
            _ => new FixedWindowRateLimiterOptions { PermitLimit = 120, Window = TimeSpan.FromMinutes(1), QueueLimit = 0 }));
});

// GKE mounts the connection string as a file; Compose keeps its environment setting.
var connectionFile = builder.Configuration["DATABASE_CONNECTION_STRING_FILE"];
string? connectionString;
if (!string.IsNullOrWhiteSpace(connectionFile))
{
    if (!File.Exists(connectionFile))
        throw new InvalidOperationException("The mounted database connection file is missing.");
    connectionString = File.ReadAllText(connectionFile).Trim();
}
else
{
    connectionString = builder.Configuration.GetConnectionString("Default") ?? builder.Configuration["DATABASE_URL"];
}
if (string.IsNullOrWhiteSpace(connectionString))
    throw new InvalidOperationException("Database connection configuration is missing. Set the configured environment value or mount the secret file.");

builder.Services.AddSingleton(_ => new NpgsqlDataSourceBuilder(connectionString).Build());
builder.Services.AddScoped<TicketRepository>();

var app = builder.Build();
app.UseExceptionHandler();
app.Use(async (context, next) =>
{
    context.Response.Headers["X-Content-Type-Options"] = "nosniff";
    context.Response.Headers["X-Frame-Options"] = "DENY";
    context.Response.Headers["Referrer-Policy"] = "strict-origin-when-cross-origin";
    context.Response.Headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'";
    await next(context);
});
// IAP authenticates at the Gateway; the app verifies Google's signed assertion again before routes.
app.UseMiddleware<IapAssertionMiddleware>();
app.UseRateLimiter();
app.UseDefaultFiles();
app.UseStaticFiles();

// A liveness check does not depend on the DB: losing the DB must not trigger an endless pod restart loop.
app.MapGet("/health/live", () => Results.Ok(new { status = "alive" }));
app.MapHealthChecks("/health/ready", new HealthCheckOptions
{
    Predicate = registration => registration.Tags.Contains("ready")
});

var api = app.MapGroup("/api");
api.MapGet("/info", () => Results.Ok(new { name = "HelpDesk Cloud", version = "1.0.0", api = "v1" }));

api.MapGet("/tickets", async (TicketRepository repository, string? status, string? priority, string? search, CancellationToken ct) =>
{
    if (status is not null && !TicketValidation.Statuses.Contains(status, StringComparer.Ordinal))
        return Results.BadRequest(new ErrorResponse("Invalid status filter."));
    if (priority is not null && !TicketValidation.Priorities.Contains(priority, StringComparer.Ordinal))
        return Results.BadRequest(new ErrorResponse("Invalid priority filter."));
    if (search is { Length: > 100 })
        return Results.BadRequest(new ErrorResponse("Search must be 100 characters or fewer."));
    return Results.Ok(await repository.ListAsync(status, priority, search, ct));
});
api.MapGet("/tickets/stats", async (TicketRepository repository, CancellationToken ct) =>
    Results.Ok(await repository.StatsAsync(ct)));
api.MapGet("/tickets/{id:guid}", async (Guid id, TicketRepository repository, CancellationToken ct) =>
    await repository.FindAsync(id, ct) is { } ticket ? Results.Ok(ticket) : Results.NotFound());
api.MapPost("/tickets", async (CreateTicketRequest input, TicketRepository repository, CancellationToken ct) =>
{
    var errors = TicketValidation.Validate(input);
    if (errors.Count > 0) return Results.ValidationProblem(errors);
    var ticket = await repository.CreateAsync(input, ct);
    return Results.Created($"/api/tickets/{ticket.Id}", ticket);
});
api.MapPut("/tickets/{id:guid}", async (Guid id, UpdateTicketRequest input, TicketRepository repository, CancellationToken ct) =>
{
    var errors = TicketValidation.Validate(input);
    if (errors.Count > 0) return Results.ValidationProblem(errors);
    return await repository.UpdateAsync(id, input, ct) is { } ticket ? Results.Ok(ticket) : Results.NotFound();
});
api.MapDelete("/tickets/{id:guid}", async (Guid id, TicketRepository repository, CancellationToken ct) =>
    await repository.DeleteAsync(id, ct) ? Results.NoContent() : Results.NotFound());

app.MapFallbackToFile("index.html");
app.Run();

// Enables future WebApplicationFactory integration tests without affecting production behavior.
public partial class Program { }
