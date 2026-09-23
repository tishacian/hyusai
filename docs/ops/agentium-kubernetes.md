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
| `agentium-kc` | Deployment + Service | on, state in the Postgres database `keycloak` |
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

## Secrets

Two Secrets, because the first one is loaded whole into the application
pods: that is how API keys and client secrets reach them, and it is also why
the MinIO root password cannot live there.

| Secret | Read by | Keys |
|---|---|---|
| `existingSecret` (lab: `agentium-lab`) | backend, worker, migrate, p4-maintenance through `envFrom`; Postgres, RabbitMQ and Keycloak by key | required: `POSTGRES_PASSWORD`, `RABBITMQ_DEFAULT_PASS`, `OBJECT_STORE_S3_SECRET_KEY`, `KEYCLOAK_CLIENT_SECRET`; `AGENTIUM_BOOTSTRAP_ADMIN_PASSWORD` when `keycloak.bootstrapAdmin.email` is set; then every application key the deployment uses (`OPENAI_API_KEY`, `SECURE_DEPOSIT_SESSION_SECRET`, `SMTP_PASSWORD`, …) |
| `minio.existingRootSecret` (lab: `agentium-lab-minio-root`) | MinIO and its init Job only | `MINIO_ROOT_PASSWORD` |

```bash
# Env files kept outside the repository, one KEY=value per line.
kubectl -n agentium create secret generic agentium-lab --from-env-file=agentium-lab.env
kubectl -n agentium create secret generic agentium-lab-minio-root \
  --from-env-file=agentium-lab-minio-root.env
```

- An install or upgrade whose application Secret still holds
  `MINIO_ROOT_PASSWORD` is refused. The check uses `lookup`, so
  `helm template` cannot see it; only a release against the cluster does.
- The Postgres and RabbitMQ passwords are spliced into `DATABASE_URL` and
  `CELERY_BROKER_URL` as they are. Keep them URL-safe: no `@`, `/`, `:`,
  `#` or `%`.

## Keycloak

The realm is derived at render time from `backend/keycloak/realm-export.json`,
which the chart copy must match byte for byte. That file is the development
realm, so the chart changes three things before import:

- no users: the demo accounts and the `admin` account are dropped;
- `core-service` redirect URIs and web origins point at the app URL
  (`keycloak.appUrl`, otherwise `ingress.host` with `https` when
  `ingress.tls` is set), which is also `APP_PUBLIC_URL` for the backend;
- the `core-resource-server` secret becomes `${AGENTIUM_REALM_CLIENT_SECRET}`,
  which Keycloak resolves at import from `KEYCLOAK_CLIENT_SECRET`, the value
  the backend uses for its admin calls.

The first organization admin comes from `keycloak.bootstrapAdmin.email` at
first install, with `AGENTIUM_BOOTSTRAP_ADMIN_PASSWORD` in the application
Secret. Keycloak keeps its state in the Postgres database `keycloak`, created
by an init container, not in the application database. `--import-realm` only
acts when the realm does not exist yet: later edits to the realm file or to
`bootstrapAdmin` do not reach a running lab.

Not covered yet: the development realm does not grant the
`core-resource-server` service account the `realm-management` roles that
signup and password reset call. Grant them in Keycloak until the realm file
does.

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

## The lab switch

`AGENTIUM_LAB_ENABLED` is the one variable that decides whether this track
reaches a cluster. Set it to the string `true` in the project CI variables
and nowhere else. While it is unset, `plan`, `apply`, `images`, `deploy` and
`smoke` evaluate to `when: never`, so they are absent from the pipeline
rather than skipped. Landing this track on `demo/agentic` therefore changes
no deployment and adds no blocking manual job to the release pipeline.

`agentium-k8s-validate` stays on without the switch. It renders Terraform,
Helm and Ansible on the runner and contacts no cluster, so it is the
regression guard that keeps the scaffold honest while the lab is dormant.
Its failure is red, and it is the only k8s job that can redden a release
pipeline.

The VM release loop is untouched either way.
`agentium-lot6-system360-production` declares its own `needs`, so it never
waits on an ops stage. The Compose services this track adds
(`agentium-ollama`, `agentium-vllm`) sit behind Compose profiles that
`scripts/agentium-vm-deploy.sh` never activates, and its `up` recreates an
explicit service list that does not name them. Nothing here starts on
`omnirag-demo`.

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
- The chart has not been installed on a cluster yet. The realm's `${...}`
  placeholders rely on Keycloak's documented import substitution.
