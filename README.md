# HelpDesk Cloud Application

HelpDesk Cloud is a ticketing application built with ASP.NET Core on .NET 10, PostgreSQL 17, Docker, Helm and GKE Autopilot. This repository owns the service, container, Kubernetes application and HTTPS Gateway releases. The companion [Infrastructure repository](https://github.com/mhachem110/HelpDeskCloud-Infra) owns Terraform and Google Cloud infrastructure.

## Deployed Dev service

The verified Dev service is available at [helpdeskcloud.dynv6.net](https://helpdeskcloud.dynv6.net/). Google HTTPS Load Balancing and Identity-Aware Proxy protect the hostname. The owner has verified approved-account login, denial for an unauthorized account, ticket creation and persistence after refresh. Anonymous requests to the ticket API are denied by IAP. The .NET service also validates IAP-signed identity assertions as a second security boundary.

The application runs as two GKE replicas behind the internal helpdesk-helpdesk ClusterIP Service. A Cloud SQL Auth Proxy sidecar reaches private PostgreSQL using Workload Identity. Google Secret Manager supplies the database connection through the GKE Secret Manager CSI integration. The public edge is an HTTPS-only Gateway with a Google-managed certificate map and an IAP-enabled backend. The public IPv4 address is 34.8.56.208. Stage and Prod are prepared in repository configuration but are not live deployments.

Known implementation evidence: [Terraform Dev Apply #45](https://github.com/mhachem110/HelpDeskCloud-Infra/actions/runs/39543113140), [App Dev delivery #17](https://github.com/mhachem110/HelpDeskCloud-App/actions/runs/39544035682), and [full HTTPS application route #20](https://github.com/mhachem110/HelpDeskCloud-App/actions/runs/39545212194). The owner separately verified the current live login and ticket persistence.

## What the application provides

- Responsive dashboard and REST API for creating, listing, searching, updating and deleting support tickets.
- PostgreSQL persistence, parameterized SQL, validation in the API and database constraints.
- Liveness and readiness health endpoints, rate limiting and browser security headers.
- A non-root container and Helm charts for the app, database proxy and separate HTTPS Gateway release.
- Application-side IAP JWT checks for signature, issuer, backend audience and approved email.
- GitHub Actions for application CI, protected immutable-image publication, protected GKE delivery, separately gated supporting images and a one-time database migration.

See [Architecture](docs/ARCHITECTURE.md), [Deployment](docs/DEPLOYMENT.md), [Rebuild](docs/REBUILD.md), [Demo](docs/DEMO.md), [Operations](docs/OPERATIONS.md) and the [code walkthrough](docs/CODE-WALKTHROUGH.md).

## Local development with Docker Compose

Requirements: Docker Desktop or Docker Engine with Compose. Compose binds only to loopback at http://localhost:8081 and maps that port to the container's port 8080.

1. Create a local environment file and set a unique local password:

    Copy-Item .env.example .env

2. Start the service and database:

    docker compose up --build -d
    docker compose ps

3. Open http://localhost:8081 and create a sample ticket. Check the API and health endpoints:

    Invoke-RestMethod http://localhost:8081/health/live
    Invoke-RestMethod http://localhost:8081/health/ready
    Invoke-RestMethod http://localhost:8081/api/tickets/stats

4. Follow logs or stop the containers:

    docker compose logs -f app
    docker compose down

Compose stores local data in the helpdesk_data volume. The command docker compose down -v deletes that local volume. Do not commit .env. The initial schema runs only when the local PostgreSQL data directory is first initialized; schema changes belong in versioned migrations.

For a direct .NET run, use the local PostgreSQL connection string and port 8081:

    $env:ConnectionStrings__Default='Host=localhost;Port=5432;Database=helpdesk;Username=helpdesk;Password=YOUR_LOCAL_PASSWORD'
    dotnet run --project src/HelpDeskCloud --urls http://localhost:8081

## Validation

Run the dependency-light .NET security and application checks:

    dotnet run --project tests/HelpDeskCloud.Tests -c Release

Run Python workflow, policy and chart checks:

    python -m unittest discover -s tests -p 'test_*.py' -v

GitHub CI also builds and scans the Docker image, lints and renders Helm configurations, validates Kubernetes schemas and scans the repository for secrets. CI runs on pull requests and pushes to dev, stage and prod. Path-aware jobs skip unrelated build groups while the workflow itself always starts so required PR checks report a result.

## Repository map

- .github/workflows/ — CI, protected Dev delivery, supporting-image release and one-time migration.
- .github/scripts/ — fail-closed validation, change-scope detection and HTTPS/IAP edge checks.
- src/HelpDeskCloud/ — HTTP API, database access, IAP security middleware and dashboard assets.
- tests/ — .NET security tests and Python workflow, Helm and policy tests.
- database/ — local initial schema and pinned PostgreSQL migration-client image.
- helm/helpdesk/ — app Deployment, internal Service, proxy sidecar and CSI-backed database connection.
- helm/https-edge-access/ — HTTPS Gateway, route, TLS policy, IAP backend policy and load-balancer health check.
- k8s/ — namespace-scoped delivery and migration RBAC bootstrap manifests.
- docs/history/ — implementation notes retained for historical context.

The live schema migration has been completed. Rebuilding from scratch uses the runbook and requires an explicit, reviewed migration action. No routine deployment resets the database.
