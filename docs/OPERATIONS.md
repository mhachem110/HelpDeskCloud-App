# Operations and safe checks

## Current service signals

Use Google Cloud and GitHub read-only views to inspect the existing project, cluster, namespace, Gateway, backend policy, certificate and protected workflow results. Avoid reading ticket rows or secret payloads during routine health checks.

From an authorized GKE context, useful checks include:

    kubectl get deployment,service,pods -n helpdesk-dev
    kubectl get gateway,httproute,gcpbackendpolicy,healthcheckpolicy -n helpdesk-dev
    kubectl get pods -n helpdesk-dev -o wide
    helm history helpdesk -n helpdesk-dev
    helm history helpdesk-edge -n helpdesk-dev

For public checks, use ordinary HTTPS so the client verifies the certificate:

    curl --silent --show-error --dump-header - --output /dev/null https://helpdeskcloud.dynv6.net/
    curl --silent --show-error --dump-header - --output /dev/null https://helpdeskcloud.dynv6.net/api/tickets
    curl --silent --show-error --dump-header - --output /dev/null https://helpdeskcloud.dynv6.net/health/live

An anonymous request should be redirected through the configured Google IAP OAuth flow or receive an IAP denial. A 200 response or an unrelated redirect on /api/tickets is a security incident. Do not use TLS bypass flags. The owner has verified approved-account access, unauthorized-account denial and ticket persistence; deployment workflow #20 also records successful full HTTPS route validation.

## Terraform operations

The three state roots remain isolated: terraform/ uses prefix helpdeskcloud/dev; terraform/https-foundation/ uses helpdeskcloud/dev-https; terraform/https-access/ uses helpdeskcloud/dev-https-access. Read-only manual Plan is available for core, https-foundation and https-access. Apply is manual, uses a fresh plan and waits on dev-network-apply; it checks protected branch/environment, strict plan safety, drift fingerprint and resource evidence.

Terraform fmt, backend-free init, validate, TFLint, Checkov and offline Python guard tests are repository validations. A zero-change plan does not by itself mean provider drift is absent. Never use destroy, state migration, ad hoc state editing or resource replacement as routine cleanup. Review the full plan and obtain protected approval for any infrastructure change.

## Access and IAM

The project-level Terraform service account intentionally retains roles/iap.admin because the owner requested it after prior IAM access failures. Preserve it. The application access grant is separately scoped to the single approved Google user on the exact GKE backend. Do not widen the user grant or add project-wide IAP access. Application JWT validation remains enabled as defense in depth.

The deployment RBAC manifests are namespace-scoped and must be reapplied after a cluster rebuild. App delivery needs the Gateway and GKE policy resources to reconcile the edge; migration access is separate. Do not grant cluster-admin to either identity.

## Deprecated FreeDNS certificate resources

The active hostname is helpdeskcloud.dynv6.net. Older FreeDNS resources for helpdeskcloud.chickenkiller.com remain Terraform-managed and protected by prevent_destroy:

- google_certificate_manager_dns_authorization.https
- google_certificate_manager_certificate.https
- google_certificate_manager_certificate_map_entry.https

They share the existing google_certificate_manager_certificate_map.https map with the active dynv6 certificate-map entry. The active Gateway points to the shared map and active hostname; it does not need the old hostname entry for its current route. The old DNS authorization and certificate remain dependencies of the legacy map entry.

Do not remove the old blocks or state during routine cleanup. A future decommission requires independent confirmation that no DNS record, certificate consumer, rollback path or other map entry uses the old hostname; a reviewed Terraform plan; owner approval; removal of the old DNS authorization only after its certificate is retired; then a separate state-backed change that preserves the shared map, active dynv6 entry, static IP and TLS policy. This repository cleanup performs none of those actions.

## Historical incident note

Delivery run #19 briefly saw HTTP 404 on / while the GKE Gateway controller was still propagating an HTTPRoute. The delivery edge stage now waits separately for controller conditions and for bounded external IAP responses on each application path. Run #20 succeeded with the full HTTPS application route.
