using System.Globalization;
using System.Net;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.IdentityModel.JsonWebTokens;
using Microsoft.IdentityModel.Tokens;

namespace HelpDeskCloud.Security;

/// <summary>Validates Google's signed IAP assertion, including the exact backend audience.</summary>
public sealed class IapAssertionValidator(HttpClient httpClient)
{
    private const string PublicKeysUrl = "https://www.gstatic.com/iap/verify/public_key-jwk";
    private const string Issuer = "https://cloud.google.com/iap";
    private static readonly TimeSpan KeyCacheLifetime = TimeSpan.FromHours(1);
    private static readonly TimeSpan UnknownKeyRefreshCooldown = TimeSpan.FromMinutes(1);
    private static readonly TimeSpan ClockSkew = TimeSpan.FromSeconds(30);
    private static readonly TimeSpan MaximumTokenLifetime = TimeSpan.FromMinutes(11);
    private static readonly TimeProvider Clock = TimeProvider.System;

    private readonly JsonWebTokenHandler _tokenHandler = new() { MapInboundClaims = false };
    private readonly SemaphoreSlim _refreshLock = new(1, 1);
    private IReadOnlyDictionary<string, SecurityKey> _publicKeys =
        new Dictionary<string, SecurityKey>(StringComparer.Ordinal);
    private DateTimeOffset _keysExpireAt = DateTimeOffset.MinValue;
    private DateTimeOffset _unknownKeyRefreshAllowedAt = DateTimeOffset.MinValue;

    public async Task<bool> ValidateAsync(
        string? assertion,
        string expectedAudience,
        string allowedEmail,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(assertion) || assertion.Length > 16_384 ||
            string.IsNullOrWhiteSpace(expectedAudience) || string.IsNullOrWhiteSpace(allowedEmail))
            return false;

        try
        {
            var unvalidatedToken = _tokenHandler.ReadJsonWebToken(assertion);
            if (unvalidatedToken.Alg != SecurityAlgorithms.EcdsaSha256 ||
                string.IsNullOrWhiteSpace(unvalidatedToken.Kid))
                return false;

            var keys = await GetPublicKeysAsync(cancellationToken);
            if (!keys.TryGetValue(unvalidatedToken.Kid, out var signingKey))
            {
                keys = await RefreshPublicKeysAsync(cancellationToken, forceRefresh: true);
                if (!keys.TryGetValue(unvalidatedToken.Kid, out signingKey)) return false;
            }

            var validation = await _tokenHandler.ValidateTokenAsync(assertion, new TokenValidationParameters
            {
                ValidateIssuer = true,
                ValidIssuer = Issuer,
                ValidateAudience = true,
                ValidAudience = expectedAudience,
                ValidateIssuerSigningKey = true,
                IssuerSigningKey = signingKey,
                RequireSignedTokens = true,
                ValidAlgorithms = [SecurityAlgorithms.EcdsaSha256],
                ValidateLifetime = true,
                RequireExpirationTime = true,
                ClockSkew = ClockSkew
            });

            if (!validation.IsValid || validation.ClaimsIdentity is not { } identity) return false;
            if (!HasClaim(identity, "sub") || !TryGetClaim(identity, "email", out var email) ||
                !string.Equals(email, allowedEmail, StringComparison.OrdinalIgnoreCase)) return false;
            if (!TryGetUnixSeconds(identity, "iat", out var issuedAt) ||
                !TryGetUnixSeconds(identity, "exp", out var expiresAt)) return false;

            var now = Clock.GetUtcNow().ToUnixTimeSeconds();
            var skew = (long)ClockSkew.TotalSeconds;
            return expiresAt > issuedAt && expiresAt - issuedAt <= (long)MaximumTokenLifetime.TotalSeconds &&
                   issuedAt <= now + skew && expiresAt > now - skew;
        }
        catch (Exception exception) when (exception is HttpRequestException or TaskCanceledException or
                                           JsonException or FormatException or CryptographicException or
                                           SecurityTokenException or InvalidOperationException or ArgumentException)
        {
            // Network, malformed-token, and cryptographic failures all deny access.
            return false;
        }
    }

    private async Task<IReadOnlyDictionary<string, SecurityKey>> GetPublicKeysAsync(
        CancellationToken cancellationToken)
    {
        if (Clock.GetUtcNow() < _keysExpireAt && _publicKeys.Count > 0) return _publicKeys;
        return await RefreshPublicKeysAsync(cancellationToken, forceRefresh: false);
    }

    private async Task<IReadOnlyDictionary<string, SecurityKey>> RefreshPublicKeysAsync(
        CancellationToken cancellationToken,
        bool forceRefresh)
    {
        await _refreshLock.WaitAsync(cancellationToken);
        try
        {
            var now = Clock.GetUtcNow();
            if (!forceRefresh && now < _keysExpireAt && _publicKeys.Count > 0)
                return _publicKeys;
            if (forceRefresh && now < _unknownKeyRefreshAllowedAt)
                return _publicKeys;
            if (forceRefresh)
                _unknownKeyRefreshAllowedAt = now.Add(UnknownKeyRefreshCooldown);

            using var response = await httpClient.GetAsync(PublicKeysUrl, cancellationToken);
            response.EnsureSuccessStatusCode();
            var body = await response.Content.ReadAsStringAsync(cancellationToken);
            if (body.Length > 65_536) throw new JsonException("IAP public key response is too large.");

            var keySet = new JsonWebKeySet(body);
            var keys = new Dictionary<string, SecurityKey>(StringComparer.Ordinal);
            foreach (var key in keySet.Keys)
            {
                if (key.Kty != "EC" || key.Crv != "P-256" ||
                    (key.Alg is not null && key.Alg != SecurityAlgorithms.EcdsaSha256) ||
                    (key.Use is not null && key.Use != "sig"))
                    continue;

                if (string.IsNullOrWhiteSpace(key.Kid) || string.IsNullOrWhiteSpace(key.X) ||
                    string.IsNullOrWhiteSpace(key.Y) || Base64UrlEncoder.DecodeBytes(key.X).Length != 32 ||
                    Base64UrlEncoder.DecodeBytes(key.Y).Length != 32 || !keys.TryAdd(key.Kid, key))
                    throw new JsonException("IAP public key set contains an invalid or duplicate key.");
            }

            if (keys.Count == 0) throw new JsonException("IAP public key set contains no supported keys.");
            _publicKeys = keys;
            _keysExpireAt = Clock.GetUtcNow().Add(KeyCacheLifetime);
            return _publicKeys;
        }
        finally
        {
            _refreshLock.Release();
        }
    }

    private static bool HasClaim(ClaimsIdentity identity, string name) =>
        identity.FindFirst(name) is { Value.Length: > 0 };

    private static bool TryGetClaim(ClaimsIdentity identity, string name, out string value)
    {
        value = identity.FindFirst(name)?.Value ?? string.Empty;
        return value.Length > 0;
    }

    private static bool TryGetUnixSeconds(ClaimsIdentity identity, string name, out long seconds)
    {
        var claim = identity.FindFirst(name)?.Value;
        return long.TryParse(claim, NumberStyles.None, CultureInfo.InvariantCulture, out seconds);
    }
}
