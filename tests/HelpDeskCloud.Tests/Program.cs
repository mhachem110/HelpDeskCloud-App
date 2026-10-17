using HelpDeskCloud.Models;
using HelpDeskCloud.Validation;

var checks = new (string Name, Func<bool> Run)[]
{
    ("Valid request", () => TicketValidation.Validate(new CreateTicketRequest("VPN disconnected", "Can't connect", "Network", "High")).Count == 0),
    ("Missing title", () => TicketValidation.Validate(new CreateTicketRequest(" ", "", "Network", "High")).ContainsKey("title")),
    ("Short title", () => TicketValidation.Validate(new CreateTicketRequest("abc", "", "Network", "High")).ContainsKey("title")),
    ("Long title", () => TicketValidation.Validate(new CreateTicketRequest(new string('x', 121), "", "Network", "High")).ContainsKey("title")),
    ("Long description", () => TicketValidation.Validate(new CreateTicketRequest("Valid title", new string('x', 2001), "Network", "High")).ContainsKey("description")),
    ("Unknown category", () => TicketValidation.Validate(new CreateTicketRequest("Valid title", "", "OtherCategory", "High")).ContainsKey("category")),
    ("Unknown priority", () => TicketValidation.Validate(new CreateTicketRequest("Valid title", "", "Network", "Extreme")).ContainsKey("priority")),
    ("Valid update", () => TicketValidation.Validate(new UpdateTicketRequest("VPN disconnected", "Reproduced", "Network", "High", "Resolved")).Count == 0),
    ("Invalid status", () => TicketValidation.Validate(new UpdateTicketRequest("VPN disconnected", "", "Network", "High", "Deleted")).ContainsKey("status")),
    ("All three statuses", () => TicketValidation.Statuses.Length == 3),
    ("All four priorities", () => TicketValidation.Priorities.Length == 4),
};

int failures = 0;
foreach (var (name, run) in checks)
{
    bool passed = run();
    Console.WriteLine($"{(passed ? "PASS" : "FAIL")}  {name}");
    if (!passed) failures++;
}
Console.WriteLine($"{checks.Length - failures}/{checks.Length} validation checks passed.");
return failures == 0 ? 0 : 1;
