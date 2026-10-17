# HelpDesk Cloud — Fast capstone application demonstration

1. Start locally with `docker compose up --build -d`.
2. Open `http://localhost:8080` and create a ticket (e.g. “VPN Connection Issue”).
3. Show the new dashboard count and the ticket in PostgreSQL-backed list.
4. Edit priority to Critical and status to In Progress; show changes persist after refreshing.
5. `docker compose restart app` — verify that tickets still exist (data is in PostgreSQL, not the container).
6. Show `http://localhost:8080/health/live` and `/health/ready`.
7. Open a `feature/*` PR into `dev` and show CI build/test/container lint actions.
8. Explain that GKE deployment, immutable image promotion, OIDC, Cloud SQL, and production authentication are future infra/CD phases, **not yet enabled**.
