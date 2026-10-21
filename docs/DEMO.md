# HelpDesk Cloud demo

Use the live Dev service at [helpdeskcloud.dynv6.net](https://helpdeskcloud.dynv6.net/) or a local Compose instance at http://localhost:8081.

## Suggested walkthrough

1. Explain the architecture: Google HTTPS load balancer and IAP protect the Gateway; the internal Kubernetes Service routes to two .NET replicas; Cloud SQL Auth Proxy connects privately to PostgreSQL.
2. Sign in with the approved Google account and show the ticket dashboard. Do not display real user or ticket data.
3. Create a clearly labeled sample ticket, refresh, and show that PostgreSQL persistence retained it.
4. Explain that an unauthorized Google identity is denied before ticket access. Anonymous API requests are also protected by IAP, and the app validates the signed IAP assertion again.
5. Show the split releases: helpdesk owns the app and internal Service; helpdesk-edge owns the HTTPS Gateway, route, TLS policy, IAP and health-check policies.
6. Walk through CI and CD: a feature PR runs checks; a reviewed dev commit produces a scanned immutable image; separate protected approvals publish and deploy the exact digest.
7. Explain Terraform's three roots and the manual Plan / protected Apply flow. Stage and Prod are prepared environments, not live deployments.

## Useful trainer questions

- **Why use a Cloud SQL Auth Proxy sidecar?** It provides authenticated Cloud SQL connectivity inside the Pod, uses the Pod's Workload Identity, and keeps database credentials and network access private.
- **Why is the Service ClusterIP?** Only the Gateway should receive public traffic; the app's Kubernetes Service stays internal.
- **Why keep IAP and validate JWTs in the app?** IAP authenticates at the edge. The application validates Google's signed assertion, issuer, expected backend audience and approved email before it serves protected paths.
- **Why deploy by image digest?** The digest identifies the exact image that was scanned and approved, so a mutable tag cannot change the deployed artifact.
- **Why separate Terraform roots?** Core network and data services, HTTPS foundations, and the exact IAP user grant have separate state ownership and approval scope.

See [Architecture](ARCHITECTURE.md), [Deployment](DEPLOYMENT.md) and [Code Walkthrough](CODE-WALKTHROUGH.md) for details.
