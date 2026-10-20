using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using HelpDeskCloud.Security;

internal static class IapAssertionTests
{
    private const string Audience = "/projects/260283083469/global/backendServices/123456789";
    private const string AllowedEmail = "approved@example.com";
    private const string KeyId = "test-iap-key";

    public static IEnumerable<(string Name, Func<Task<bool>> Run)> Checks()
    {
        yield return ("Documented signed IAP claims are accepted", ValidAssertionIsAccepted);
        yield return ("Wrong IAP audience is rejected", () => AssertionIsRejected(audience: "wrong-audience"));
        yield return ("Unapproved IAP email is rejected", () => AssertionIsRejected(email: "other@example.com"));
        yield return ("Expired IAP assertion is rejected", () => AssertionIsRejected(expired: true));
        yield return ("IAP assertion without a subject is rejected", () => AssertionIsRejected(subject: null));
        yield return ("IAP assertion without an email is rejected", () => AssertionIsRejected(email: ""));
        yield return ("Wrong IAP issuer is rejected", () => AssertionIsRejected(issuer: "https://attacker.example"));
        yield return ("Future IAP assertion is rejected", () => AssertionIsRejected(futureIssuedAt: true));
        yield return ("Excessive IAP token lifetime is rejected", () => AssertionIsRejected(longLifetime: true));
        yield return ("Invalid IAP signature is rejected", InvalidSignatureIsRejected);
        yield return ("Missing IAP assertion is rejected", MissingAssertionIsRejected);
        yield return ("Unknown key refresh is throttled", UnknownKeyRefreshIsThrottled);
        yield return ("Only the two health endpoints bypass assertion checks", HealthPathPolicyIsExact);
    }

    private static async Task<bool> ValidAssertionIsAccepted()
    {
        using var signer = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var token = CreateToken(signer, Audience, AllowedEmail);
        var validator = CreateValidator(signer);
        return await validator.ValidateAsync(token, Audience, AllowedEmail);
    }

    private static async Task<bool> AssertionIsRejected(
        string? audience = null,
        string? email = null,
        bool expired = false,
        string? subject = "google-user-id",
        string? issuer = null,
        bool futureIssuedAt = false,
        bool longLifetime = false)
    {
        using var signer = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var token = CreateToken(signer, audience ?? Audience, email ?? AllowedEmail, expired,
            subject, issuer, futureIssuedAt, longLifetime);
        var validator = CreateValidator(signer);
        return !await validator.ValidateAsync(token, Audience, AllowedEmail);
    }

    private static async Task<bool> InvalidSignatureIsRejected()
    {
        using var publishedKey = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        using var attackerKey = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var token = CreateToken(attackerKey, Audience, AllowedEmail);
        var validator = CreateValidator(publishedKey);
        return !await validator.ValidateAsync(token, Audience, AllowedEmail);
    }

    private static async Task<bool> MissingAssertionIsRejected()
    {
        using var signer = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var validator = CreateValidator(signer);
        return !await validator.ValidateAsync(null, Audience, AllowedEmail);
    }

    private static async Task<bool> UnknownKeyRefreshIsThrottled()
    {
        using var signer = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var (validator, handler) = CreateValidatorWithHandler(signer);
        var token = CreateToken(signer, Audience, AllowedEmail, keyId: "unknown-key");
        var first = await validator.ValidateAsync(token, Audience, AllowedEmail);
        var second = await validator.ValidateAsync(token, Audience, AllowedEmail);
        return !first && !second && handler.RequestCount == 2; // initial key fetch plus one unknown-kid refresh
    }

    private static Task<bool> HealthPathPolicyIsExact()
    {
        var passed = !IapAssertionMiddleware.RequiresIapAssertion("/health/live") &&
                     !IapAssertionMiddleware.RequiresIapAssertion("/health/ready") &&
                     IapAssertionMiddleware.RequiresIapAssertion("/api/tickets") &&
                     IapAssertionMiddleware.RequiresIapAssertion("/health/live/tickets") &&
                     IapAssertionMiddleware.RequiresIapAssertion("/");
        return Task.FromResult(passed);
    }

    private static IapAssertionValidator CreateValidator(ECDsa key)
        => CreateValidatorWithHandler(key).Validator;

    private static (IapAssertionValidator Validator, StaticResponseHandler Handler) CreateValidatorWithHandler(ECDsa key)
    {
        var publicParameters = key.ExportParameters(includePrivateParameters: false);
        var jwks = JsonSerializer.Serialize(new
        {
            keys = new[]
            {
                new
                {
                    kty = "EC",
                    crv = "P-256",
                    alg = "ES256",
                    use = "sig",
                    kid = KeyId,
                    x = Encode(publicParameters.Q.X!),
                    y = Encode(publicParameters.Q.Y!)
                }
            }
        });
        var handler = new StaticResponseHandler(jwks);
        return (new IapAssertionValidator(new HttpClient(handler)), handler);
    }

    private static string CreateToken(
        ECDsa signer,
        string audience,
        string email,
        bool expired = false,
        string? subject = "google-user-id",
        string? issuer = null,
        bool futureIssuedAt = false,
        bool longLifetime = false,
        string keyId = KeyId)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var issuedAt = expired ? now - 900 : futureIssuedAt ? now + 120 : now - 5;
        var expiresAt = expired ? now - 600 : longLifetime ? issuedAt + 900 : now + 300;
        var header = Encode(JsonSerializer.SerializeToUtf8Bytes(new { alg = "ES256", kid = keyId }));
        var claims = new Dictionary<string, object>
        {
            ["iss"] = issuer ?? "https://cloud.google.com/iap",
            ["aud"] = audience,
            ["email"] = email,
            ["iat"] = issuedAt,
            ["exp"] = expiresAt
        };
        if (subject is not null) claims["sub"] = subject;
        var payload = Encode(JsonSerializer.SerializeToUtf8Bytes(claims));
        var content = Encoding.ASCII.GetBytes($"{header}.{payload}");
        var signature = signer.SignData(content, HashAlgorithmName.SHA256,
            DSASignatureFormat.IeeeP1363FixedFieldConcatenation);
        return $"{header}.{payload}.{Encode(signature)}";
    }

    private static string Encode(byte[] bytes) =>
        Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    private sealed class StaticResponseHandler(string body) : HttpMessageHandler
    {
        public int RequestCount { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            RequestCount++;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(body, Encoding.UTF8, "application/json")
            });
        }
    }
}
