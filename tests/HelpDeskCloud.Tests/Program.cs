using HelpDeskCloud.Models;
using HelpDeskCloud.Validation;

var checks = new List<(string Name, Func<Task<bool>> Run)>
{
    ("Valid request", () => Task.FromResult(TicketValidation.Validate(new CreateTicketRequest("VPN disconnected", "Can't connect", "Network", "High")).Count == 0)),
    ("Missing title", () => Task.FromResult(TicketValidation.Validate(new CreateTicketRequest(" ", "", "Network", "High")).ContainsKey("title"))),
    ("Short title", () => Task.FromResult(TicketValidation.Validate(new CreateTicketRequest("abc", "", "Network", "High")).ContainsKey("title"))),
    ("Long title", () => Task.FromResult(TicketValidation.Validate(new CreateTicketRequest(new string('x', 121), "", "Network", "High")).ContainsKey("title"))),
    ("Long description", () => Task.FromResult(TicketValidation.Validate(new CreateTicketRequest("Valid title", new string('x', 2001), "Network", "High")).ContainsKey("description"))),
    ("Unknown category", () => Task.FromResult(TicketValidation.Validate(new CreateTicketRequest("Valid title", "", "OtherCategory", "High")).ContainsKey("category"))),
    ("Unknown priority", () => Task.FromResult(TicketValidation.Validate(new CreateTicketRequest("Valid title", "", "Network", "Extreme")).ContainsKey("priority"))),
    ("Valid update", () => Task.FromResult(TicketValidation.Validate(new UpdateTicketRequest("VPN disconnected", "Reproduced", "Network", "High", "Resolved")).Count == 0)),
    ("Invalid status", () => Task.FromResult(TicketValidation.Validate(new UpdateTicketRequest("VPN disconnected", "", "Network", "High", "Deleted")).ContainsKey("status"))),
    ("All three statuses", () => Task.FromResult(TicketValidation.Statuses.Length == 3)),
    ("All four priorities", () => Task.FromResult(TicketValidation.Priorities.Length == 4)),
};
checks.AddRange(IapAssertionTests.Checks());

int failures = 0;
foreach (var (name, run) in checks)
{
    bool passed = await run();
    Console.WriteLine($"{(passed ? "PASS" : "FAIL")}  {name}");
    if (!passed) failures++;
}
Console.WriteLine($"{checks.Count - failures}/{checks.Count} validation checks passed.");
return failures == 0 ? 0 : 1;
