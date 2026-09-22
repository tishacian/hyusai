# Agentium Kubernetes track

Status: IaC + CI on `cursor/agentium-kubernetes-3892`. The demo VM remains
Docker Compose. This document is the map from that Compose stack to the
managed-cluster path (OVH MKS first, AKS twin).

## Why this shape

Terraform provides a portable cluster contract. Ansible only deploys the
Helm chart. The Agentium tree lives in this repo; it does not need a
sibling checkout of papAI OPS. `ops/instance` (Nova + kubeadm) is an
optional fallback and is not the GitLab path.

```
validate → terraform plan → terraform apply (manual lab)
        → docker build/push digest → ansible helm → smoke
```

## Compose → Helm

| Compose service | Helm resource | Default |
|---|---|---|
| `agentium-frontend` | Deployment + Service `agentium-frontend` | on |
| `agentium-backend` | Deployment + Service `agentium-backend` | on |
| `agentium-worker-cpu` | Deployment `agentium-worker` | on, embedded beat |
| `agentium-p4-maintenance` | Deployment `agentium-p4-maintenance` | on |
| `agentium-migrate` | Job `agentium-migrate` | on (`post-install,post-upgrade`, waits for Postgres) |
| `agentium-rabbitmq` | StatefulSet + Service | on |
| `agentium-pg` | StatefulSet + Service | on (lab). Turn off when using an external DB |
| `agentium-minio` | StatefulSet + Service | on |
| `agentium-qdrant` | StatefulSet + Service | on |
| `agentium-kc` | Deployment + Service | on |
| `agentium-beat` | — | later (`beat` profile) |
| `agentium-sftp` | — | later (`sftp` profile) |
| `agentium-livekit*` | — | later (`realtime` profiles) |

Service DNS names keep the Compose hostnames (`agentium-backend`,
`agentium-pg`, `agentium-rabbitmq`, …) so existing env files do not have to
be rewritten for the first cut.

Ingress paths copy `deploy/nginx/agentium-container-frontend.conf`:

- `/health/live` → backend `:8000` (smoke; not the SPA)
- `/` → frontend `:8080`
- `/api` → backend `:8000`
- `/kc` → Keycloak `:8080`
- hidden-path regex (`/.env`, `/.git`, `/assets/.secret`) → `404`, same
  contract as `docs/ops/ingress-proxy-contract.md`. `/kc/` and
  `/.well-known/acme-challenge/` stay reachable.

Lab/prod values set `createSecret: false` and `existingSecret`. Placeholders
in `values.yaml` exist only so `helm template` works locally.

## GitLab

Jobs live in `.gitlab/ci/agentium-k8s.yml` under `resource_group`
`agentium-k8s-lab`. They do not share the VM `agentium-production` group
and they do not SSH to `omnirag-demo`.

Protected variables for the first lab apply: `OVH_ENDPOINT`,
`OVH_APPLICATION_KEY`, `OVH_APPLICATION_SECRET`, `OVH_CONSUMER_KEY`,
`OS_PROJECT_ID`, plus registry (`AGENTIUM_LAB_REGISTRY`,
`AGENTIUM_LAB_REGISTRY_USER`, `AGENTIUM_LAB_REGISTRY_PASSWORD`,
`PIP_INDEX_URL`) and `AGENTIUM_LAB_INGRESS_URL` for smoke.

`terraform apply` is manual on protected `demo/agentic` until that lab has
an explicit GO.

## Local models

Ollama and vLLM are optional and off in `values.yaml` and the lab files.
`values-local.yaml` is the container mode: chat and embeddings default to
the in-cluster Ollama. vLLM stays off unless `vllm.enabled` is set; the pod
then requests an NVIDIA GPU and the routing default stays unchanged. The
Mac GPU path is not a chart: Metal is a macOS process, see
`docs/ops/agentium-local-models.md`. The model portal still switches a
workspace to another provider.

## Honesty

- Missing evidence is not a zero. A rendered chart is not a running cluster.
- `helm template` / `terraform validate` prove the scaffold, not a release.
- Sealed writes, image digests, and the VM deploy policy are unchanged.
