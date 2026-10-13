# Agentium Kubernetes track

Status: IaC + CI on `demo/agentic`, dormant behind `AGENTIUM_LAB_ENABLED`.
The demo VM remains Docker Compose. This document is the map from that
Compose stack to the managed-cluster path (OVH MKS first, AKS twin). Chart
0.2.0 covers the stack as deployed on the VM on 11/10/2026: model-family
workers, Hugging Face, secret registry and optional OpenBao. Chart 0.3.0
adds realtime voice (LiveKit and its sidecar), off by default.

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
| `agentium-worker-cpu` + `agentium-worker-recipes` | Deployment `agentium-worker` (queues `cpu,recipes`) | on, embedded beat |
| `agentium-worker-ml-ts` / `-serve` | Deployments `agentium-worker-ml-ts` / `-serve` (`ml_ts` / `ml_ts_rpc`) | off (`mlTs.enabled`) |
| `agentium-worker-ml-deep` / `-serve` | Deployments `agentium-worker-ml-deep` / `-serve` (`ml_deep` / `ml_deep_rpc`) | off (`mlDeep.enabled`) |
| `agentium-hub-fetch` | Deployment `agentium-hub-fetch` (`hub_fetch`) + RWX PVCs `hub-cache`, `hub-bundles` | off (`huggingface.enabled`) |
| `agentium-openbao` | StatefulSet + Service `agentium-openbao`, NetworkPolicy | off (`openbao.enabled` + `openbao.server.enabled`) |
| `agentium-p4-maintenance` | Deployment `agentium-p4-maintenance` | on |
| `agentium-migrate` | Job `agentium-migrate` | on (`post-install,post-upgrade`, waits for Postgres, `alembic upgrade head`, currently `124_secret_registry`) |
| `agentium-rabbitmq` | StatefulSet + Service | on |
| `agentium-pg` | StatefulSet + Service | on (lab). Turn off when using an external DB |
| `agentium-minio` | StatefulSet + Service | on |
| `agentium-qdrant` | StatefulSet + Service | on |
| `agentium-kc` | Deployment + Service | on, state in the Postgres database `keycloak` |
| `agentium-beat` | — | later (`beat` profile) |
| `agentium-sftp` | — | later (`sftp` profile) |
| `agentium-livekit` | Deployment + Services `agentium-livekit` (`:7880`) and, in `loadBalancer` mode, `agentium-livekit-rtc`; ConfigMap; Ingress `/livekit` | off (`livekit.enabled`) |
| `agentium-livekit-agent` | Deployment + Service `agentium-livekit-agent` (`:8090`) | off (`livekit.enabled`, then `livekit.agent.enabled`) |
| `agentium-livekit-redis` | — (external `livekit.redis.address`, more than one replica only) | off |

Service DNS names keep the Compose hostnames (`agentium-backend`,
`agentium-pg`, `agentium-rabbitmq`, …) so existing env files do not have to
be rewritten for the first cut.

Ingress paths copy `deploy/nginx/agentium-container-frontend.conf`:

- `/health/live` → backend `:8000` (smoke; not the SPA)
- `/` → frontend `:8080`
- `/api` → backend `:8000`
- `/kc` → Keycloak `:8080`
- `/livekit/` → LiveKit `:7880`, prefix stripped (only with `livekit.enabled`)
- hidden-path regex (`/.env`, `/.git`, `/assets/.secret`) → `404`, same
  contract as `docs/ops/ingress-proxy-contract.md`. `/kc/` and
  `/.well-known/acme-challenge/` stay reachable.

Lab/prod values set `createSecret: false` and `existingSecret`. Placeholders
in `values.yaml` exist only so `helm template` works locally.

## Secrets

The application Secret is loaded whole into the application pods: that is
how API keys and client secrets reach them, and it is also why the MinIO
root password, the Hub writer's identity and the OpenBao AppRoles each live
in a Secret of their own. The chart only names Secrets; a lab or production
release creates none of them and no value is ever committed.

| Secret | Read by | Keys |
|---|---|---|
| `existingSecret` (lab: `agentium-lab`) | backend, worker, ml-ts, ml-deep, migrate, p4-maintenance through `envFrom`; Postgres, RabbitMQ and Keycloak by key; hub-fetch by key for the database, broker and registry key only | required: `POSTGRES_PASSWORD`, `RABBITMQ_DEFAULT_PASS`, `OBJECT_STORE_S3_SECRET_KEY`, `KEYCLOAK_CLIENT_SECRET`, `SECRET_REGISTRY_FERNET_KEY`; `AGENTIUM_BOOTSTRAP_ADMIN_PASSWORD` when `keycloak.bootstrapAdmin.email` is set; then every application key the deployment uses (`OPENAI_API_KEY`, `CONNECTOR_SECRETS_FERNET_KEY`, `LLM_PORTAL_FERNET_KEY`, the API's read-only `HF_S3_ACCESS_KEY` / `HF_S3_SECRET_KEY`, `SECURE_DEPOSIT_SESSION_SECRET`, `SMTP_PASSWORD`, …) |
| `minio.existingRootSecret` (lab: `agentium-lab-minio-root`) | MinIO and its init Job only | `MINIO_ROOT_PASSWORD` |
| `secretRegistry.fernetKey.secretName` (optional) | every Agentium pod, by key | `SECRET_REGISTRY_FERNET_KEY` (or `secretRegistry.fernetKey.key`). Empty means the application Secret |
| `huggingface.hubFetch.existingSecret` (lab: `agentium-lab-hub-fetch`) | hub-fetch only, through `envFrom` | `HF_S3_ACCESS_KEY`, `HF_S3_SECRET_KEY` (writer identity), `CONNECTOR_SECRETS_FERNET_KEY`, `LLM_PORTAL_FERNET_KEY`; optional `OBJECT_STORE_S3_ACCESS_KEY` / `OBJECT_STORE_S3_SECRET_KEY`, `HF_TABULAR_DELETE_ACCESS_KEY` / `HF_TABULAR_DELETE_SECRET_KEY` |
| `huggingface.bundleSigning.existingSecret` (optional) | worker and hub-fetch, mounted read-only at `/run/hf-bundle-keys` | the Ed25519 private key file named by `huggingface.bundleSigning.keyFile` |
| `openbao.appRoleSecrets.backend` / `.worker` / `.hubFetch` | backend + migrate / worker / hub-fetch, through `envFrom` after the application Secret | `OPENBAO_ROLE_ID`, `OPENBAO_SECRET_ID` |
| `openbao.server.unsealKeySecret` | the in-cluster OpenBao only, mounted read-only | `unseal.key` (64 hex characters) |
| `livekit.existingSecret` (lab: `agentium-lab-livekit`) | LiveKit and the API, by key | `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` (32 characters or more); optional `LIVEKIT_REDIS_PASSWORD` |
| `livekit.turn.tlsSecret` (optional) | LiveKit only, mounted read-only | `kubernetes.io/tls` for `livekit.turn.domain` |

```bash
# Env files kept outside the repository, one KEY=value per line.
kubectl -n agentium create secret generic agentium-lab --from-env-file=agentium-lab.env
kubectl -n agentium create secret generic agentium-lab-minio-root \
  --from-env-file=agentium-lab-minio-root.env
```

- An install or upgrade whose application Secret still holds
  `MINIO_ROOT_PASSWORD`, `OPENBAO_ROLE_ID`, `OPENBAO_SECRET_ID`,
  `HF_TABULAR_DELETE_SECRET_KEY` or `LIVEKIT_API_SECRET` is refused. The check uses `lookup`, so
  `helm template` cannot see it; only a release against the cluster does.
- `helm template` with `createSecret: true` (local only) generates a random
  `SECRET_REGISTRY_FERNET_KEY` once and keeps it across upgrades through
  `lookup`. Every other environment brings its own.
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

## Model-family workers

`mlTs.enabled` and `mlDeep.enabled` are the Compose profiles `ml-ts` and
`ml-deep`. Each renders a training worker and a serving worker (threads
pool, the queue the API waits on), on `image.mlTs` / `image.mlDeep`, with
the memory limits of the Compose `mem_limit`. Until a family's worker beats,
the catalog greys that family out instead of queueing work nobody consumes.
`mlDeep.modelsClaim` names a PVC with the provisioned weights, mounted
read-only at `/data/models`; no weights are baked into the image.

## Hugging Face

`huggingface.enabled` is `docker/compose.agentium.huggingface.yml`
(`docs/huggingface-operations.md`):

- `agentium-hub-fetch` is the only Hub client. It loads its own Secret and
  nothing else whole, and takes the database and broker URLs and the
  registry key by reference. Runtimes (API, worker, ml-deep) run with
  `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.
- `hub-cache` is written by hub-fetch and mounted read-only in the API, the
  worker and ml-deep; `hub-bundles` is written by the API, the worker and
  hub-fetch. Several pods share them, so both are `ReadWriteMany`: set
  `huggingface.cache.existingClaim` / `bundles.existingClaim`, or a
  `storageClass` that provisions RWX volumes (AKS: `azurefile-csi`; OVH MKS
  has none by default, bring an NFS-backed claim). The release is refused
  otherwise. The claims the chart creates are kept on uninstall.
- `huggingface.limits`, `allowedEndpoints` and the public
  `trustKeysJson` go to the ConfigMap. The signing key is a Secret file,
  mounted only where bundles are exported (worker, hub-fetch).
- Images: backend and worker must be built with `INSTALL_HF_RAG=1`, plus the
  `agentium-hub-fetch` image (`AGENTIUM_LAB_OPTIONAL_IMAGES` below).
- MinIO: the init Job creates the application user only. Create the
  hub-fetch, hub-read and tabular-purge identities with the policies of
  `scripts/agentium_hf_storage_policies.py`.

## Secret registry and OpenBao

`SECRET_REGISTRY_FERNET_KEY` is required by every Agentium pod (read by key,
so a missing key fails at pod creation). `secretRegistry.defaultBackend`
(`db` or `openbao`) only chooses the backend of new secrets; existing
secrets keep theirs. `openbao` as default without `openbao.enabled` is
refused.

`openbao.enabled` wires the clients: `OPENBAO_ADDR`, `OPENBAO_MOUNT`,
`OPENBAO_TIMEOUT_SECONDS`, and one AppRole Secret per role, as on the VM:
`backend` for the API and the migrate Job, `worker` for the worker,
`hubFetch` for hub-fetch. ml-ts, ml-deep and p4-maintenance get none.
`openbao.addr` points at an external OpenBao; with
`openbao.server.enabled` the chart runs the single-node server of
`docker/compose.agentium.openbao.yml` instead (same digest, raft on a PVC,
static-key auto-unseal, declarative file audit, read-only root filesystem,
a NetworkPolicy that admits only the API, worker, migrate and hub-fetch
pods). Its readiness is `bao status`, so it stays unready until initialised.

First install of the in-cluster server, from an operator workstation:

```bash
# 1. Unseal key: never generated or owned by the chart. Keep a copy in the
#    team vault; losing it makes the raft data unreadable.
umask 077; openssl rand -hex 32 | tr -d '\n' > unseal.key
kubectl -n agentium create secret generic agentium-lab-openbao-unseal --from-file=unseal.key
# 2. Release with openbao.server.enabled and the AppRole Secret names set.
#    Pods that reference a missing AppRole Secret wait; that is expected.
# 3. Initialise and configure through a port-forward. Credentials land in
#    a private directory, never on stdout; the root token is revoked.
kubectl -n agentium port-forward pod/agentium-openbao-0 8200:8200 &
mkdir -m 0700 runtime-env
python3 scripts/agentium_openbao_bootstrap.py init --addr http://127.0.0.1:8200 --runtime-env runtime-env
# 4. One Secret per role.
for role in backend worker hub-fetch; do
  kubectl -n agentium create secret generic "agentium-lab-openbao-$role" \
    --from-env-file="runtime-env/openbao-$role.env"
done
```

`runtime-env/openbao-recovery.env` and `openbao-snapshot.env` stay in the
team vault. Snapshots and restore follow `docs/agentium-secret-registry.md`
through the same port-forward. Order for an existing deployment: migrate
(`124_secret_registry`), then `scripts/agentium_secret_registry_migrate.py`
(`--dry-run`, then `--backup`), then switch `defaultBackend`.

## LiveKit (realtime voice)

`livekit.enabled` is the Compose profile `realtime`: `agentium-livekit`
(config of `docker/livekit/agentium-livekit.yaml`, same server version) and
`agentium-livekit-agent`. The demo VM keeps running them through
`scripts/agentium-vm-deploy.sh livekit-up`; nothing here changes it.

- Signalling (HTTP/WebSocket `:7880`) goes through the ingress at
  `/livekit/`, prefix stripped, as `deploy/nginx/agentium-container-frontend.conf`
  does. The browser URL is `livekit.publicUrl`, otherwise
  `ws(s)://<ingress.host>/livekit`. The rewrite needs a second Ingress on
  the same host, and ingress-nginx then matches every path of that host as
  a case-insensitive regex (`/api` also matches `/apiX`).
- The API gets `LIVEKIT_ENABLED`, `LIVEKIT_URL`, `LIVEKIT_INTERNAL_URL`
  (`http://agentium-livekit:7880`), `LIVEKIT_AGENT_DISPATCH_URL`
  (`http://agentium-livekit-agent:8090/dispatch`) and
  `LIVEKIT_VOICE_GATEWAY_WS_URL` from the ConfigMap, and the two keys by
  reference from `livekit.existingSecret`. Webhooks are signed with the same
  key, so `LIVEKIT_WEBHOOK_API_KEY` / `_SECRET` are not needed.
- The sidecar is the Compose service: port `8090`, `/healthz` probes, no
  volume, read-only root filesystem, non-root. The room token arrives in the
  `/dispatch` body, so it holds no LiveKit key; it reads `OPENAI_API_KEY`
  alone from the application Secret (optional: without it, batch STT). A
  NetworkPolicy admits the API alone. One replica: sessions live in memory.
  Image `image.livekitAgent`, built from `livekit-agent/`.

Media never crosses the ingress. Two modes, `livekit.network.mode`:

| | `hostNetwork` (lab-ovh default) | `loadBalancer` (lab-aks default) |
|---|---|---|
| Media | UDP `50000-50100` + TCP `7881` on the node's own address, as on the VM | one UDP port (`7882`, ICE mux) + TCP `7881` behind a LoadBalancer Service, `externalTrafficPolicy: Local` |
| Address advertised | discovered by STUN (`use_external_ip`) | `livekit.network.loadBalancer.ip`, reserved beforehand (`NODE_IP`) |
| Placement | `nodeSelector` / `tolerations` (`agentium.io/media=livekit`), one pod per node | any node |
| Replicas | several, with `livekit.redis.address` | one |
| Needs | nodes with a public address and a firewall that opens the media ports | a provider LoadBalancer that carries UDP |

- `hostNetwork` binds `7880` on the node too. Keep it closed at the node
  firewall: the ingress reaches it over the cluster network. NetworkPolicies
  do not cover host-network pods, so the chart renders none for LiveKit in
  that mode.
- `loadBalancer`: a NetworkPolicy admits signalling from the ingress
  controller namespace (`livekit.ingressControllerNamespace`), the API and
  the sidecar, and media from anywhere. One address cannot front several
  LiveKit nodes, so more than one replica is refused.
- Annotations: lab-ovh sets the Public Cloud Load Balancer
  (`loadbalancer.ovhcloud.com/class: octavia`), which needs an MKS cluster on
  a private network with a gateway; `cluster-ovh-mks` creates neither, hence
  `hostNetwork` there. lab-aks names the Terraform address
  (`service.beta.kubernetes.io/azure-pip-name: agentium-lab-aks-livekit`).
- TURN (`livekit.turn.enabled`, off): LiveKit's embedded TURN on TLS `5349`
  and UDP `3478`, certificate from `livekit.turn.tlsSecret`. `turn.domain`
  must resolve to the media address. It does not listen on 443, so a client
  network that allows only 443 still fails.
- Redis only for more than one replica, and the chart does not run it
  (`agentium-livekit-redis` is the Compose `realtime-scale` profile).
- Release refusals: no `livekit.existingSecret`, the application Secret as
  `livekit.existingSecret`, an unknown mode, `loadBalancer` without its
  address or with several replicas, several replicas without Redis, TURN
  without domain or certificate.

Terraform (all off by default, nothing applied by this change):
`cluster-ovh-mks` `media_nodepool` adds a tainted media pool; the module has
no OpenStack provider and manages no security group, so check that the
project's node security group lets the UDP range in. `cluster-aks`
`livekit_public_ip` reserves the static address for `loadBalancer`
(output `livekit_public_ip`), and `media_node_pool` adds a pool with public
node IPs and the UDP range and `7881` allowed as host ports for
`hostNetwork`. Port values there must match the chart's.

```bash
# Keys stay out of the repository; the secret needs 32 characters or more.
kubectl -n agentium create secret generic agentium-lab-livekit \
  --from-env-file=agentium-lab-livekit.env
```

## Images

`ops/scripts/build-lab-images.sh` always builds frontend, backend and
worker. `AGENTIUM_LAB_OPTIONAL_IMAGES` (CI variable) adds `ml-ts`,
`ml-deep`, `hub-fetch` and/or `livekit-agent`; `hub-fetch` also builds
backend and worker with `INSTALL_HF_RAG=1`. The digest overlay then sets
`image.mlTs`, `image.mlDeep`, `image.hubFetch` and `image.livekitAgent`.
The LiveKit server image is the public `livekit/livekit-server` tag, as in
Compose.

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
- The 0.2.0 components (model-family workers, hub-fetch, OpenBao) are
  rendered and checked by `ops/scripts/check-k8s-scaffold.sh`, not run. RWX
  provisioning, the OpenBao NetworkPolicy (it needs a CNI that enforces
  policies) and the port-forward bootstrap are unproven on MKS and AKS.
- LiveKit (0.3.0) is rendered and checked, not run. Unproven on MKS and
  AKS: UDP through either provider's LoadBalancer (mixed TCP/UDP on one
  Service), STUN discovery from a host-network pod, the AKS host-port
  allowance, the `/livekit` rewrite with WebSockets on Application Routing,
  the sidecar's media path to a host-network LiveKit, LiveKit and Node as
  non-root on a read-only root filesystem, and TURN.
- The chart's Qdrant has no API key, unlike the VM. Add one before Qdrant
  holds shared data.
