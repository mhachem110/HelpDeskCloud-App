using Microsoft.Extensions.Options;

namespace HelpDeskCloud.Security;

public sealed class IapAssertionMiddleware(RequestDelegate next, IOptions<IapOptions> options)
{
    public async Task InvokeAsync(HttpContext context, IapAssertionValidator validator)
    {
        var settings = options.Value;
        if (!settings.Enabled || !RequiresIapAssertion(context.Request.Path))
        {
            await next(context);
            return;
        }

        var assertions = context.Request.Headers["X-Goog-IAP-JWT-Assertion"];
        if (assertions.Count != 1 ||
            !await validator.ValidateAsync(assertions[0], settings.ExpectedAudience,
                settings.AllowedEmail, context.RequestAborted))
        {
            context.Response.StatusCode = StatusCodes.Status401Unauthorized;
            await context.Response.WriteAsJsonAsync(
                new { error = "A valid IAP identity assertion is required." }, context.RequestAborted);
            return;
        }

        await next(context);
    }

    // Google load-balancer and Kubernetes probes need these health signals; the public Gateway
    // still enforces IAP before external requests can reach either endpoint.
    public static bool RequiresIapAssertion(PathString path) =>
        !path.Equals("/health/live", StringComparison.OrdinalIgnoreCase) &&
        !path.Equals("/health/ready", StringComparison.OrdinalIgnoreCase);
}
