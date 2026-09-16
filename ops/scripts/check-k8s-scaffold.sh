#!/usr/bin/env bash
# Prove the Kubernetes scaffold renders. This is not a cluster or a release.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

fail() { printf '%s\n' "$*" >&2; exit 1; }

command -v helm >/dev/null || fail "helm is required"
command -v terraform >/dev/null || fail "terraform is required"
command -v ansible-playbook >/dev/null || fail "ansible-playbook is required"

helm lint ops/helm/agentium
helm template agentium ops/helm/agentium --namespace agentium > /tmp/agentium-helm.yaml
grep -q 'name: agentium-backend' /tmp/agentium-helm.yaml || fail "backend missing from helm template"
grep -q 'name: agentium-frontend' /tmp/agentium-helm.yaml || fail "frontend missing from helm template"
grep -q 'name: agentium-worker' /tmp/agentium-helm.yaml || fail "worker missing from helm template"
grep -q 'kind: Ingress' /tmp/agentium-helm.yaml || fail "ingress missing from helm template"

terraform -chdir=ops/instance init -backend=false -input=false >/tmp/tf-init.log
terraform -chdir=ops/instance validate

export ANSIBLE_CONFIG="$ROOT/ops/ansible/ansible.cfg"
ansible-playbook --syntax-check "$ROOT/ops/ansible/playbooks/provision-cluster.yml"
ansible-playbook --syntax-check "$ROOT/ops/ansible/playbooks/deploy-agentium.yml"

printf 'ops scaffold ok\n'
