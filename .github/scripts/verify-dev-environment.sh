#!/usr/bin/env bash
set -euo pipefail

# GitHub can create an unprotected Environment from a misspelled name. Check
# the exact repository, branch, required reviewers, and sole allowed branch
# before any job requests a Google Cloud OIDC token.
if [[ "${GITHUB_REPOSITORY:-}" != 'mhachem110/HelpDeskCloud-App' || "${GITHUB_REF:-}" != 'refs/heads/dev' ]]; then
  echo '::error::Protected Dev actions are limited to the trusted Dev branch.'
  exit 1
fi
if [[ "${GITHUB_EVENT_NAME:-}" != 'push' && "${GITHUB_EVENT_NAME:-}" != 'workflow_dispatch' ]]; then
  echo '::error::Protected Dev actions cannot run from a pull request.'
  exit 1
fi
if [[ -z "${GH_TOKEN:-}" ]]; then
  echo '::error::Missing GitHub token.'
  exit 1
fi
case "${EXPECTED_ENVIRONMENT:-}" in
  dev-app-publish|dev-app-deploy|dev-supporting-images-publish|dev-db-migration) ;;
  *) echo '::error::Unexpected deployment Environment.'; exit 1 ;;
esac

environment_file="${RUNNER_TEMP}/dev-app-environment.json"
branches_file="${RUNNER_TEMP}/dev-app-branches.json"
url="https://api.github.com/repos/mhachem110/HelpDeskCloud-App/environments/${EXPECTED_ENVIRONMENT}"
curl -fsSL --retry 3 -H 'Accept: application/vnd.github+json' -H "Authorization: Bearer ${GH_TOKEN}" "$url" > "$environment_file" || {
  echo '::error::Cannot read the GitHub Environment configuration; check actions: read permission.'
  exit 1
}
curl -fsSL --retry 3 -H 'Accept: application/vnd.github+json' -H "Authorization: Bearer ${GH_TOKEN}" "$url/deployment-branch-policies?per_page=100" > "$branches_file" || {
  echo '::error::Cannot read the Environment deployment branch policy.'
  exit 1
}
jq -e --arg name "$EXPECTED_ENVIRONMENT" \
  '.name == $name and .deployment_branch_policy.custom_branch_policies == true and ([.protection_rules[]? | select(.type == "required_reviewers" and (.reviewers | length) > 0)] | length) > 0' \
  "$environment_file" >/dev/null || {
  echo '::error::The Dev Environment must require a reviewer and custom branch policy.'
  exit 1
}
jq -e '.total_count == 1 and (.branch_policies | length) == 1 and .branch_policies[0].name == "dev"' \
  "$branches_file" >/dev/null || {
  echo '::error::The Dev Environment must allow exactly the dev branch.'
  exit 1
}
echo "Protected ${EXPECTED_ENVIRONMENT} Environment verified."
