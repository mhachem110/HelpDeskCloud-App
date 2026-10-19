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
- GitHub Actions CI for .NET, Docker, Helm and digest-pinned supporting images
- Manually dispatched, separately Environment-approved workflows prepared for supporting-image publication and the one-time Dev database migration
- Existing Dev application delivery workflow remains disabled until its WIF, Environment, RBAC and repository-variable prerequisites are reviewed
- No hardcoded cloud credentials or Terraform state in this repository

## Dev GKE and Phase 8

The owner reports Terraform, the Dev GKE cluster, namespace bootstrap, restricted application login and Secret Manager versions are deployed. The supporting images remain unpublished, the one-time schema migration has not run, and application delivery remains disabled. The chart prepares two internal `ClusterIP` replicas, digest-pinned application and Cloud SQL Auth Proxy containers, and a separate migration Job. See the [Dev deployment guide](docs/GKE-DEPLOYMENT.md) and [Phase 8 activation checklist](docs/PHASE8.md). This App PR does not query or mutate cloud resources, read secret payloads, run a migration, publish images or expose the app publicly.

## Quickest start — Docker Desktop

Requirements: [Docker Desktop](https://docs.docker.com/desktop/) with Linux containers. .NET does not need to be installed if using Docker.

1. Clone `mhachem110/HelpDeskCloud-App` and create a feature branch from `dev` for changes. For local use, switch to `dev` or a reviewed feature branch.
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
├── .github/workflows/app-ci.yml                # credential-free application CI
├── .github/workflows/supporting-images-ci.yml  # image scan, provenance and gated publish
├── .github/workflows/dev-db-migration.yml      # separate approved one-time schema migration
├── .github/workflows/app-dev-delivery.yml      # existing protected Dev application delivery
├── .github/scripts/verify-dev-environment.sh  # fail-closed Environment policy check
├── src/HelpDeskCloud/
│   ├── Program.cs                       # minimal API routes and middleware
│   ├── Data/                            # PostgreSQL repository and readiness probe
│   ├── Models/                          # ticket request/response models
│   ├── Validation/                      # ticket input validation
│   ├── wwwroot/                         # accessible HTML/CSS/JS dashboard
│   └── HelpDeskCloud.csproj
├── tests/HelpDeskCloud.Tests/           # dependency-light test executable
├── database/init.sql                         # initial PostgreSQL schema for local DB
├── database/migration-client/Dockerfile     # pinned PostgreSQL 17.11 migration client
├── helm/helpdesk/                       # base chart, Dev values, delivery overlay and one-time migration SQL
├── docs/GKE-DEPLOYMENT.md              # approved first-deployment checkpoints
├── docs/PHASE8.md                      # identity and delivery activation plan
├── docs/FINAL-PROJECT-DEMO.md          # evidence-driven capstone walkthrough
├── k8s/dev-delivery-rbac.yaml                # namespace-scoped application delivery access
├── k8s/dev-migration-runner-rbac.yaml        # separate namespace-scoped migration access
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

`dev`, `stage`, and `prod` are protected. Pull requests run credential-free Application CI and, for `dev`, supporting-image build, architecture, command and Trivy checks. Trusted pushes to `dev` also create and verify GitHub SLSA provenance for the exact supporting-image archives. These jobs do not authenticate to Google Cloud or publish images.

Supporting-image publication is manual-only, disabled until `DEV_SUPPORTING_IMAGES_PUBLISH_ENABLED=true`, and waits for the separately protected `dev-supporting-images-publish` Environment. It uses a dedicated WIF provider and repository-scoped Artifact Registry Writer grant. The one-time database migration has its own manual workflow, typed confirmation, `DEV_DB_MIGRATION_ENABLED` gate, WIF identity, namespace RBAC and `dev-db-migration` approval. The existing `app-dev-delivery.yml` keeps its separate `dev-app-publish` and `dev-app-deploy` gates; `DEV_APP_CD_ENABLED` stays unset until prerequisites and the migration are reviewed. See [Phase 8](docs/PHASE8.md) and [GKE deployment](docs/GKE-DEPLOYMENT.md) for the exact IAM, Environment, RBAC and repository-variable checklist.

Stage and Production cloud resources, image repositories, identities and delivery workflows are out of scope. The Helm chart exposes only **ClusterIP**; do not add public ingress without approved authentication and HTTPS.

## GKE deployment chart (prepared; rollout gated)

The Dev chart uses digest-pinned app, proxy and migration-client images. Bootstrap resources and secrets stay outside the regular app release. The one-time migration runs only through its separately approved workflow; application upgrades keep migration disabled and the Service internal. Do not deploy with missing digests or bootstrap prerequisites. Public access remains out of scope until authentication and HTTPS are approved.

## GCP security decisions

- Cloud CI/CD uses separate GitHub OIDC Workload Identity Federation providers and service accounts, not service-account keys
- Supporting-image publication, the one-time migration and app deployment use distinct Environment approvals
- Runtime identity: GKE Workload Identity Federation with scoped Cloud SQL and secret access
- Secrets: Google Secret Manager and restricted CSI delivery to pods
- Database: private Cloud SQL for PostgreSQL
- Authorization: identity-aware ingress / login and least-privilege authorization (**required before public release**)
- Monitoring: use existing GKE/Cloud SQL Logging and Monitoring after rollout; no alert policy is claimed yet
- The Helm chart exposes only **ClusterIP**, not a publicly reachable LoadBalancer

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
