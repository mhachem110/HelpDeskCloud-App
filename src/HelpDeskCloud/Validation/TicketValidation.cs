using HelpDeskCloud.Models;

namespace HelpDeskCloud.Validation;

public static class TicketValidation
{
    public static readonly string[] Priorities = ["Low", "Medium", "High", "Critical"];
    public static readonly string[] Statuses = ["Open", "In Progress", "Resolved"];
    public static readonly string[] Categories = ["Access", "Hardware", "Software", "Network", "Other"];

    public static Dictionary<string, string[]> Validate(CreateTicketRequest ticket) =>
        ValidateFields(ticket.Title, ticket.Description, ticket.Category, ticket.Priority);

    public static Dictionary<string, string[]> Validate(UpdateTicketRequest ticket)
    {
        var issues = ValidateFields(ticket.Title, ticket.Description, ticket.Category, ticket.Priority);
        if (!Statuses.Contains(ticket.Status, StringComparer.Ordinal))
        {
            issues["status"] = ["Choose a valid status."];
        }
        return issues;
    }

    private static Dictionary<string, string[]> ValidateFields(string? title, string? description, string? category, string? priority)
    {
        var issues = new Dictionary<string, string[]>(StringComparer.Ordinal);
        if (string.IsNullOrWhiteSpace(title) || title.Trim().Length is < 4 or > 120)
            issues["title"] = ["Title must contain between 4 and 120 characters."];
        if (description is { Length: > 2000 })
            issues["description"] = ["Description cannot exceed 2000 characters."];
        if (!Categories.Contains(category, StringComparer.Ordinal))
            issues["category"] = ["Choose a valid category."];
        if (!Priorities.Contains(priority, StringComparer.Ordinal))
            issues["priority"] = ["Choose a valid priority."];
        return issues;
    }
}
