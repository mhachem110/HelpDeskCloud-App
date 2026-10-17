using Microsoft.Extensions.Diagnostics.HealthChecks;
using Npgsql;

namespace HelpDeskCloud.Data;

public sealed class DatabaseHealthCheck(NpgsqlDataSource dataSource) : IHealthCheck
{
    public async Task<HealthCheckResult> CheckHealthAsync(HealthCheckContext context, CancellationToken cancellationToken = default)
    {
        try
        {
            await using var command = dataSource.CreateCommand("SELECT to_regclass('public.tickets') IS NOT NULL");
            command.CommandTimeout = 3;
            var exists = (bool)(await command.ExecuteScalarAsync(cancellationToken) ?? false);
            return exists ? HealthCheckResult.Healthy("Database and schema ready")
                : HealthCheckResult.Unhealthy("Database schema not initialized");
        }
        catch (Exception ex) when (ex is NpgsqlException or TimeoutException or InvalidOperationException)
        {
            return HealthCheckResult.Unhealthy("Database unavailable");
        }
    }
}
