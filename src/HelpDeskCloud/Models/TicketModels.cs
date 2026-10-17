namespace HelpDeskCloud.Models;

public sealed record Ticket(
    Guid Id,
    string Title,
    string Description,
    string Category,
    string Priority,
    string Status,
    DateTime CreatedAt,
    DateTime UpdatedAt);

public sealed record CreateTicketRequest(
    string? Title,
    string? Description,
    string? Category,
    string? Priority);

public sealed record UpdateTicketRequest(
    string? Title,
    string? Description,
    string? Category,
    string? Priority,
    string? Status);

public sealed record TicketStats(
    long Total,
    long Open,
    long InProgress,
    long Resolved,
    long Critical);

public sealed record ErrorResponse(string Error, IDictionary<string, string[]>? Details = null);
