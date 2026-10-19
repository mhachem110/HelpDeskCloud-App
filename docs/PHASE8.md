# Phase 8 — prepared Dev application delivery

**Status:** code only. The GKE cluster, database bootstrap, supporting image digests, dedicated GitHub OIDC providers/service accounts, Kubernetes RoleBinding and protected GitHub Environments have not been verified. `DEV_APP_CD_ENABLED` defaults to unset, so the delivery jobs skip. The owner must approve each live setup or deployment checkpoint.

## Flow

```text
Feature PR → credential-free Application CI → reviewed merge to dev
    → test/build/Trivy scan once → one-day image artifact
    → dev-app-publish approval → dedicated publisher OIDC → Artifact Registry digest
    → dev-app-deploy approval → dedicated deployer OIDC → DNS GKE endpoint
    → Helm release (two Pods, two proxy sidecars) → readiness and localhost smoke tests
```

`app-ci.yml` validates PRs to `dev`, `stage` and `prod` without cloud credentials. It builds .NET, runs tests, builds/scans Docker, scans the repository for secrets, lints/renders Helm and validates Kubernetes schemas and chart policy. The new `app-dev-delivery.yml` runs only on `dev` push or manual dispatch. Its packaging job is gated by the repository variable `DEV_APP_CD_ENABLED=true`. Keep that variable absent until all prerequisites and costs are approved.

The packaging job uploads only the scanned container image tar for one day. The publisher loads that exact image, tags it with the commit and workflow run, pushes it to the existing regional Artifact Registry, then reads its immutable digest. The deployer consumes that digest; it does not rebuild. Neither raw credentials nor kubeconfig are uploaded. The workflow never runs a schema migration, Terraform, or a Stage/Prod deployment.

## Identity and approval setup — owner review required

These are **proposed** names, not claims that the identities exist. Before creating them, inspect current IAM/WIF inventory, confirm the application repository's immutable GitHub owner/repository IDs, and approve the exact grants. Do not reuse `helpdesk-terraform-dev` or its infra-only OIDC provider.

| Identity | Proposed trust | Required access |
| --- | --- | --- |
| `helpdesk-app-publisher-dev@helpdeskcloud-capstone-511905.iam.gserviceaccount.com` | New `github-app-publish-dev` provider in the existing `helpdesk-github` pool, restricted to the exact App repository, immutable IDs, `refs/heads/dev`, and `dev-app-publish` Environment | `roles/artifactregistry.writer` on **only** repository `helpdeskcloud-dev-images` in `us-east1` |
| `helpdesk-app-deployer-dev@helpdeskcloud-capstone-511905.iam.gserviceaccount.com` | Separate `github-app-deploy-dev` provider with the same repository/branch checks and only `dev-app-deploy` Environment | GKE Cluster Viewer (`roles/container.clusterViewer`) on the project for cluster lookup, plus the reviewed `helpdesk-dev` namespace RoleBinding in `k8s/dev-delivery-rbac.yaml` |

Each provider should map `google.subject=assertion.sub` and the needed immutable repository, owner, ref and environment attributes. Its condition must compare the verified immutable repository and owner IDs, `assertion.ref`, the exact `assertion.environment`, and, where available, the delivery workflow reference. Bind each service account's `roles/iam.workloadIdentityUser` only to its corresponding verified provider principal. The owner must inspect GitHub's actual OIDC subject because this repository may use immutable-subject customization. Do not copy the Infra repository's subject. The workflow's fixed provider and service-account names intentionally fail until this separate setup is approved and complete. [GitHub documents Environment OIDC subjects](https://docs.github.com/en/actions/reference/security/oidc); [Google documents WIF conditions](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines).

Create GitHub Environments `dev-app-publish` and `dev-app-deploy` only after approval. Each must have a required reviewer and **exactly one** deployment branch policy, `dev`. The workflow checks both through authenticated GitHub REST calls **before** OIDC. A missing or misconfigured Environment fails closed. The publication and deployment jobs have distinct approval gates. The App repository must also keep `dev` protected and require green PR CI. Set the non-secret repository variable `DEV_PROXY_IMAGE_DIGEST` to the verified digest of the mirrored Cloud SQL Auth Proxy image. [GitHub Environment protections](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments) explain the reviewer gate.

The proposed Role only allows release workload changes within `helpdesk-dev`, read-only access to the app ServiceAccount and SecretProviderClass, and Helm's Kubernetes Secret release storage. It does **not** grant direct Secret Manager, IAM, Cloud SQL or migration Job administration. The Kubernetes Secret rule is still namespace-wide because Helm release names are dynamic; review that limitation before approval. A principal able to edit Deployments can potentially select another existing ServiceAccount, so protected source review and deployment approval remain essential. Do not treat namespace RBAC as complete privilege separation. [GKE RBAC guidance](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/role-based-access-control) documents IAM service accounts as Kubernetes `User` subjects.

## Bootstrap and release boundary

After a separately approved GKE Apply and database/secret bootstrap, the owner runs the first part of `GKE-DEPLOYMENT.md`: create the namespace, then render and apply the two Kubernetes ServiceAccounts, SecretProviderClasses and migration SQL ConfigMap. This bootstrap is deliberately **not** a Helm release. The application delivery job layers `values-dev-delivery.yaml` on top of `values-dev.yaml`; it disables bootstrap and migration, fixes two replicas and the internal Service, and requires immutable images. Its Helm release contains only the Deployment and ClusterIP Service. The chart test asserts this boundary. The one-time migration remains an explicit owner-run Job.

Before the first delivery run, mirror and verify the approved proxy image in the existing Artifact Registry and set its digest variable. The application image and proxy are both digest-pinned. A blank or malformed digest blocks rendering. The deployer checks the exact GKE project, region and cluster, pre-existing app identity and SecretProviderClass, a server-side manifest dry run, two Ready replicas, the internal Service and `/health/live` plus `/health/ready` through localhost-only port-forward. Readiness depends on the private database and initialized schema; a failed check fails the job. The workflow does not mark the release successful if readiness fails.

## Activation and evidence

1. Resolve Infra PR #13's still unknown drift, obtain owner merge approval, rerun the trusted Dev Plan and strict guard, then separately approve the protected GKE Apply. Verify all 21 intended Terraform resources and no unexpected drift.
2. Approve and complete namespace/bootstrap, restricted database user, secret versions, migration, supporting image mirror and Cloud SQL connectivity according to `GKE-DEPLOYMENT.md`. None of these are performed by this PR.
3. Review and approve the proposed WIF, two service accounts, repository-scoped Writer IAM, GKE lookup permission, namespace RoleBinding and both GitHub Environments. Confirm the exact repository OIDC claims and GitHub Environment settings before enabling the workflow.
4. Set `DEV_PROXY_IMAGE_DIGEST` to the actual approved mirror digest. Set `DEV_APP_CD_ENABLED=true` only after all prerequisites, reviewer restrictions and billing impact are accepted. Dispatch `Application Dev delivery` on `dev` for the first supervised run. Review both Environment approvals at the point of execution. Future approved merges to `dev` trigger the same two-gate flow.
5. Record the run URL, commit SHA, Artifact Registry digest, Helm revision, two Pod readiness checks and sanitized smoke output. Do a synthetic ticket CRUD test from an authenticated operator workstation after deployment; this workflow intentionally avoids modifying database data.

## Rollback and promotion

For an app-only fault, inspect `helm history helpdesk -n helpdesk-dev` and the prior digest. With a fresh owner-approved deployment review, run `helm rollback helpdesk REVISION -n helpdesk-dev --wait`, then verify two Ready Pods and both health endpoints. Helm rollback does not undo database schema changes or Terraform. Do not run a migration during normal application rollout. An automated rollback workflow is intentionally deferred until deployment access and the first rollout are proven.

The `dev → stage → prod` source promotion path remains. Stage and Prod GKE clusters, registries, secrets and delivery identities have **not** been created; the Dev OIDC identities and image may not be reused as those environments. A later approved design can promote the same reviewed digest with separate trust and approvals.

## Local validation

```sh
dotnet build src/HelpDeskCloud/HelpDeskCloud.csproj -c Release
dotnet run --project tests/HelpDeskCloud.Tests/HelpDeskCloud.Tests.csproj -c Release
docker build --platform linux/amd64 -t helpdeskcloud:ci .
helm lint helm/helpdesk -f helm/helpdesk/values-dev.yaml \
  --set-string image.digest=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --set-string cloudSqlProxy.image.digest=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
python -m unittest discover -s tests -p 'test_*.py' -v
```

These checks cannot prove WIF, registry push, GKE RBAC, Pod readiness or Cloud SQL connectivity. The hosted Application CI validates the PR without GCP credentials. The delivery workflow remains disabled until the owner-approved live setup is complete.
