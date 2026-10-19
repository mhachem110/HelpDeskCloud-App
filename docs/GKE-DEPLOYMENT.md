# First Dev deployment on GKE

**Status as of 2026-10-19:** the owner reports that Terraform, GKE, namespace/bootstrap objects, the restricted application login and Secret Manager versions are deployed. This PR does not query GCP or read secret payloads. The supporting images remain unpublished, the schema migration has not run, and the application delivery workflow remains disabled. The application has no end-user login, so delivery stays on a `ClusterIP` Service and localhost-only port-forward. Do not add a public Ingress, LoadBalancer or real customer data.

```text
Protected GitHub workflow ──separate WIF identity──> Dev GKE DNS endpoint
Dev node SA ──repository Reader──> Dev Artifact Registry (image pulls)
App Pod KSA ──GSA Workload Identity──> Cloud SQL Auth Proxy ──private IP──> existing Cloud SQL
App Pod KSA ──managed CSI──> app connection-string Secret Manager version (read-only file)
Migration Job KSA ──own GSA and secret──> one-time SQL schema creation
Owner ──localhost kubectl port-forward──> internal HelpDesk Service
```

## Checkpoint 1 — review and prerequisites

The owner reports that the Dev GKE cluster is deployed. This guide does not run Terraform or make infrastructure changes. If the live state differs from the owner-reported checkpoint, stop and return to the infrastructure review before continuing. Confirm the actual cluster version supports Kubernetes native sidecars, the managed Secret Manager CSI add-on, private nodes and the DNS control-plane endpoint. The CI workflows also verify the exact project, cluster, namespace and bootstrap objects before a protected operation.

The application has no end-user login. Keep its Service internal and use localhost-only port-forward for an owner demonstration. Do not add a public IP, Ingress, LoadBalancer or real customer data.

## Checkpoint 2 — owner-controlled namespace and secret bootstrap

**Reported complete:** the `helpdesk-dev` namespace, `helpdesk-dev-app` and `helpdesk-dev-migrate` ServiceAccounts, the app and admin SecretProviderClasses, and `helpdesk-dev-schema-001` ConfigMap are already present. Do not rerun Helm bootstrap or recreate these objects. The migration workflow checks the migration KSA, admin SecretProviderClass and ConfigMap before it creates a Job.

Use only read-only inspection when confirming the checkpoint. Never print Secret Manager payloads. App KSA access remains limited to the app connection secret; migration KSA access remains limited to the migration administrator secret. The app and migration KSAs use separate Google service accounts.

## Checkpoint 3 — restricted PostgreSQL login and secrets

**Reported complete:** the restricted application login and Secret Manager versions are already configured. Do not recreate database users or add new secret versions as part of this phase. The CI workflows do not read secret payloads. Confirm only metadata and access bindings through the approved owner process; never print secret contents into a terminal, workflow log, or issue.

The app connection secret holds the restricted `helpdesk` login. The migration secret holds the owner-controlled database administrator password and is mounted only through the migration Job's SecretProviderClass. Localhost `SSL Mode=Disable` applies only to the Pod-to-proxy hop; the Auth Proxy secures the upstream Cloud SQL connection. The migration workflow validates the expected Kubernetes objects but does not read or copy either secret value.

## Checkpoint 4 — gated supporting-image publication

Supporting images remain unpublished until the separate publisher identity and reviewer gate are approved.

`Supporting images CI and gated publication` builds the pinned Cloud SQL Auth Proxy 2.26.2 image and `database/migration-client/Dockerfile`, checks Linux/amd64 and the `psql`/`pg_isready` commands, and blocks fixable critical Trivy findings. A trusted `dev` run attests and verifies the exact archives. The manual publication job rechecks those attestations before Google authentication, checks Artifact Registry immutable tags, publishes unique non-overwriting tags, and records the actual registry digests.

Before enabling its publisher, review the separate WIF provider and service account, repository-only `roles/artifactregistry.writer` grant, and `dev-supporting-images-publish` Environment with a required reviewer and exactly the `dev` branch policy. Keep `DEV_SUPPORTING_IMAGES_PUBLISH_ENABLED` unset until this review is complete. The owner then sets it to `true`, dispatches the workflow on `dev` with `approve_publication=true`, and approves the protected Environment after reviewing the scan and provenance results. Copy the output digests into repository variables `DEV_PROXY_IMAGE_DIGEST` and `DEV_MIGRATION_IMAGE_DIGEST` only after reviewing the run summary. Do not publish from Cloud Shell or use service-account keys.

The existing Artifact Registry repository is configured for immutable tags. The source Proxy image and Alpine base image are digest-pinned; the migration client pins its PostgreSQL and certificate package versions. A partial two-image push can leave the first immutable image in the repository. Review the run and use a new workflow attempt for a retry; do not move or delete tags.

## Checkpoint 5 — one-time schema migration

Review `helm/helpdesk/files/001_init.sql`, `002_grants.sql` and the rendered Job. It uses the restricted migration KSA `helpdesk-dev-migrate`, its existing `helpdesk-migrate-dev` GSA, the existing admin-password SecretProviderClass, the pinned Cloud SQL Auth Proxy sidecar and the digest-pinned PostgreSQL client. The SQL creates `public.tickets` and indexes in one transaction and grants only the required table operations to `helpdesk`. This Job is outside normal application delivery.

The manual-only `Approved Dev database migration` workflow lints and renders only `templates/migration-job.yaml` without cloud credentials. It is disabled unless `DEV_DB_MIGRATION_ENABLED=true` and the operator types exactly `RUN helpdesk-dev-schema-001`. The separate `dev-db-migration` Environment must require a reviewer and allow exactly the `dev` branch. After approval, the workflow authenticates with a dedicated GitHub WIF migration-runner identity, checks the DNS GKE context and existing bootstrap objects, performs a server-side dry run, refuses to replace an existing Job, then creates and waits for the fixed Job. A failed or already-existing Job is left for review; the workflow does not delete or rerun it.

Before enabling it, configure the separate WIF provider and service account with project `roles/container.clusterViewer`, then apply the reviewed `k8s/dev-migration-runner-rbac.yaml` RoleBinding in `helpdesk-dev`. The Role grants Job create/get/list/watch in that namespace, Pod/log reads, and reads of only the migration KSA, admin SecretProviderClass and schema ConfigMap. Kubernetes RBAC cannot scope Job create by object name; the fixed workflow, branch protection and Environment approval provide the additional control. The GitHub runner identity receives no Cloud SQL or Secret Manager access. Those permissions remain with the migration Pod KSA/GSA configured by the existing platform bootstrap.

If the fixed Job already exists or fails, inspect its status and logs without deleting it. Do not rerun blindly; review the SQL transaction and database state before preparing a new versioned migration.

## Checkpoint 6 — protected application delivery

The existing `Application Dev delivery` workflow replaces manual Helm deployment. It consumes the reviewed app digest and `DEV_PROXY_IMAGE_DIGEST`, runs Helm lint/render and server dry-run, then performs the release after the separate `dev-app-deploy` approval. It uses the `dev-app-publish` and `dev-app-deploy` Environments with their existing reviewer gates, deploys two replicas behind ClusterIP only, and checks health through localhost-only port-forward. Migration stays disabled during application upgrades.

Keep `DEV_APP_CD_ENABLED` unset until the migration completed and all existing publisher/deployer prerequisites in `docs/PHASE8.md` are reviewed. The workflow also runs on every push to `dev`, so enabling the variable makes the next merge eligible for publication and deployment approvals. No public Ingress or LoadBalancer is introduced.

## Failures and rollback

| Symptom | First checks |
| --- | --- |
| `ImagePullBackOff` | Verify destination image digest/architecture, node SA, repository Reader IAM and Private Google Access. Do not add a public IP by default. |
| CSI mount failure | Check secret version exists, direct KSA secretAccessor on the **one** secret, SecretProviderClass name and managed add-on status. Do not print payloads. |
| Proxy not ready | Inspect Cloud SQL Client on app/migration GSA, KSA annotation, WIF binding, exact instance name and private VPC reachability. |
| App not ready | Check proxy readiness, mounted file presence (not contents), restricted role, `public.tickets`, table grants and app logs without secrets. |
| Job does not Complete | Verify Kubernetes native sidecar support, `psql` error and SQL transaction outcome; do not rerun blindly. |

For a bad **application** release, inspect `helm history helpdesk -n "$NAMESPACE"`, review the earlier revision, then run an owner-approved `helm rollback helpdesk REVISION -n "$NAMESPACE" --wait`. This does not roll back database schema or Terraform infrastructure. Scale the Deployment to zero only after owner approval if Pod cost must stop; Cloud SQL and cluster management charges continue. Preserve GKE deletion protection and never use `terraform destroy` as incident response.

Local `docker compose up --build` still reads `ConnectionStrings__Default`. The mounted-file path is used only when `DATABASE_CONNECTION_STRING_FILE` is set by the Dev Helm values. Phase 8 now prepares separate protected identities for supporting-image publication, the one-time database migration and application delivery. Review the exact IAM, Environment, RBAC and repository-variable prerequisites in [PHASE8.md](PHASE8.md) before enabling any workflow.
