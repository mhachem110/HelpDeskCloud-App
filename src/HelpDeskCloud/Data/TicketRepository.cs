using HelpDeskCloud.Models;
using Npgsql;
using NpgsqlTypes;
using System.Text;

namespace HelpDeskCloud.Data;

public sealed class TicketRepository(NpgsqlDataSource dataSource)
{
    private const string Columns = "id, title, description, category, priority, status, created_at, updated_at";

    public async Task<IReadOnlyList<Ticket>> ListAsync(string? status, string? priority, string? search, CancellationToken ct)
    {
        var query = new StringBuilder($"SELECT {Columns} FROM tickets WHERE TRUE");
        await using var command = dataSource.CreateCommand();
        if (!string.IsNullOrWhiteSpace(status))
        {
            query.Append(" AND status = @status");
            command.Parameters.AddWithValue("status", status);
        }
        if (!string.IsNullOrWhiteSpace(priority))
        {
            query.Append(" AND priority = @priority");
            command.Parameters.AddWithValue("priority", priority);
        }
        if (!string.IsNullOrWhiteSpace(search))
        {
            query.Append(" AND (strpos(lower(title), lower(@search)) > 0 OR strpos(lower(description), lower(@search)) > 0)");
            command.Parameters.AddWithValue("search", search);
        }
        query.Append(" ORDER BY created_at DESC LIMIT 200");
        command.CommandText = query.ToString();
        await using var reader = await command.ExecuteReaderAsync(ct);
        var tickets = new List<Ticket>();
        while (await reader.ReadAsync(ct)) tickets.Add(ReadTicket(reader));
        return tickets;
    }

    public async Task<Ticket?> FindAsync(Guid id, CancellationToken ct)
    {
        await using var command = dataSource.CreateCommand($"SELECT {Columns} FROM tickets WHERE id = @id");
        command.Parameters.AddWithValue("id", id);
        await using var reader = await command.ExecuteReaderAsync(ct);
        return await reader.ReadAsync(ct) ? ReadTicket(reader) : null;
    }

    public async Task<Ticket> CreateAsync(CreateTicketRequest input, CancellationToken ct)
    {
        await using var command = dataSource.CreateCommand($"""
            INSERT INTO tickets (id, title, description, category, priority, status)
            VALUES (@id, @title, @description, @category, @priority, 'Open')
            RETURNING {Columns}
            """);
        command.Parameters.AddWithValue("id", Guid.NewGuid());
        command.Parameters.AddWithValue("title", input.Title!.Trim());
        command.Parameters.AddWithValue("description", input.Description?.Trim() ?? "");
        command.Parameters.AddWithValue("category", input.Category!);
        command.Parameters.AddWithValue("priority", input.Priority!);
        await using var reader = await command.ExecuteReaderAsync(ct);
        await reader.ReadAsync(ct);
        return ReadTicket(reader);
    }

    public async Task<Ticket?> UpdateAsync(Guid id, UpdateTicketRequest input, CancellationToken ct)
    {
        await using var command = dataSource.CreateCommand($"""
            UPDATE tickets SET title = @title, description = @description,
                category = @category, priority = @priority, status = @status,
                updated_at = NOW()
            WHERE id = @id RETURNING {Columns}
            """);
        command.Parameters.AddWithValue("id", id);
        command.Parameters.AddWithValue("title", input.Title!.Trim());
        command.Parameters.AddWithValue("description", input.Description?.Trim() ?? "");
        command.Parameters.AddWithValue("category", input.Category!);
        command.Parameters.AddWithValue("priority", input.Priority!);
        command.Parameters.AddWithValue("status", input.Status!);
        await using var reader = await command.ExecuteReaderAsync(ct);
        return await reader.ReadAsync(ct) ? ReadTicket(reader) : null;
    }

    public async Task<bool> DeleteAsync(Guid id, CancellationToken ct)
    {
        await using var command = dataSource.CreateCommand("DELETE FROM tickets WHERE id = @id");
        command.Parameters.AddWithValue("id", id);
        return await command.ExecuteNonQueryAsync(ct) > 0;
    }

    public async Task<TicketStats> StatsAsync(CancellationToken ct)
    {
        await using var command = dataSource.CreateCommand("""
            SELECT COUNT(*),
                COUNT(*) FILTER (WHERE status = 'Open'),
                COUNT(*) FILTER (WHERE status = 'In Progress'),
                COUNT(*) FILTER (WHERE status = 'Resolved'),
                COUNT(*) FILTER (WHERE priority = 'Critical' AND status != 'Resolved')
            FROM tickets
            """);
        await using var reader = await command.ExecuteReaderAsync(ct);
        await reader.ReadAsync(ct);
        return new TicketStats(reader.GetInt64(0), reader.GetInt64(1), reader.GetInt64(2), reader.GetInt64(3), reader.GetInt64(4));
    }

    private static Ticket ReadTicket(NpgsqlDataReader reader) => new(
        reader.GetGuid(0), reader.GetString(1), reader.GetString(2),
        reader.GetString(3), reader.GetString(4), reader.GetString(5),
        reader.GetDateTime(6), reader.GetDateTime(7));
}
