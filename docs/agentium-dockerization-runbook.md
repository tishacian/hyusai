# Agentium Dockerization Runbook

This runbook migrates the Agentium API and async workers to Docker while
keeping Nginx on the host and keeping `agentium-sftp.service` untouched.

## Runtime Contract

- `agentium-sftp.service` remains systemd-managed. Do not restart, stop, or
  replace it during an Andritz transfer.
- The demo VM is the build node. Images are built locally on the VM and kept as
  local tags (`agentium-backend:local`, `agentium-worker:local`); no external
  container registry is required for v1.
- `backend/.env` remains the SFTP/systemd env with host-local endpoints.
- Docker services use a separate env file through `AGENTIUM_ENV_FILE`.
- Nginx stays on the host. First cutover is blue/green:
  - systemd backend remains on `127.0.0.1:8000`;
  - Docker backend starts on `127.0.0.1:8001`;
  - Nginx switches `/api/` to `8001` only after checks pass.
- Existing Docker volumes are reused:
  - `agentium_pgdata` for Postgres;
  - `qdrant_data` for Qdrant;
  - `agentium_rabbitmq` for RabbitMQ.

## Files

- `docker/compose.agentium.yml` — production Agentium Compose stack.
- `docker/env/agentium.env.example` — container env template.
- `docker/env/keycloak.agentium.env.example` — Keycloak env template.
- `docker/env/qdrant.agentium.env.example` — Qdrant env template.
- `deploy/nginx/agentium-container-backend.conf` — Nginx config that points API
  traffic to the Docker backend on `8001`.

## VM Preparation

```bash
cd /home/ubuntu/omnirag
mkdir -p /home/ubuntu/agentium-data/object_store
cp docker/env/agentium.env.example docker/env/agentium.vm.env
cp docker/env/keycloak.agentium.env.example docker/env/keycloak.vm.env
cp docker/env/qdrant.agentium.env.example docker/env/qdrant.vm.env
```

Fill `docker/env/agentium.vm.env` from `backend/.env`, changing only container
hostnames:

```text
DATABASE_URL=postgresql://agentium:<password>@agentium-pg:5432/agentium
KEYCLOAK_URL=https://agentium.papai.ai/kc
KEYCLOAK_URL_INTERNAL=http://agentium-kc:8080/kc
QDRANT_HOST=agentium-qdrant
CELERY_BROKER_URL=amqp://guest:<password>@agentium-rabbitmq:5672//
CELERY_CONCURRENCY=2
OBJECT_STORE_BASE_PATH=/data/object_store
SECURE_DEPOSIT_STORAGE_DIR=/data/secure_deposit
DOCUMENT_INGEST_ASYNC_ENABLED=false
```

Keep `DOCUMENT_INGEST_ASYNC_ENABLED=false` until RabbitMQ and the worker are
healthy.

## Safe Start While SFTP Transfer Is Active

First record SFTP state:

```bash
systemctl show agentium-sftp -p MainPID -p NRestarts --value
sudo ss -tnp | grep 2222 || true
```

Ensure existing infra containers are reachable from the Compose network without
recreating them. This does not restart Qdrant:

```bash
docker network inspect agentium-net >/dev/null
docker network connect --alias agentium-qdrant agentium-net qdrant 2>/dev/null || true
```

Start only the new services that do not replace existing infra:

```bash
cd /home/ubuntu/omnirag/docker
export AGENTIUM_ENV_FILE=./env/agentium.vm.env
export PIP_INDEX_URL=<private-index-url>
docker compose -f compose.agentium.yml up -d agentium-rabbitmq
docker compose -f compose.agentium.yml build agentium-backend agentium-worker-cpu
docker compose -f compose.agentium.yml up -d agentium-worker-cpu
docker compose -f compose.agentium.yml up -d agentium-backend
```

Do not run the `infra` profile while SFTP is active. It would recreate
Postgres, Keycloak, or Qdrant containers.

## Pre-Cutover Checks

```bash
curl -fsS http://127.0.0.1:8001/health
curl -fsS http://127.0.0.1:8001/api/v1/health
docker compose -f /home/ubuntu/omnirag/docker/compose.agentium.yml ps
docker logs --tail=100 agentium-backend
docker logs --tail=100 agentium-worker-cpu
systemctl show agentium-sftp -p MainPID -p NRestarts --value
sudo ss -tnp | grep 2222 || true
```

Run migrations through the container only after the backend container can reach
Postgres:

```bash
docker compose -f compose.agentium.yml --profile tools run --rm agentium-migrate
```

## Nginx Cutover

```bash
sudo cp /etc/nginx/sites-enabled/agentium /etc/nginx/sites-enabled/agentium.systemd-backend.bak
sudo cp /home/ubuntu/omnirag/deploy/nginx/agentium-container-backend.conf /etc/nginx/sites-enabled/agentium
sudo nginx -t
sudo systemctl reload nginx
```

Validate:

```bash
curl -fsS https://agentium.papai.ai/api/v1/health
curl -fsSI https://agentium.papai.ai/
systemctl show agentium-sftp -p MainPID -p NRestarts --value
sudo ss -tnp | grep 2222 || true
```

Leave `agentium-backend.service` running during the first observation window so
`/legacy/` and rollback remain available.

## Enable Async Ingestion

After RabbitMQ and `agentium-worker-cpu` are healthy:

```bash
sed -i 's/^DOCUMENT_INGEST_ASYNC_ENABLED=.*/DOCUMENT_INGEST_ASYNC_ENABLED=true/' docker/env/agentium.vm.env
docker compose -f compose.agentium.yml up -d agentium-backend agentium-worker-cpu
```

Then upload a small document and verify a `WorkerJob` is created, completed,
and indexed into Qdrant.

## Rollback

```bash
sudo cp /etc/nginx/sites-enabled/agentium.systemd-backend.bak /etc/nginx/sites-enabled/agentium
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl start agentium-backend
docker compose -f /home/ubuntu/omnirag/docker/compose.agentium.yml stop agentium-backend agentium-worker-cpu agentium-rabbitmq
```

Never include `agentium-sftp.service` in rollback commands.

## Full Infra Adoption After Transfer

When no SFTP upload is active, move existing manually created infra containers
under Compose:

```bash
sudo ss -tnp | grep 2222 || true
docker stop agentium-pg agentium-kc qdrant
docker rm agentium-pg agentium-kc qdrant
docker compose -f compose.agentium.yml --profile infra up -d agentium-pg agentium-kc agentium-qdrant
```

The Compose services reuse `agentium_pgdata` and `qdrant_data`, so no Postgres
restore or Qdrant reindex is expected.
