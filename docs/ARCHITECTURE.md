# Application architecture

## Live request path

    User browser
      → helpdeskcloud.dynv6.net DNS
      → Google global HTTPS Load Balancer (34.8.56.208, TLS certificate map)
      → Google Identity-Aware Proxy (approved Google account)
      → GKE Gateway and HTTPRoute, HTTPS port 443
      → helpdesk-helpdesk internal ClusterIP Service
      → two ASP.NET Core .NET 10 pods
      → Cloud SQL Auth Proxy sidecar over private IP and Workload Identity
      → Cloud SQL PostgreSQL 17

The Gateway release owns the HTTPS listener, hostname route, certificate-map reference, SSL policy, IAP backend policy and Google load-balancer health-check policy. It does not add a public Service or HTTP listener. IAP blocks anonymous traffic before it reaches the app. The .NET middleware independently verifies the signed IAP assertion, issuer, audience for the active backend and approved email. Health endpoints used by the load balancer and Kubernetes probes are intentionally exempt inside the app; the external Gateway policy still protects the public hostname.

Database passwords and the connection string are supplied from Secret Manager through the GKE Secret Manager CSI driver. The app receives a read-only mounted connection file. Its proxy sidecar listens on loopback inside the Pod and uses its Pod service account's Workload Identity. The migration Job uses a separate identity and is dispatched manually through a protected workflow.

## Application delivery

    Reviewed feature PR → Application CI
                       → merge to dev
                       → build and scan image from dev source
                       → protected dev-app-publish approval
                       → immutable Artifact Registry digest
                       → protected dev-app-deploy approval
                       → Helm app release and health checks
                       → protected HTTPS edge release and IAP smoke checks

The pipeline deploys an immutable digest that was scanned and published from the reviewed dev commit. App publication and GKE deployment use separate Workload Identity Federation identities and protected GitHub Environments. Supporting images and database migrations have separate, manually dispatched workflows and approvals.

## Infrastructure delivery

    Infrastructure PR → Terraform CI (format, validate, lint, security and guard tests)
    Manual Dev Plan → existing GCS state → strict plan and drift report
    Manual Dev Apply → fresh plan → protected Environment → safety guard → apply and read-only verification

The App repository does not own Terraform state. See the [Infrastructure architecture and code walkthrough](https://github.com/mhachem110/HelpDeskCloud-Infra/blob/dev/docs/ARCHITECTURE.md) for VPC, Cloud SQL, GKE, IAM, state and Terraform workflow details.

Stage and Prod Terraform configuration and app promotion branches exist as preparation only. No Stage or Prod deployment is represented as live.
