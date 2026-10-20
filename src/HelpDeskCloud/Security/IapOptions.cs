namespace HelpDeskCloud.Security;

public sealed class IapOptions
{
    public bool Enabled { get; set; }
    public string ExpectedAudience { get; set; } = "";
    public string AllowedEmail { get; set; } = "";
}
