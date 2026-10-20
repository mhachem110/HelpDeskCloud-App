# Permanent HTTPS access: application handoff

Status: preparation only. The working release stays private. The owner has no
selected domain and wants IAP limited to one configurable personal Google
account. No email is inferred or hardcoded. No DNS, OAuth client, LB or cluster
change is made by this PR. Full platform design and verified cloud inventory:
[Infra HTTPS design](https://github.com/mhachem110/HelpDeskCloud-Infra/blob/codex/https-access-design/docs/HTTPS-ACCESS-DESIGN.md).

## Current serving boundary

The successful [delivery 39466841649](https://github.com/mhachem110/HelpDeskCloud-App/actions/runs/39466841649)
built/scanned source, published the image, deployed by digest and passed rollout
and probe checks. Read-only GKE inspection on 2026-10-20 found two ready
`helpdesk-helpdesk` replicas and a ClusterIP Service on port 80. No Ingress,
Gateway, HTTPRoute or NetworkPolicy exists yet. Website access currently uses
port-forwarding because no external frontend routes to that Service.

`Program.cs` has no end-user authentication/authorization and the ticket
repository does not filter by caller or owner. Any caller reaching its API can
operate on all tickets. IAP will admit only the configured account to the site,
but will not add application roles or ticket-level isolation. Use demonstration
data until application authorization is separately designed.

## Implemented in this PR

`.github/scripts/check-private-release.py` validates the exact rendered App
release before the server dry run and Helm upgrade. It permits only the existing
two-replica Deployment and internal Service, rejects routing/bootstrap resources,
public Service types/addressing, proxy ports, edge annotations, host networking
and host ports. Application CI runs the same check. Regression tests exercise
public-exposure bypass attempts and verify the checks precede Kubernetes writes.

This checks desired YAML. GKE/Helm may add their own live annotations; the script
does not read or rewrite those objects. It is a focused ownership/exposure check,
not a replacement for Kubernetes admission, IAM, Trivy or application security.

The Helm templates, values, application code, migration Job, RBAC and WIF names
are unchanged. CI still uses read-only permissions; publication/deployment remain
separate protected jobs. The offline parser dependency is pinned and installed
before the deploy job requests Google credentials.

## Proposed routing ownership

Use GKE Gateway `gke-l7-global-external-managed`, a retained static IP and
Google-managed certificate, and backend IAP. The existing ClusterIP and
private-IP SQL proxy path remain. An owner-selected hostname is required;
Cloud DNS is optional. See the Infra design for OAuth, costs and resource owners.

The **platform bootstrap** owns Gateway, HTTPRoute, GCPGatewayPolicy, GCPBackendPolicy,
HealthCheckPolicy, OAuth Secret delivery and app ingress NetworkPolicy. These
will live outside `helm/helpdesk/templates`, with a separately reviewed stage
behind the existing deployment approval. The app release continues to own only
Deployment and Service, so future application upgrades cannot silently remove
platform policies or adopt Terraform resources. No App RBAC expansion is needed
for this preparation. Future edge writes require a reviewed namespace Role for
only the necessary resource kinds; no cluster-admin or CRD/GatewayClass writes.

Do not add an `enabled` value that silently creates public routes on a normal
App merge. Do not rename `app-dev-delivery.yml` or change protected Environment
names: existing WIF conditions bind the exact workflow, repository IDs, dev
branch and `dev-app-publish` / `dev-app-deploy` Environments.

## Required later application work before exposure

Prepare a separate reviewed .NET change that validates signed IAP JWT assertions
on every UI/API path, with only the exact `/health/live` and `/health/ready`
paths exempt for probes. Validate ES256 signature against Google's rotating
keys, issuer, time claims and exact backend audience; reject missing/forged
assertions and never trust unsigned email headers. Use a maintained library and
cached key refresh. This validates Google's identity boundary without adding a
custom login system. [Google's signed-header guidance](https://docs.cloud.google.com/iap/docs/signed-headers-howto).

Use explicit opt-in enforcement, disabled for the current private release.
Enabling it without a valid backend audience must fail startup. Supply only
non-secret enforcement/audience settings through the existing reviewed Helm
Deployment, after GKE allocates the backend. Verify key retrieval from private
Pods before rollout; do not automatically add NAT or change SQL egress.

Create only an Exact `/health/live` bootstrap route initially, configure/verify
backend IAP and its single-account IAM grant, then deliver the signed-assertion
app configuration through protected publication/deployment. Open the hostname's
root route only after negative auth tests pass. This avoids exposing ticket
paths during asynchronous LB/IAP reconciliation. No such route is created here.

The personal account is a required `iap_allowed_email` configuration in the
platform access phase, with no default. Its value produces exactly one
`user:` binding at the backend, never a project-wide/wildcard grant. The custom
OAuth client ID, client secret delivery and consent configuration are separate
inputs. Never put OAuth secrets in Helm values or workflow logs. The current
Helm deployer can read namespace Secrets and edit Pod templates; treat it as a
trusted deployment identity rather than claiming it cannot access an OAuth
Secret in that namespace.

## Later acceptance and rebuild

Preserve existing health probes, two replicas, immutable images, CSI connection
secret, loopback proxy and internal Service. Use `/health/ready` on app port 8080
for the LB HealthCheckPolicy; Gateway does not infer the Pod readiness probe.
Future tests must reject unsigned, expired, invalid-signature and wrong-audience
requests; check anonymous redirect/rejection and unapproved-account denial;
verify the allowed account can create/read/update demonstration tickets. The
existing localhost health smoke test remains useful, but cannot verify IAP.

When the cluster is rebuilt, bootstrap the namespace/identities, restore the
app's existing delivery prerequisites, discover the new generated backend ID,
recreate backend IAM and update the app audience before restoring root routing.
Static IP, certificate authorization DNS, OAuth credentials and reviewed allowed
account config should survive the disposable cluster lifecycle. The current
Terraform guard does not yet implement full destroy/empty-state rebuild.

Neither a working HTTPS URL nor a functioning certificate/IAP boundary is
claimed by these static changes. Domain selection, OAuth/account inputs,
reviewed implementation PRs and explicit deployment approval remain required.

## Preparation checks

Local .NET Release build and 11 validation checks passed. The 34 Python tests,
including exposure and workflow-order regressions, passed. Helm lint and Dev,
delivery and offline migration manifest renders passed. Kubeconform 0.8.0 with
the CI's Kubernetes 1.33.0 schemas found 15 valid resources, zero errors/invalid
resources, and four existing SecretProviderClass documents without CRD schemas.
The local Linux image build and Trivy 0.75.0 fixable-CRITICAL scan passed with
zero findings at that threshold. No image was published. Actionlint syntax
validation passed with ShellCheck disabled; the full run reported two existing
ShellCheck warnings in unchanged smoke-test/summary shell code.
