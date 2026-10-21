# Dev deployment and CI/CD

## Current deployment

The working Dev deployment uses project helpdeskcloud-capstone-511905, region us-east1, Autopilot cluster helpdeskcloud-dev-gke, namespace helpdesk-dev, app release helpdesk and edge release helpdesk-edge. The app Service is helpdesk-helpdesk (ClusterIP). The database is private Cloud SQL PostgreSQL instance helpdeskcloud-dev-postgres. The public host is helpdeskcloud.dynv6.net, served through reserved IP 34.8.56.208, Certificate Manager map helpdesk-dev-https-map, and SSL policy helpdesk-dev-https-tls.

The exact IAP backend name is gkegw1-q0h0-helpdesk-dev-helpdesk-helpdesk-80-3xnr96g2yybt; its numeric ID is 4800183520372038985. The application JWT audience uses the IAP backend service identity for this deployment. The single approved user grant is managed in the separate https-access Terraform root. Never place OAuth client secrets or database credentials in the repository.

## Pull request CI

.github/workflows/app-ci.yml always starts for PRs to dev, stage and prod. A small change detector selects .NET/IAP tests, Docker build and scan, and Helm/Kubernetes/policy validation based on changed paths. Repository secret scanning remains independent of those groups. The workflow does not use event-level path filters, so a required PR check is not left pending because GitHub skipped the workflow entirely.

The supporting-image CI has its own path detector. Changes to proxy or migration image inputs run architecture checks, pinned-version checks and vulnerability scans. Publication is manual, checks a typed confirmation and a protected Environment, attests the exact scanned images and pushes immutable digests using its own WIF identity.

## Reviewed Dev release

The app delivery workflow runs only for selected deployable inputs on dev, or on an explicit manual dispatch. It verifies the repository, branch, exact project and namespace, approved Environment configuration and expected WIF identity before cloud actions. It builds and scans the image, publishes the exact result under an immutable digest only after the dev-app-publish Environment, then deploys that digest only after the separate dev-app-deploy approval.

The Helm release keeps two ready replicas, an internal Service, non-root containers, resource requests and limits, probes, the Cloud SQL Auth Proxy sidecar and Secret Manager CSI mount. The pipeline waits for both replicas and the Kubernetes Gateway policies. It then probes /, /api/tickets and /health/live through verified HTTPS with retries. Anonymous requests must carry Google's IAP-generated-response marker and redirect to Google's OAuth flow with the configured client ID (or return an IAP denial). The API is not considered protected based only on an arbitrary redirect. TLS validation stays enabled.

The edge release checks that the running workload still has IAP enabled with the expected OAuth client and attached backend policy. Any configuration, controller or public traffic check that fails stops the release and writes a diagnostic summary.

## Database maintenance

dev-db-migration.yml is manual and uses its own WIF identity, namespace-scoped Role and protected dev-db-migration Environment. It does not run during regular app deployment. The first schema has already been installed on the live database; do not rerun initial SQL there. Use a reviewed, versioned migration for future schema changes.

For full setup ordering, external prerequisites and rebuild steps, see [Rebuild](REBUILD.md). For read-only operational checks, see [Operations](OPERATIONS.md).
