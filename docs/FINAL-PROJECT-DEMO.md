# HelpDesk Cloud — final demonstration and evidence record

**Current status:** this is a runbook for a future approved Dev demonstration. Phase 5 networking and Phase 6 Artifact Registry/Cloud SQL were deployed. Phase 7 GKE and the application have not been verified live. Phase 8 delivery is prepared but disabled. Never present the checks below as passed until their actual output and run URLs are recorded.

## Architecture to explain

```text
Developer → feature PR → GitHub credential-free CI → reviewed dev commit
       → scan/build → publish approval → Artifact Registry (immutable digest)
       → deployment approval → Helm → GKE Autopilot / helpdesk-dev
                                      ├─ HelpDesk Pod 1 + Cloud SQL Auth Proxy
                                      └─ HelpDesk Pod 2 + Cloud SQL Auth Proxy
                                              ↓ private VPC / PSA
                                        Cloud SQL PostgreSQL

Terraform → protected Dev Plan/Apply → VPC, PSA, Artifact Registry, Cloud SQL, GKE,
                                       workload identities and Secret Manager metadata
GKE Workload Identity → app KSA → Cloud SQL Client and its own Secret Manager record
Owner kubectl port-forward (localhost only) → internal ClusterIP Service
```

Terraform records infrastructure in the existing Dev GCS backend. Its approved Apply has its own GitHub Environment and OIDC identity. Application CI/CD uses separate identities and never runs Terraform. Helm packages the Kubernetes Deployment and Service; the Deployment creates a ReplicaSet that keeps two Pods running. Autopilot manages node capacity, while PostgreSQL data lives in managed Cloud SQL rather than in a Pod. Each Pod's Auth Proxy authorizes and encrypts the upstream connection to the private database. Workload Identity and managed CSI remove long-lived keys from source and Pods. The app has no end-user login, so it must remain internal.

Two replicas keep one app Pod available during a rolling update or a single Pod restart. Each replica has its own proxy sidecar, so both container requests contribute to Autopilot cost. Fixed replicas are deliberate for the initial release; a bounded HPA can be tested later after baseline metrics. Cloud SQL and Artifact Registry incur their own charges; inspect the current [GKE](https://cloud.google.com/kubernetes-engine/pricing), [Cloud SQL](https://cloud.google.com/sql/pricing), [Artifact Registry](https://cloud.google.com/artifact-registry/pricing) and [network](https://cloud.google.com/vpc/network-pricing) pricing before owner approval. Credits do not make usage free.

## Pre-demo gate

Record: Infra PR #13 merge approval and strict Plan result; protected Terraform Apply run; GKE cluster version and verification result; approved IAM/API grants; namespace/bootstrap checks; database user/schema and secret-version metadata; approved app/proxy image digests; Phase 8 PR merge and protected delivery run. Stop if any item is missing. Never print passwords, Secret Manager payloads, kubeconfig or Terraform state.

## Demonstration sequence

1. **Source and CI:** show the two GitHub repositories and `feature/* → dev → stage → prod` PR flow. Show green infra/app PR checks and the reviewed application commit. Explain that Stage/Prod cloud deployments are absent.
2. **Terraform:** show the Dev backend bucket/prefix and only the expected managed resource addresses using `terraform state list` from an authorized Dev session. Do not show raw state. Show the strict drift guard and latest protected Plan result; do not run Apply for the demo.
3. **GCP foundation:** use read-only `gcloud compute networks describe helpdeskcloud-dev-vpc`, `gcloud compute networks subnets describe helpdeskcloud-dev-subnet --region us-east1`, `gcloud artifacts repositories describe helpdeskcloud-dev-images --location us-east1`, and sanitized `gcloud sql instances describe helpdeskcloud-dev-postgres`. Confirm custom subnet, named secondary ranges, private Cloud SQL IP, no public IPv4 and deletion protection.
4. **GKE:** `gcloud container clusters describe helpdeskcloud-dev-gke --region us-east1` and `gcloud container clusters get-credentials helpdeskcloud-dev-gke --region us-east1 --dns-endpoint`. Show Autopilot, actual version, private-node/network settings and Workload Identity. With approved access, run `kubectl get nodes`, `kubectl get deployment,pods,service -n helpdesk-dev`, and `kubectl get serviceaccount,secretproviderclass -n helpdesk-dev`. Do not print secret payloads.
5. **Two replicas:** `kubectl rollout status deployment/helpdesk-helpdesk -n helpdesk-dev`; `kubectl get deployment helpdesk-helpdesk -n helpdesk-dev -o jsonpath='{.status.readyReplicas}'` must return `2`. Show two Pods, each with `helpdesk` and `cloud-sql-proxy` containers. Show the Service type `ClusterIP` and absence of public Ingress/LoadBalancer.
6. **Images and identities:** show the approved application image digest in Artifact Registry and compare it with `kubectl get deployment helpdesk-helpdesk -n helpdesk-dev -o jsonpath='{.spec.template.spec.containers[0].image}'`. Show app KSA annotation, Secret Manager **metadata** and the separate publisher/deployer WIF approvals. Explain that CI has no GCP token and the runtime app never uses the Terraform service account.
7. **Private connection and health:** from an authorized workstation run `kubectl port-forward --address 127.0.0.1 -n helpdesk-dev service/helpdesk-helpdesk 8080:80`. In a second terminal call `curl -fsS http://127.0.0.1:8080/health/live` and `/health/ready`. Liveness proves the process runs; readiness checks database access and `tickets` schema. Check sanitized proxy and application logs if readiness fails.
8. **Synthetic ticket CRUD:** using the localhost UI or API, create a clearly synthetic ticket, read/list it, update its status or priority, read it again, then delete it and confirm the expected result. Record only synthetic IDs and responses. The owner should verify persistence in the real `helpdesk` database without exposing credentials.
9. **Release demonstration:** make a harmless, reviewed code change on a new feature branch; show PR CI, owner-approved merge to `dev`, one image build/scan, protected publication and deployment approvals, matching SHA/digest, two Ready replicas and health checks. Do this only after the delivery identities, environments and costs have been approved. A failed rollout is not success.
10. **Operations:** show `kubectl top pods -n helpdesk-dev`, Pod restarts, events, Deployment availability, app/proxy logs and Cloud SQL CPU/connections/backup status in Cloud Monitoring. Discuss alert thresholds for unavailable replicas, repeated restarts, sustained utilization and SQL availability; do not claim an alert exists unless configured and tested. Explain Helm history and rollback to a reviewed digest, with separate approval. Never roll back Terraform state or database schema as part of Helm rollback.

## Troubleshooting quick reference

| Symptom | Read-only first check | Safe response |
| --- | --- | --- |
| Terraform drift or guard failure | Trusted Plan's safe diagnostic and exact resource address/path | Investigate live metadata; permit only proven normalization in a reviewed PR. |
| IAM/API or GKE quota failure | Enabled services, quota page, sanitized job error | Document exact permission/API/quota; request approval before changes. |
| Partial GKE creation | Terraform state list and read-only cluster describe | Stop; do not blindly rerun Apply or replace resources. |
| `ImagePullBackOff` | Pod events, exact digest, node SA repository Reader | Correct reviewed image/IAM; do not add public nodes or NAT automatically. |
| CSI mount / Workload Identity failure | Pod events, KSA annotation, secret version metadata and scoped IAM | Fix exact identity/resource scope; never log payloads. |
| Cloud SQL/proxy failure | Proxy logs, instance private IP, Client role, PSA and private path | Keep public IPv4 disabled; verify private route and credentials separately. |
| Database permission error | App logs and restricted role/table grants | Review migration result; do not elevate the app user to superuser. |
| Helm failure or unready Pod | `helm status`, `kubectl describe`, readiness/proxy logs | Fix the root cause; retain prior release for approved rollback. |
| CI/CD OIDC failure | Environment policy, exact repo/ref, provider condition, service account binding | Keep delivery disabled; never use a JSON key or Terraform identity. |

## Backup and recovery boundary

Inspect Cloud SQL automated backup configuration and the latest successful backup before the demo. Restoring Cloud SQL is a separate, potentially destructive operation requiring a disposable target and owner approval. Restarting a Kubernetes Pod does not erase Cloud SQL data. Helm rollback changes the app image/manifests, not SQL data or migrations. A restore test has not been performed until a separate test run proves it.
