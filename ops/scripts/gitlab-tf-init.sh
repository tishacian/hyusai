#!/usr/bin/env bash
# Init a Terraform env against the GitLab HTTP backend. Not used for
# validate (that is -backend=false).
set -euo pipefail

ENV_DIR="${1:?usage: gitlab-tf-init.sh <env-dir> <state-name>}"
STATE_NAME="${2:?usage: gitlab-tf-init.sh <env-dir> <state-name>}"

: "${CI_API_V4_URL:?CI_API_V4_URL is required}"
: "${CI_PROJECT_ID:?CI_PROJECT_ID is required}"
: "${CI_JOB_TOKEN:?CI_JOB_TOKEN is required}"

ADDRESS="${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/terraform/state/${STATE_NAME}"

terraform -chdir="$ENV_DIR" init -input=false \
  -backend-config="address=${ADDRESS}" \
  -backend-config="lock_address=${ADDRESS}/lock" \
  -backend-config="unlock_address=${ADDRESS}/lock" \
  -backend-config="username=gitlab-ci-token" \
  -backend-config="password=${CI_JOB_TOKEN}" \
  -backend-config="lock_method=POST" \
  -backend-config="unlock_method=DELETE" \
  -backend-config="retry_wait_min=5"
