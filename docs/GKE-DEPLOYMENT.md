# First Dev deployment on GKE

**Status:** Phase 7 code is merged, but GKE creation and application deployment have not been verified. The current [infrastructure drift PR](https://github.com/mhachem110/HelpDeskCloud-Infra/pull/13) must be reviewed before any Apply. The application has no end-user login, so this guide uses a `ClusterIP` Service and localhost-only port-forward. Do not add a public Ingress, LoadBalancer or real customer data.

```text
Owner's Cloud Shell ──authenticated DNS endpoint──> Dev GKE control plane
Dev node SA ──repository Reader──> Dev Artifact Registry (image pulls)
App Pod KSA ──GSA Workload Identity──> Cloud SQL Auth Proxy ──private IP──> existing Cloud SQL
App Pod KSA ──managed CSI──> app connection-string Secret Manager version (read-only file)
Migration Job KSA ──own GSA and secret──> one-time SQL schema creation
Owner ──localhost kubectl port-forward──> internal HelpDesk Service
```

## Checkpoint 1 — review and prerequisites

1. Confirm the Phase 7 Infra and App PRs are merged into `dev`, their CI suites passed, and the remaining drift was resolved through a separately reviewed correction. Merging does not deploy GKE or the app.
2. Owner verifies Infra's `docs/PHASE7.md`: seven APIs, IAM prerequisites, quota, budget, network/subnet, reviewed Dev Plan and the 14 additions. The protected `dev-network-apply` workflow requires separate reviewer approval. Do not run Apply from this guide.
3. After approved Apply, use its read-only verification (or dispatch `verify-only`). Confirm the cluster's actual GKE version supports [native sidecars](https://kubernetes.io/docs/concepts/workloads/pods/sidecar-containers/) for the one-time Job (stable in Kubernetes 1.33), the managed Secret Manager CSI add-on, private nodes and DNS control-plane endpoint.
4. The human operator needs `container.clusters.get` plus the required Kubernetes namespace/deployment permissions. Terraform and application Pod identities are not human deployment identities. Commands below require owner approval when they create a secret version, database login, image, Job or workload.

```sh
PROJECT=helpdeskcloud-capstone-511905
REGION=us-east1
CLUSTER=helpdeskcloud-dev-gke
NAMESPACE=helpdesk-dev
REGISTRY="$REGION-docker.pkg.dev/$PROJECT/helpdeskcloud-dev-images"
gcloud container clusters describe "$CLUSTER" --region="$REGION" --project="$PROJECT" \
  --format='table(name,location,status,currentMasterVersion)'
gcloud container clusters get-credentials "$CLUSTER" --region="$REGION" --project="$PROJECT" --dns-endpoint
kubectl config current-context
kubectl get nodes -o wide
```

The [GKE `--dns-endpoint` flag](https://docs.cloud.google.com/sdk/gcloud/reference/container/clusters/get-credentials) intentionally avoids an IP endpoint. If connectivity fails, inspect identity and endpoint settings; do not open a public control-plane IP or add a NAT gateway automatically.

## Checkpoint 2 — namespace and identities

From the merged application `dev` checkout:

```sh
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
helm lint helm/helpdesk -f helm/helpdesk/values-dev.yaml \
  --set application.enabled=false
helm template helpdesk helm/helpdesk --namespace "$NAMESPACE" \
  -f helm/helpdesk/values-dev.yaml --set application.enabled=false \
  > /tmp/helpdesk-bootstrap.yaml
# Review the rendered objects; then apply only after owner approval.
kubectl apply --dry-run=server -n "$NAMESPACE" -f /tmp/helpdesk-bootstrap.yaml
kubectl apply -n "$NAMESPACE" -f /tmp/helpdesk-bootstrap.yaml
kubectl get serviceaccounts,secretproviderclasses -n "$NAMESPACE"
kubectl get serviceaccount helpdesk-dev-app -n "$NAMESPACE" -o yaml
```

This owner-controlled bootstrap installs two annotated Kubernetes ServiceAccounts, two managed CSI `SecretProviderClass` objects and the reviewed SQL ConfigMap. It starts no app or migration Pod and needs no image digest. It is intentionally outside the later application Helm release: the Dev delivery identity cannot change these bootstrap resources through Helm. `helpdesk-dev-app` maps to `helpdesk-app-dev@...`; `helpdesk-dev-migrate` maps to `helpdesk-migrate-dev@...`. Infra IAM grants the app and migration KSAs access to their **own** Secret Manager records. Managed CSI uses direct KSA principals; the Cloud SQL Auth Proxy uses KSA-to-GSA impersonation. [Google's managed CSI guide](https://docs.cloud.google.com/secret-manager/docs/secret-manager-managed-csi-component) describes the driver `secrets-store-gke.csi.k8s.io` and `provider: gke`.

## Checkpoint 3 — restricted PostgreSQL login and secrets

The existing SQL instance and `helpdesk` database have no application user or schema yet. First confirm an owner-controlled `postgres` admin password exists. If absent, establish one in the Google Cloud SQL console after owner approval; never pass it through Terraform or commit it. In [Cloud SQL Studio](https://docs.cloud.google.com/sql/docs/postgres/manage-data-using-studio), connect as the owner-controlled administrator to database `helpdesk` and execute this **non-secret** role definition:

```sql
CREATE ROLE helpdesk_restricted NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
```

Check for an existing role first. Do not rerun `CREATE ROLE` blindly. Then create the built-in `helpdesk` login in Cloud Shell with a strong owner-held password. Use an alphanumeric password of at least 32 random characters so it is also safe inside an Npgsql connection string. **The custom role assignment matters:** [Cloud SQL documents](https://docs.cloud.google.com/sql/docs/postgres/create-manage-users) that a built-in user created without a custom role can receive `cloudsqlsuperuser` automatically.

```sh
gcloud sql users create helpdesk --instance=helpdeskcloud-dev-postgres \
  --project="$PROJECT" --database-roles=helpdesk_restricted --prompt-for-password
gcloud sql users list --instance=helpdeskcloud-dev-postgres --project="$PROJECT" \
  --format='table(name,type,databaseRoles)'
```

The password prompt avoids a password in shell history and process arguments. Store the chosen password in an approved password manager. Verify the user has no `cloudsqlsuperuser`, `CREATEDB`, `CREATEROLE` or `SUPERUSER`. If Cloud SQL rejects `--database-roles` or the resulting role is broader than intended, **stop** and review instead of creating a default privileged user.

After Infra's secret **metadata** and IAM exist, add versions through an owner-controlled secure input. The following `read -s` values are local shell variables, are not exported, and are piped to `gcloud` through stdin. Run with shell tracing disabled and avoid screen recording; do not echo or paste credentials in tickets or CI logs.

```sh
set +x
read -r -s -p 'Postgres admin password: ' PG_ADMIN_PASSWORD; printf '\n'
printf '%s' "$PG_ADMIN_PASSWORD" | gcloud secrets versions add helpdesk-dev-db-admin-password \
  --project="$PROJECT" --data-file=- >/dev/null
unset PG_ADMIN_PASSWORD

read -r -s -p 'Restricted helpdesk password: ' APP_PASSWORD; printf '\n'
printf 'Host=127.0.0.1;Port=5432;Database=helpdesk;Username=helpdesk;Password=%s;SSL Mode=Disable' "$APP_PASSWORD" \
  | gcloud secrets versions add helpdesk-dev-db-connection --project="$PROJECT" --data-file=- >/dev/null
unset APP_PASSWORD

# Metadata only: never access or print payloads in routine verification.
gcloud secrets versions list helpdesk-dev-db-connection --project="$PROJECT" --format='table(name,state)'
gcloud secrets versions list helpdesk-dev-db-admin-password --project="$PROJECT" --format='table(name,state)'
```

`SSL Mode=Disable` applies only to the localhost hop. The Auth Proxy encrypts and authorizes the upstream connection to the existing private Cloud SQL address. It does **not** replace PostgreSQL password authentication. The app secret contains the restricted login; the migration secret contains only the admin password. Terraform state holds neither. Rotate by changing the database password through an approved procedure, adding a new secret version, and restarting the Pod after confirming CSI refresh behavior. Do not remove the prior version until the new Pod is healthy.

## Checkpoint 4 — trusted image publishing

Application CI must first pass its .NET, Docker, critical-vulnerability and Helm checks on the reviewed commit. Use Docker on an approved Cloud Shell or owner workstation with `gcloud` and repo-scoped Artifact Registry **Writer** permission. No service-account key or GitHub app-repository OIDC trust is introduced. The Dev node SA only has Reader, so it cannot publish.

```sh
gcloud auth configure-docker "$REGION-docker.pkg.dev"
COMMIT=$(git rev-parse --short=12 HEAD)
APP_IMAGE="$REGISTRY/helpdeskcloud"
docker build --platform linux/amd64 -t "$APP_IMAGE:$COMMIT" .
# Run the approved critical-vulnerability scanner before this push; CI also scans the same source.
docker push "$APP_IMAGE:$COMMIT"
APP_DIGEST=$(gcloud artifacts docker images describe "$APP_IMAGE:$COMMIT" \
  --project="$PROJECT" --format='value(image_summary.digest)')
printf 'Application digest: %s\n' "$APP_DIGEST"
```

Use the current reviewed [official Cloud SQL Auth Proxy v2.26.2](https://github.com/GoogleCloudPlatform/cloud-sql-proxy/releases/tag/v2.26.2) image and [Docker Official PostgreSQL 17.11 Alpine](https://github.com/docker-library/official-images/blob/master/library/postgres) client. Verify publisher, digest, architecture and scan results before mirroring. Private GKE nodes pull these from the **existing** regional Artifact Registry rather than requiring Cloud NAT or external registry reachability. The source tags identify versions; **deployment uses the destination digests**.

```sh
PROXY_SOURCE=gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.26.2
PG_SOURCE=postgres:17.11-alpine3.24
PROXY_IMAGE="$REGISTRY/cloud-sql-proxy"
PG_IMAGE="$REGISTRY/postgres-client"
docker pull --platform linux/amd64 "$PROXY_SOURCE"
docker pull --platform linux/amd64 "$PG_SOURCE"
# Inspect image provenance and scan before approving these two pushes.
docker tag "$PROXY_SOURCE" "$PROXY_IMAGE:2.26.2"
docker tag "$PG_SOURCE" "$PG_IMAGE:17.11-alpine3.24"
docker push "$PROXY_IMAGE:2.26.2"
docker push "$PG_IMAGE:17.11-alpine3.24"
PROXY_DIGEST=$(gcloud artifacts docker images describe "$PROXY_IMAGE:2.26.2" \
  --project="$PROJECT" --format='value(image_summary.digest)')
PG_DIGEST=$(gcloud artifacts docker images describe "$PG_IMAGE:17.11-alpine3.24" \
  --project="$PROJECT" --format='value(image_summary.digest)')
printf 'Proxy digest: %s\nPostgreSQL client digest: %s\n' "$PROXY_DIGEST" "$PG_DIGEST"
```

Every digest must match `sha256:` plus 64 lowercase hex characters and refer to a Linux/amd64 image that passed scanning. Store the three non-secret digests in the deployment record. Do not replace an immutable tag or use `latest`.

## Checkpoint 5 — one-time schema migration

Inspect `helm/helpdesk/files/001_init.sql` (copied from `database/init.sql`) and `002_grants.sql` before execution. The Job uses the admin password only, creates `public.tickets` and indexes in one transaction, then grants `SELECT`, `INSERT`, `UPDATE`, `DELETE` on that table and schema `USAGE` to `helpdesk`. The ordinary app login does not own the table or receive schema administration rights. The Job uses the separate migration KSA and [native restartable init sidecar](https://kubernetes.io/docs/concepts/workloads/pods/sidecar-containers/) so the Auth Proxy ends when `psql` exits; it is **not** part of normal app upgrades. Review the rendered manifest first:

```sh
helm template helpdesk helm/helpdesk --namespace "$NAMESPACE" \
  -f helm/helpdesk/values-dev.yaml \
  --set application.enabled=false --set migration.enabled=true \
  --set-string cloudSqlProxy.image.digest="$PROXY_DIGEST" \
  --set-string migration.image.digest="$PG_DIGEST" \
  --show-only templates/migration-job.yaml > /tmp/helpdesk-migration-job.yaml
kubectl apply --dry-run=server -n "$NAMESPACE" -f /tmp/helpdesk-migration-job.yaml
# Only after explicit owner approval of the SQL and Job:
kubectl apply -n "$NAMESPACE" -f /tmp/helpdesk-migration-job.yaml
kubectl wait -n "$NAMESPACE" --for=condition=complete job/helpdesk-dev-schema-001 --timeout=10m
kubectl logs -n "$NAMESPACE" job/helpdesk-dev-schema-001 -c migrate
```

`/tmp/helpdesk-migration-job.yaml` contains no password. If the Job fails, inspect Pod events, proxy/CSI/Workload Identity access and `psql` errors. SQL is executed with `ON_ERROR_STOP` inside one transaction, so a failed attempt rolls back. Do not delete/recreate the Job merely to suppress a failure; review state and use a new versioned migration after fixing the cause. A later read-only SQL check should verify `public.tickets` exists and `helpdesk` can select/insert/update/delete a synthetic row but cannot create tables or databases. Avoid production data.

## Checkpoint 6 — application deployment and evidence

The Dev values require real immutable digests. A blank or invalid digest fails Helm rendering. Normal upgrades do **not** run the schema Job because `migration.enabled=false`.

```sh
helm lint helm/helpdesk -f helm/helpdesk/values-dev.yaml -f helm/helpdesk/values-dev-delivery.yaml \
  --set-string image.digest="$APP_DIGEST" --set-string cloudSqlProxy.image.digest="$PROXY_DIGEST"
helm template helpdesk helm/helpdesk --namespace "$NAMESPACE" \
  -f helm/helpdesk/values-dev.yaml -f helm/helpdesk/values-dev-delivery.yaml \
  --set-string image.digest="$APP_DIGEST" --set-string cloudSqlProxy.image.digest="$PROXY_DIGEST" \
  > /tmp/helpdesk-dev.yaml
kubectl apply --dry-run=server -n "$NAMESPACE" -f /tmp/helpdesk-dev.yaml
# Only after owner approval of the manifest and cost:
helm upgrade --install helpdesk helm/helpdesk --namespace "$NAMESPACE" \
  -f helm/helpdesk/values-dev.yaml -f helm/helpdesk/values-dev-delivery.yaml \
  --set-string image.digest="$APP_DIGEST" --set-string cloudSqlProxy.image.digest="$PROXY_DIGEST" \
  --wait --timeout 10m
helm status helpdesk -n "$NAMESPACE"
kubectl rollout status deployment/helpdesk-helpdesk -n "$NAMESPACE" --timeout=5m
kubectl get pods,service -n "$NAMESPACE" -o wide
```

Confirm the Deployment has two replicas, each with the application and its own Cloud SQL Auth Proxy sidecar, digest-pinned images, a read-only CSI mount, the intended KSA, `/health/live` and `/health/ready` probes, and a `ClusterIP` Service. Autoscaling remains disabled for this initial deployment. Confirm each proxy uses `--private-ip` and the existing instance connection name; inspect logs without dumping environment variables. Confirm node image pulls use the node SA's repository Reader permission. The GKE API verifier cannot prove actual Pod-to-SQL connectivity; `/health/ready` and ticket operations do.

For a localhost-only owner demonstration, use a shell on the **owner's computer** that has authorized `kubectl` access (Cloud Shell port-forward only exposes its own localhost):

```sh
kubectl port-forward --address 127.0.0.1 -n "$NAMESPACE" service/helpdesk-helpdesk 8080:80
# In a separate terminal on the same computer:
curl -fsS http://127.0.0.1:8080/health/live
curl -fsS http://127.0.0.1:8080/health/ready
```

If using Cloud Shell, its localhost belongs to the Cloud Shell VM; use its built-in preview only after reviewing exposure, or use a local workstation with the DNS-based kubeconfig. Perform create, list, update and delete with **synthetic** ticket data, then restart only the app Pod and confirm persistence. Record the commit and image digests, cluster version, Helm revision, Pod status, private service type, readiness response and sanitized CRUD results. Do not record secret payloads or Terraform state.

## Failures and rollback

| Symptom | First checks |
| --- | --- |
| `ImagePullBackOff` | Verify destination image digest/architecture, node SA, repository Reader IAM and Private Google Access. Do not add a public IP by default. |
| CSI mount failure | Check secret version exists, direct KSA secretAccessor on the **one** secret, SecretProviderClass name and managed add-on status. Do not print payloads. |
| Proxy not ready | Inspect Cloud SQL Client on app/migration GSA, KSA annotation, WIF binding, exact instance name and private VPC reachability. |
| App not ready | Check proxy readiness, mounted file presence (not contents), restricted role, `public.tickets`, table grants and app logs without secrets. |
| Job does not Complete | Verify Kubernetes native sidecar support, `psql` error and SQL transaction outcome; do not rerun blindly. |

For a bad **application** release, inspect `helm history helpdesk -n "$NAMESPACE"`, review the earlier revision, then run an owner-approved `helm rollback helpdesk REVISION -n "$NAMESPACE" --wait`. This does not roll back database schema or Terraform infrastructure. Scale the Deployment to zero only after owner approval if Pod cost must stop; Cloud SQL and cluster management charges continue. Preserve GKE deletion protection and never use `terraform destroy` as incident response.

Local `docker compose up --build` still reads `ConnectionStrings__Default`. The mounted-file path is used only when `DATABASE_CONNECTION_STRING_FILE` is set by the Dev Helm values. Phase 8 can add a separate approved image-publisher/CD identity and promotion gates.
