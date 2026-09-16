# Agentium Kubernetes track

Status: scaffold on `cursor/agentium-kubernetes-3892`. The demo VM remains
Docker Compose. This document is the map from that Compose stack to the
Terraform / Ansible / Helm path.

## Why this shape

papAI already provisions OpenStack with Terraform (`OPS/instance`) and deploys
with Ansible + Helm (`OPS/ansible/ansible`). Agentium reuses that split inside
this repo so the two products can share inventory, SSH, and pipeline habits
without a second Compose-only ops story.

The papAI OPS trees were not present on the agent that opened this track.
`ops/instance` and `ops/ansible` are therefore a first-party mirror of that
layout, not a copy of those roles. Import the papAI modules when the repos
are available; do not rewrite them here.

## Compose → Helm

| Compose service | Helm resource | Default |
|---|---|---|
| `agentium-frontend` | Deployment + Service `agentium-frontend` | on |
| `agentium-backend` | Deployment + Service `agentium-backend` | on |
| `agentium-worker-cpu` | Deployment `agentium-worker` | on, embedded beat |
| `agentium-p4-maintenance` | Deployment `agentium-p4-maintenance` | on |
| `agentium-migrate` | Job `agentium-migrate` | on (pre-install/pre-upgrade hook) |
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

- `/` → frontend `:8080`
- `/api` → backend `:8000`
- `/kc` → Keycloak `:8080`

## Honesty

- Missing evidence is not a zero. A rendered chart is not a running cluster.
- `helm template` / `terraform validate` prove the scaffold, not a release.
- Sealed writes, image digests, and the VM deploy policy are unchanged.
