# Permanent HTTPS access: application handoff

Status: implementation prepared for review, **not deployed**. The current Dev
release remains a private ClusterIP service. The owner has not selected a domain
or supplied a Google account address, so no HTTPS route, DNS record, OAuth
client, certificate, load balancer or app IAP enforcement is active. See the
[Infra architecture and live inventory](https://github.com/mhachem110/HelpDeskCloud-Infra/blob/codex/https-access-design/docs/HTTPS-ACCESS-DESIGN.md)
and the coordinated [App pull request](https://github.com/mhachem110/HelpDeskCloud-App/pull/16).

## Verified current boundary

The successful [App deployment 39466841649](https://github.com/mhachem110/HelpDeskCloud-App/actions/runs/39466841649)
published an immutable image, rolled out two replicas and passed health checks.
Read-only GKE inspection on 2026-10-20 found two ready
`helpdesk-helpdesk` replicas and a `ClusterIP` Service on port 80. No Gateway,
HTTPRoute or Ingress is currently installed. The website therefore still uses
port-forwarding.

The app has no end-user roles or ticket ownership checks. IAP will restrict
website access to the one configured Google account, but it will not add
per-ticket authorization: that account can operate on every ticket. Use demo
data until authorization is separately designed.

## Implemented in this PR

The app now has opt-in Google IAP signed-assertion validation using Microsoft's
maintained `Microsoft.IdentityModel.JsonWebTokens` library. It checks the ES256
signature against Google's rotating public keys, issuer, exact backend
audience, expiry/issued-at, nonempty subject and the exact configured email.
IAP's documented signed payload provides `sub` and `email`; the validator does
not require an undocumented `email_verified` claim. Missing or invalid
assertions fail closed. Only the exact `/health/live` and
`/health/ready` paths bypass the middleware. Unknown signing-key refreshes are
throttled. Enforcement stays disabled unless the owner enables it with the
numeric backend ID and one email; enabling it without both values fails startup.

The existing `helm/helpdesk` release still owns only the app Deployment and
internal Service. Its Dev delivery overlay explicitly keeps IAP enforcement
off. A separate `helm/https-edge-access` chart owns only the Gateway,
HTTPRoute, SSL policy attachment, IAP backend policy and health-check policy.
Its default is disabled. It uses an exact `/health/live` route in `health-only`
stage and expands to `/` only in the explicitly selected `application` stage.
The offline manifest guard rejects extra resources, HTTP listeners, other
hosts/backends, disabled IAP or expanded paths in the health-only stage.

The `app-dev-delivery.yml` workflow retains its existing protected publisher
and deployer Environments, WIF providers, immutable image flow and DNS-based
GKE endpoint. Ordinary app delivery defaults to the private mode. A separate
manual edge stage is disabled unless `DEV_HTTPS_EDGE_ENABLED=true`; application
routes additionally require `DEV_HTTPS_ACTIVE=true`, an explicit confirmation,
and a running app Deployment already configured with the exact audience and
account. It checks the Gateway/Route/policy conditions, verifies the Gateway
IP is the retained address, and confirms unauthenticated HTTPS requests are
rejected. It never writes DNS.

The namespace Role grants the deployer access only to the named Gateway API
resource kinds in `helpdesk-dev`; it adds no cluster-scoped permission, CRD,
GatewayClass or Service mutation. The OAuth client secret is delivered from a
protected Environment secret into a namespace Secret outside Helm values and
logs. The app deployer remains trusted with namespace Secret access, including
the existing Helm release storage.

## Owner inputs required before any deployment

Do not configure these values until the related Infra plan is reviewed and the
owner approves a public load balancer and certificate cost:

- App repository variables: `DEV_HTTPS_EDGE_ENABLED`, `DEV_HTTPS_HOSTNAME`,
  `DEV_HTTPS_CERTIFICATE_MAP`, `DEV_HTTPS_STATIC_IP_NAME`,
  `DEV_HTTPS_STATIC_IP`, `DEV_HTTPS_SSL_POLICY`, and
  `DEV_IAP_OAUTH_CLIENT_ID`.
- After the Gateway backend is discovered and the separate IAP access grant is
  verified: `DEV_IAP_BACKEND_SERVICE_ID` and `DEV_IAP_ALLOWED_EMAIL`.
- Protected Environment secret in `dev-app-deploy`:
  `DEV_IAP_OAUTH_CLIENT_SECRET`.
- Before app enforcement: set `DEV_HTTPS_ACTIVE=true`, then use the normal
  protected App delivery workflow to publish and deploy the signed-assertion
  version. Do not set it before the Gateway IAP backend is ready.
- Before ticket paths are reachable: manually dispatch the HTTPS `application`
  stage with `confirm_application_route=true`, after verifying the exact
  backend grant and the approved-account flow.

The custom OAuth client must be configured for an external/personal account
through the supported Google Auth Platform workflow; Google-managed OAuth is
not available to this project without an organization. Keep the client ID
visible only as a repository variable and store the secret only in the protected
Environment. The owner's one-email IAP binding is managed by the separate Infra
access root. No email is defaulted or hardcoded.

## Ordered rollout

1. Review and merge the App and Infra PRs only after all required checks and
   independent approvals. This implementation request does not merge either.
2. Choose a controlled hostname, create the external OAuth client, and review
   consent/test-user settings and projected load-balancer costs.
3. Run **Terraform Dev Plan** for `https-foundation`; inspect the exact plan,
   then use the existing protected **Terraform Dev Apply** component only after
   the `dev-network-apply` reviewer approves. Publish the emitted DNS
   authorization CNAME through the chosen DNS provider manually; wait for
   Certificate Manager to report `ACTIVE`. The IaC never creates DNS records.
4. Configure the App inputs above. Manually dispatch `health-only` through the
   protected `dev-app-deploy` Environment. Confirm the Gateway, exact-host
   route, health policy and IAP policy are accepted/programmed and that
   anonymous HTTPS is rejected. This stage creates a public load balancer and
   therefore requires separate owner approval.
5. Copy the one backend service name from the Gateway's
   `networking.gke.io/backend-services` annotation. Run the separate
   `https-access` Terraform Dev Plan and protected Apply for that exact backend
   and the owner-selected account. Confirm the live IAP policy contains only
   that account. Set the numeric backend ID and email variables.
6. Enable `DEV_HTTPS_ACTIVE` and run the normal protected App delivery to
   roll out assertion enforcement. From the approved account, verify UI and
   ticket API calls work; verify a second/unapproved account and anonymous
   requests fail. Check the app logs for successful signing-key retrieval and
   ensure key rotation can be fetched from the private Pods using existing
   Private Google Access. Do not add NAT unless a measured live failure proves
   it is necessary.
7. Only after those checks, dispatch the `application` edge stage with
   `confirm_application_route=true`. Publish the hostname A record manually
   only after IAP and route status are verified. Never add an HTTP listener or
   public database/control-plane path.

No App image publication, Gateway, DNS record, HTTPS URL, certificate status,
IAP login or public reachability is claimed from this offline implementation.
The completed database migration is not part of this flow and must not be run
again.

## Rebuild notes

The independent `helpdesk-edge` Helm release avoids taking ownership of the
Terraform IP, certificate or the normal `helpdesk` Deployment/Service. A future
cluster rebuild keeps the retained global IP/certificate foundation; recreate
the edge Gateway after rebuilding the cluster, wait for its backend name and
numeric ID, reapply the one-user IAP grant, and redeploy the app with the new
audience before opening the root route. DNS and external OAuth configuration
remain owner-managed. The existing migration Job and SQL are outside this
change.

## Local validation

- .NET Release build: passed with zero warnings.
- IAP and application validation checks: **24/24 passed**, including signature,
  issuer, audience, subject/email, time bounds, missing-token and unknown-key
  throttle cases. The documented IAP payload shape without `email_verified` is
  accepted; missing user identity claims are rejected.
- App Python regression suite: **42 tests passed**.
- Existing app chart and dormant HTTPS chart: Helm lint passed; the private
  release and exact health-only edge rendered manifests passed their scope
  guards.
- Neither an image nor a Kubernetes resource was published or applied.
