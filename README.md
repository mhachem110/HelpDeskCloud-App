# HelpDesk Cloud — Application

A modern support-ticket platform built with **ASP.NET Core (.NET 10)**, **PostgreSQL**, **Docker**, and a **Kubernetes Helm chart**. The application repository is deliberately independent of the Terraform/GCP infrastructure repository.

> **Security/scope:** This is a functional capstone MVP, **not yet a publicly deployable authenticated product**. There is currently **no end-user login or authorization**. Do **not** expose it publicly, store real employee/customer data, or call it production-ready until an identity-aware ingress/authentication layer, HTTPS, backups, and platform controls have been configured and verified. Those belong in the infrastructure/security phases.

## What works now

- Responsive HelpDesk dashboard with summary cards, filter/search and status chart
- Create, list, search, edit and delete IT tickets (status, priority, category, description)
- PostgreSQL persistent ticket storage (shared by all app replicas)
- Input validation in the API **and** PostgreSQL CHECK constraints; parameterized SQL
- `/health/live` and `/health/ready` for Kubernetes probes
- Rate limiting, basic browser security headers, non-root runtime image
- Local `docker compose up` development environment (app + PostgreSQL)
- Helm Deployment, ClusterIP Service, ServiceAccount, optional HPA
- GitHub Actions **credential-free PR CI** (compile, tests, Docker build/scan, secret scan, Helm lint/render)
- Prepared Dev delivery workflow with separate approvals for image publication and GKE deployment; disabled until owner-approved identities and live prerequisites exist
- No hardcoded cloud credentials or Terraform state in this repository

## Phase 7 Dev GKE preparation

The chart now has a [Dev-specific deployment guide](docs/GKE-DEPLOYMENT.md) and `helm/helpdesk/values-dev.yaml`. It prepares two internal `ClusterIP` replicas, each with digest-pinned app and Cloud SQL Auth Proxy containers, a read-only managed Secret Manager CSI connection-string file, dedicated app and migration identities, and a separately approved one-time schema Job. Autoscaling is disabled for the initial deployment. The app still uses `ConnectionStrings__Default` for local Docker Compose. Dev image digests are intentionally empty until owner-approved image publication; Helm refuses to render a Dev workload without real digests. No cluster, image, database user, secret payload or workload is created by merging this application PR.

## Quickest start — Docker Desktop

Requirements: [Docker Desktop](https://docs.docker.com/desktop/) with Linux containers. .NET does not need to be installed if using Docker.

1. Clone the `dev` branch of `mhachem110/HelpDeskCloud-App`.
2. In the project root, create your private `.env` file:

   ```powershell
   Copy-Item .env.example .env
   ```

   Edit `.env` and change `POSTGRES_PASSWORD` to a unique local-only password. **Do not commit `.env`.**

3. Start the application:

   ```powershell
   docker compose up --build -d
   docker compose ps
   ```

4. Open **http://localhost:8080** and create a sample ticket.
5. Verify the API and health endpoints:

   ```powershell
   Invoke-RestMethod http://localhost:8080/health/live
   Invoke-RestMethod http://localhost:8080/health/ready
   Invoke-RestMethod http://localhost:8080/api/tickets/stats
   ```

6. View logs or stop containers:

   ```powershell
   docker compose logs -f app
   docker compose down
   ```

`docker compose down` preserves your ticket database in the Docker volume. `docker compose down -v` **deletes** the local database. Avoid `-v` unless you want a complete reset.

**Important:** The SQL schema `database/init.sql` runs only when the PostgreSQL volume is *first created*. For a future change to database structure, add a versioned migration instead of editing the initial file and expecting a populated volume to reinitialize.

## Project structure

```text
HelpDeskCloud-App/
├── .github/workflows/app-ci.yml        # credential-free PR validation
├── .github/workflows/app-dev-delivery.yml # gated Dev image publication and GKE rollout
├── .github/scripts/verify-dev-environment.sh # fail-closed Environment policy check
├── src/HelpDeskCloud/
│   ├── Program.cs                       # minimal API routes and middleware
│   ├── Data/                            # PostgreSQL repository and readiness probe
│   ├── Models/                          # ticket request/response models
│   ├── Validation/                      # ticket input validation
│   ├── wwwroot/                         # accessible HTML/CSS/JS dashboard
│   └── HelpDeskCloud.csproj
├── tests/HelpDeskCloud.Tests/           # dependency-light test executable
├── database/init.sql                   # initial PostgreSQL schema for local DB
├── helm/helpdesk/                       # base chart, Dev values, delivery overlay and one-time migration SQL
├── docs/GKE-DEPLOYMENT.md              # approved first-deployment checkpoints
├── docs/PHASE8.md                      # identity and delivery activation plan
├── docs/FINAL-PROJECT-DEMO.md          # evidence-driven capstone walkthrough
├── k8s/dev-delivery-rbac.yaml          # proposed namespace-only release access
├── Dockerfile
├── compose.yaml
├── .env.example
└── README.md
```

## Run without Docker for the application

If you have .NET 10 SDK and a PostgreSQL database already started:

```powershell
$env:ConnectionStrings__Default='Host=localhost;Port=5432;Database=helpdesk;Username=helpdesk;Password=YOUR_LOCAL_PASSWORD'
dotnet run --project src/HelpDeskCloud --urls http://localhost:8080
```

You still need to apply `database/init.sql` to that database once. Prefer `docker compose up` to avoid manual setup.

Validation tests:

```powershell
dotnet run --project tests/HelpDeskCloud.Tests -c Release
```

The included test project covers request validation. It is **not** an end-to-end integration test of PostgreSQL, so verify ticket creation/editing/deletion through Docker Compose as well.

## REST API

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/info` | App metadata |
| `GET` | `/api/tickets` | List latest 200; filters `status`, `priority`, `search` |
| `GET` | `/api/tickets/stats` | Dashboard totals |
| `GET` | `/api/tickets/{id}` | One ticket |
| `POST` | `/api/tickets` | Create a new ticket |
| `PUT` | `/api/tickets/{id}` | Update all editable fields |
| `DELETE` | `/api/tickets/{id}` | Remove a ticket |
| `GET` | `/health/live` | Process is running |
| `GET` | `/health/ready` | PostgreSQL connection + tickets schema ready |

Create request example:

```json
{
  "title": "Cannot connect to VPN",
  "description": "VPN times out after entering credentials.",
  "category": "Network",
  "priority": "High"
}
```

Update request must also include `status`: `Open`, `In Progress`, or `Resolved`.

## GitHub branching and CI

This repo uses the agreed branch flow:

```text
feature/* --PR--> dev --PR--> stage --PR--> prod
```

`dev`, `stage`, and `prod` are protected. A normal PR **only validates** changes; CI has no GCP credential. The [Dev delivery workflow](docs/PHASE8.md) is prepared for approved merges to `dev` but is disabled until a separate application OIDC setup, protected GitHub Environments and live GKE/database prerequisites are reviewed. It builds and scans one image, publishes its immutable digest through a dedicated publisher, then uses a separate deployment identity and approval to release that digest. Stage/Prod cloud deployment is not configured.

GitHub Actions should later require the names of real completed checks before merging. You can currently find the PR workflow in `.github/workflows/app-ci.yml`.

## GKE deployment chart (prepared; not deployed)

The Helm chart assumes:

1. Artifact Registry is provisioned and GKE can pull the image.
2. Cloud SQL PostgreSQL is available and its schema has been applied using a restricted, controlled migration process.
3. In Dev, the pre-existing `helpdesk-dev-db-connection` Secret Manager version is mounted as a read-only file by managed CSI. The bootstrap creates its `SecretProviderClass` separately from the app Helm release. Local Compose still uses `ConnectionStrings__Default`. Never put the database password into Git, Helm values, or CLI history.
4. An authenticated HTTPS ingress/IAP or equivalent is configured **before** internet exposure.

Example render (safe; does not deploy):

```bash
helm lint helm/helpdesk --set image.repository=example.invalid/helpdesk
helm template helpdesk helm/helpdesk --set image.repository=example.invalid/helpdesk --set image.tag=1.0.0
```

Do **not** deploy to GKE with the placeholder image or missing database Secret. These will be supplied by the Terraform/CI-CD phases.

## GCP security decisions

- Cloud CI/CD identity: proposed separate publisher/deployer OIDC identities, pending owner approval
- Runtime identity: GKE Workload Identity Federation in merged Phase 7 Terraform; live deployment pending
- Secrets: Google Secret Manager metadata in Phase 7 Terraform; payloads and mounts pending approval
- Database: private Cloud SQL for PostgreSQL exists; restricted user and schema pending approval
- Authorization: identity-aware ingress / login and least-privilege authorization (**required before public release**)
- Networking: Dev VPC and private database path exist; GKE and any authenticated HTTPS entry remain pending
- Monitoring: use existing GKE/Cloud SQL Logging and Monitoring after rollout; no alert policy claimed yet
- The Helm chart intentionally exposes only **ClusterIP**, not a publicly reachable LoadBalancer.

## Operational cautions

- This is **not** a multi-tenant helpdesk; no RBAC or tenant isolation exists yet.
- `GET /api/tickets` is capped at 200 recent matches; production-grade pagination is future scope.
- Deletes are permanent; future production changes should add soft delete/audit trail and backups.
- The rate limiter is per-process and based on the directly observed client IP; a full ingress/WAF policy is still required.
- No PostgreSQL schema auto-creation is done in production startup. Database changes will be deployed via a controlled migration step.
- Requests fail cleanly when Cloud SQL is unavailable, but the system does not yet have queue-based resilience.

## Reference GCP project

Google Cloud project ID: `helpdeskcloud-capstone-511905`

Infrastructure lives in a different repository: [HelpDeskCloud-Infra](https://github.com/mhachem110/HelpDeskCloud-Infra).
