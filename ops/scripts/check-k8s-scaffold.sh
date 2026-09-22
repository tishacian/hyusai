#!/usr/bin/env bash
# Prove the Kubernetes scaffold renders. This is not a cluster or a release.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

fail() { printf '%s\n' "$*" >&2; exit 1; }

command -v helm >/dev/null || fail "helm is required"
command -v terraform >/dev/null || fail "terraform is required"
command -v ansible-playbook >/dev/null || fail "ansible-playbook is required"

assert_no_local_images() {
  local file="$1"
  if grep -E '^[[:space:]]+(frontend|backend|worker):[[:space:]].*:(local|latest)[[:space:]]*$' "$file"; then
    fail "$file must not pin :local or :latest"
  fi
}

assert_no_passwords() {
  local file="$1"
  if grep -Ei 'password|change-me|secret_key' "$file"; then
    fail "$file must not contain secret material"
  fi
}

helm lint "$ROOT/ops/helm/agentium"

helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
  > /tmp/agentium-helm.yaml
grep -q 'name: agentium-backend' /tmp/agentium-helm.yaml || fail "backend missing from helm template"
grep -q 'name: agentium-frontend' /tmp/agentium-helm.yaml || fail "frontend missing from helm template"
grep -q 'name: agentium-worker' /tmp/agentium-helm.yaml || fail "worker missing from helm template"
grep -q 'kind: Ingress' /tmp/agentium-helm.yaml || fail "ingress missing from helm template"
grep -q 'path: /health/live' /tmp/agentium-helm.yaml || fail "ingress /health/live missing"
grep -q 'wait-postgres' /tmp/agentium-helm.yaml || fail "migrate must wait for Postgres"
grep -q 'post-install' /tmp/agentium-helm.yaml || fail "migrate hook must be post-install, not pre-upgrade"
grep -q 'server-snippet' /tmp/agentium-helm.yaml || fail "hidden-path ingress snippet missing"

# One rendered "image:" line per container, one "cpu:" line per container's
# request block. A container added without requests breaks the equality, so
# the QoS hole cannot come back unnoticed.
tpl_containers="$(grep -cE '^ +image: ' /tmp/agentium-helm.yaml || true)"
tpl_sized="$(grep -cE '^ +cpu: ' /tmp/agentium-helm.yaml || true)"
[ "$tpl_containers" -gt 0 ] || fail "helm template rendered no container"
[ "$tpl_containers" = "$tpl_sized" ] \
  || fail "every container must declare cpu and memory requests ($tpl_sized/$tpl_containers)"
# Single-replica stateful services must refuse a voluntary eviction.
tpl_pdbs="$(grep -c 'kind: PodDisruptionBudget' /tmp/agentium-helm.yaml || true)"
[ "$tpl_pdbs" = "4" ] \
  || fail "postgres, qdrant, minio and rabbitmq each need a PodDisruptionBudget (got $tpl_pdbs)"
for svc in postgres qdrant minio rabbitmq; do
  helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
    --show-only "templates/$svc.yaml" | grep -q 'livenessProbe:' \
    || fail "$svc must declare a liveness probe"
done
if grep -qE '^resources: \{\}' "$ROOT/ops/helm/agentium/values.yaml"; then
  fail "values.yaml must not ship a resources key no template consumes"
fi
if grep -q 'name: agentium-ollama' /tmp/agentium-helm.yaml; then
  fail "default chart must not start Ollama"
fi
if grep -q 'DEFAULT_PROVIDER: ollama' /tmp/agentium-helm.yaml; then
  fail "default chart must keep the cloud routing default"
fi

helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
  --set ollama.enabled=true \
  > /tmp/agentium-helm-ollama.yaml
grep -q 'name: agentium-ollama' /tmp/agentium-helm-ollama.yaml || fail "ollama service missing when enabled"
grep -q 'nomic-embed-text' /tmp/agentium-helm-ollama.yaml || fail "ollama embed model missing"
grep -q 'DEFAULT_PROVIDER: ollama' /tmp/agentium-helm-ollama.yaml || fail "local chart must default chat to ollama"
grep -q 'EMBEDDING_PROVIDER: ollama' /tmp/agentium-helm-ollama.yaml || fail "local chart must default embeddings to ollama"

helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
  --set vllm.enabled=true \
  > /tmp/agentium-helm-vllm.yaml
grep -q 'name: agentium-vllm' /tmp/agentium-helm-vllm.yaml || fail "vllm service missing when enabled"
grep -q 'nvidia.com/gpu' /tmp/agentium-helm-vllm.yaml || fail "vllm must request a GPU"
if grep -q 'DEFAULT_PROVIDER: vllm' /tmp/agentium-helm-vllm.yaml; then
  fail "enabling vllm must not replace the routing default"
fi

helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
  -f "$ROOT/ops/helm/agentium/values-lab-ovh.yaml" \
  > /tmp/agentium-helm-lab-ovh.yaml
grep -q 'name: agentium-lab' /tmp/agentium-helm-lab-ovh.yaml || fail "lab-ovh must use existingSecret agentium-lab"
if grep -q '^kind: Secret$' /tmp/agentium-helm-lab-ovh.yaml; then
  fail "lab-ovh must not create a Secret"
fi
grep -q 'storageClassName: "csi-cinder-high-speed"' /tmp/agentium-helm-lab-ovh.yaml \
  || fail "lab-ovh must set OVH CSI storage class"
grep -q 'ingressClassName: "nginx"' /tmp/agentium-helm-lab-ovh.yaml || fail "lab-ovh ingress class"
assert_no_local_images "$ROOT/ops/helm/agentium/values-lab-ovh.yaml"
assert_no_passwords "$ROOT/ops/helm/agentium/values-lab-ovh.yaml"

helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
  -f "$ROOT/ops/helm/agentium/values-lab-aks.yaml" \
  > /tmp/agentium-helm-lab-aks.yaml
grep -q 'name: agentium-lab' /tmp/agentium-helm-lab-aks.yaml || fail "lab-aks must use existingSecret"
if grep -q '^kind: Secret$' /tmp/agentium-helm-lab-aks.yaml; then
  fail "lab-aks must not create a Secret"
fi
grep -q 'storageClassName: "managed-csi"' /tmp/agentium-helm-lab-aks.yaml \
  || fail "lab-aks must set Azure CSI storage class"
assert_no_local_images "$ROOT/ops/helm/agentium/values-lab-aks.yaml"
assert_no_passwords "$ROOT/ops/helm/agentium/values-lab-aks.yaml"

terraform fmt -check -recursive "$ROOT/ops/terraform" "$ROOT/ops/instance"

validate_tf() {
  local dir="$1"
  terraform -chdir="$dir" init -backend=false -input=false >/tmp/tf-init.log
  terraform -chdir="$dir" validate
}

validate_tf "$ROOT/ops/terraform/modules/cluster-ovh-mks"
validate_tf "$ROOT/ops/terraform/modules/cluster-aks"
validate_tf "$ROOT/ops/terraform/envs/lab-ovh"
validate_tf "$ROOT/ops/terraform/envs/lab-aks"
# The OpenStack fallback is fmt-checked above; validate it too, and
# require the backend so no Terraform in this repo keeps local state.
validate_tf "$ROOT/ops/instance"
grep -q 'backend "http" {}' "$ROOT/ops/instance/versions.tf" \
  || fail "ops/instance must keep remote, lockable state"
validate_tf "$ROOT/ops/instance"

DIGEST_A="$(printf 'a%.0s' {1..64})"
DIGEST_B="$(printf 'b%.0s' {1..64})"
DIGEST_C="$(printf 'c%.0s' {1..64})"
cat > /tmp/values-ci-images.yaml <<EOF
image:
  pullPolicy: IfNotPresent
  frontend: registry.example/agentium-frontend@sha256:${DIGEST_A}
  backend: registry.example/agentium-backend@sha256:${DIGEST_B}
  worker: registry.example/agentium-worker@sha256:${DIGEST_C}
EOF
helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
  -f "$ROOT/ops/helm/agentium/values-lab-ovh.yaml" \
  -f /tmp/values-ci-images.yaml \
  > /tmp/agentium-helm-ci.yaml
grep -q "agentium-frontend@sha256:${DIGEST_A}" /tmp/agentium-helm-ci.yaml \
  || fail "CI digest overlay must win over :local"
if grep -q 'agentium-frontend:local' /tmp/agentium-helm-ci.yaml; then
  fail "CI overlay left a :local frontend image"
fi
grep -q 'name: agentium-lab' /tmp/agentium-helm-ci.yaml || fail "CI render must keep existingSecret"

# Every job that reaches the lab must stay behind the one switch. Without
# this, landing the track on demo/agentic would deploy on the next push.
CI_K8S="$ROOT/.gitlab/ci/agentium-k8s.yml"
gated="$(grep -c 'AGENTIUM_LAB_ENABLED == "true"' "$CI_K8S" || true)"
reaching="$(grep -cE "^ +- if: '.*(OVH_APPLICATION_KEY|AGENTIUM_LAB_REGISTRY|AGENTIUM_LAB_INGRESS_URL)" "$CI_K8S" || true)"
[ "$gated" -ge 6 ] || fail "lab jobs must stay behind AGENTIUM_LAB_ENABLED"
[ "$gated" -eq "$reaching" ] \
  || fail "a lab-reaching rule is missing the AGENTIUM_LAB_ENABLED gate"
grep -q 'rules: \*ops-k8s-rules-ops-tree' "$CI_K8S" \
  || fail "validate must stay on without the switch"

export ANSIBLE_CONFIG="$ROOT/ops/ansible/ansible.cfg"
ansible-playbook --syntax-check "$ROOT/ops/ansible/playbooks/provision-cluster.yml"
ansible-playbook --syntax-check -i "$ROOT/ops/ansible/inventories/ci" \
  "$ROOT/ops/ansible/playbooks/deploy-agentium.yml"

printf 'ops scaffold ok\n'
