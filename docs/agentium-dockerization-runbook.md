# Agentium Dockerization Runbook

This runbook migrates the Agentium API and async workers to Docker while
keeping Nginx on the host and keeping `agentium-sftp.service` untouched.

## Runtime Contract

- `agentium-sftp.service` remains systemd-managed. Do not restart, stop, or
  replace it during an Andritz transfer.
- The demo VM is the build node. Images are built locally on the VM and kept as
  local tags (`agentium-backend:local`, `agentium-worker:local`,
  `agentium-frontend:local`); no external container registry is required for v1.
- `backend/.env` remains the SFTP/systemd env with host-local endpoints.
- Docker services use a separate env file through `AGENTIUM_ENV_FILE`.
- Nginx stays on the host. First cutover is blue/green:
  - systemd backend remains on `127.0.0.1:8000`;
  - Docker backend starts on `127.0.0.1:8001`;
  - Docker frontend starts on `127.0.0.1:8081`;
  - Nginx switches `/api/` to `8001` and then `/` to `8081` only after checks pass.
- Existing Docker volumes are reused:
  - `agentium_pgdata` for Postgres;
  - `qdrant_data` for Qdrant;
  - `agentium_rabbitmq` for RabbitMQ.
- `agentium_minio` is the new S3-compatible object-store volume. Local
  ObjectStore files remain the source of truth until strict mirror verification
  passes and `OBJECT_STORE_BACKEND=s3` is deliberately enabled.

## Files

- `docker/compose.agentium.yml` — production Agentium Compose stack.
- `docker/Dockerfile.agentium-frontend` — Angular build + Nginx SPA runtime.
- `docker/env/agentium.env.example` — container env template.
- `docker/env/keycloak.agentium.env.example` — Keycloak env template.
- `docker/env/qdrant.agentium.env.example` — Qdrant env template.
- `deploy/nginx/agentium-container-backend.conf` — Nginx config that points API
  traffic to the Docker backend on `8001`.
- `deploy/nginx/agentium-container-frontend.conf` — Nginx config that also
  points SPA traffic to the Docker frontend on `8081`.

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
FAISS_PERSIST_DIRECTORY=/data/faiss_db
CELERY_BROKER_URL=amqp://guest:<password>@agentium-rabbitmq:5672//
CELERY_CONCURRENCY=2
OBJECT_STORE_BASE_PATH=/data/object_store
OBJECT_STORE_S3_BUCKET=agentium-artifacts
OBJECT_STORE_S3_ENDPOINT_URL=http://agentium-minio:9000
OBJECT_STORE_S3_ACCESS_KEY=<minio-user>
OBJECT_STORE_S3_SECRET_KEY=<minio-password>
SECURE_DEPOSIT_STORAGE_DIR=/data/secure_deposit
DOCUMENT_INGEST_ASYNC_ENABLED=false
```

Point the infra profile at the VM-specific env files before adopting existing
containers:

```text
AGENTIUM_KEYCLOAK_ENV_FILE=./env/keycloak.vm.env
AGENTIUM_QDRANT_ENV_FILE=./env/qdrant.vm.env
AGENTIUM_POSTGRES_DB=agentium
AGENTIUM_POSTGRES_USER=agentium
AGENTIUM_POSTGRES_PASSWORD=<same password as DATABASE_URL>
```

If Qdrant should run without auth on the private Docker network, remove the
`QDRANT__SERVICE__API_KEY=` line entirely from `qdrant.vm.env`. An empty value
still enables Qdrant API-key checks.

Keep `DOCUMENT_INGEST_ASYNC_ENABLED=false` until RabbitMQ and the worker are
healthy. Qdrant is the standardized target for new deployments, but
`FAISS_PERSIST_DIRECTORY=/data/faiss_db` keeps legacy workspace presets
compatible until their collections are deliberately migrated.

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
docker compose --env-file ./env/agentium.vm.env -f compose.agentium.yml up -d agentium-rabbitmq
docker compose --env-file ./env/agentium.vm.env -f compose.agentium.yml up -d agentium-minio
docker compose --env-file ./env/agentium.vm.env -f compose.agentium.yml --profile tools run --rm agentium-minio-init
docker compose --env-file ./env/agentium.vm.env -f compose.agentium.yml build agentium-backend agentium-worker-cpu agentium-frontend
docker compose --env-file ./env/agentium.vm.env -f compose.agentium.yml up -d agentium-worker-cpu
docker compose --env-file ./env/agentium.vm.env -f compose.agentium.yml up -d agentium-backend
docker compose --env-file ./env/agentium.vm.env -f compose.agentium.yml up -d agentium-frontend
```

Do not run the `infra` profile while SFTP is active. It would recreate
Postgres, Keycloak, or Qdrant containers.

## Pre-Cutover Checks

```bash
curl -fsS http://127.0.0.1:8001/health
curl -fsS http://127.0.0.1:8001/api/v1/health
curl -fsS http://127.0.0.1:8081/healthz
curl -fsSI http://127.0.0.1:8081/
docker compose -f /home/ubuntu/omnirag/docker/compose.agentium.yml ps
docker logs --tail=100 agentium-backend
docker logs --tail=100 agentium-worker-cpu
docker logs --tail=100 agentium-frontend
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

## Frontend Container Cutover

Switch the SPA only after the frontend container answers locally:

```bash
curl -fsS http://127.0.0.1:8081/healthz
curl -fsSI http://127.0.0.1:8081/
sudo cp /etc/nginx/sites-enabled/agentium /etc/nginx/sites-enabled/agentium.container-backend.bak
sudo cp /home/ubuntu/omnirag/deploy/nginx/agentium-container-frontend.conf /etc/nginx/sites-enabled/agentium
sudo nginx -t
sudo systemctl reload nginx
curl -fsSI https://agentium.papai.ai/
curl -fsS https://agentium.papai.ai/api/v1/health
```

Rollback is only an Nginx copy back to `agentium.container-backend.bak`; the old
static files in `/var/www/agentium` are not removed during this wave.

## Mirror Local ObjectStore To MinIO

This mirrors artifacts without changing the backend runtime. It is safe to run
while the app is live because it only reads local ObjectStore files and writes
missing or changed S3 objects.

```bash
cd /home/ubuntu/omnirag/docker
export AGENTIUM_ENV_FILE=./env/agentium.vm.env
docker compose --env-file ./env/agentium.vm.env -f compose.agentium.yml up -d agentium-minio
docker compose --env-file ./env/agentium.vm.env -f compose.agentium.yml --profile tools run --rm agentium-minio-init

docker compose --env-file ./env/agentium.vm.env -f compose.agentium.yml --profile tools run --rm --no-deps \
  agentium-migrate python -m app.cli.migrate_object_store_to_minio \
  --mode mirror

docker compose --env-file ./env/agentium.vm.env -f compose.agentium.yml --profile tools run --rm --no-deps \
  agentium-migrate python -m app.cli.migrate_object_store_to_minio \
  --mode mirror --apply

docker compose --env-file ./env/agentium.vm.env -f compose.agentium.yml --profile tools run --rm --no-deps \
  agentium-migrate python -m app.cli.migrate_object_store_to_minio \
  --mode verify
```

Only enable S3 after `strict_match: true`:

```bash
sed -i 's/^OBJECT_STORE_BACKEND=.*/OBJECT_STORE_BACKEND=s3/' docker/env/agentium.vm.env
docker compose -f compose.agentium.yml up -d agentium-backend agentium-worker-cpu
curl -fsS https://agentium.papai.ai/api/v1/health
```

Rollback is the inverse env edit (`OBJECT_STORE_BACKEND=local`) plus recreating
`agentium-backend` and `agentium-worker-cpu`. Do not delete
`/home/ubuntu/agentium-data/object_store` until S3 has been observed in
production.

## Enable Async Ingestion

After RabbitMQ and `agentium-worker-cpu` are healthy:

```bash
sed -i 's/^DOCUMENT_INGEST_ASYNC_ENABLED=.*/DOCUMENT_INGEST_ASYNC_ENABLED=true/' docker/env/agentium.vm.env
docker compose -f compose.agentium.yml up -d agentium-backend agentium-worker-cpu
```

Then upload a small document and verify a `WorkerJob` is created, completed,
and indexed into Qdrant.

## Migrate Andritz FAISS Collections To Qdrant

Keep the migration invisible by copying FAISS into Qdrant first, validating ID
parity, then switching the workspace preset only after strict validation:

```bash
cd /home/ubuntu/omnirag/docker
export AGENTIUM_ENV_FILE=./env/agentium.vm.env
docker compose -f compose.agentium.yml --profile tools run --rm --no-deps \
  agentium-migrate python -m app.cli.migrate_faiss_to_qdrant \
  --workspace andritz \
  --collection andritz-mvp-knowledge \
  --dry-run

docker compose -f compose.agentium.yml --profile tools run --rm --no-deps \
  agentium-migrate python -m app.cli.migrate_faiss_to_qdrant \
  --workspace andritz \
  --collection andritz-mvp-knowledge \
  --no-dry-run \
  --replace-target

docker compose -f compose.agentium.yml --profile tools run --rm --no-deps \
  agentium-migrate python -m app.cli.migrate_faiss_to_qdrant \
  --workspace andritz \
  --collection andritz-mvp-knowledge \
  --no-dry-run \
  --switch-preset
```

Rollback remains a preset change: set the Andritz workspace default
`ragVectorDBType` back to `faiss`. Do not delete the FAISS files until the
Qdrant cutover has been observed in production.

## Rollback

```bash
sudo cp /etc/nginx/sites-enabled/agentium.systemd-backend.bak /etc/nginx/sites-enabled/agentium
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl start agentium-backend
docker compose -f /home/ubuntu/omnirag/docker/compose.agentium.yml stop agentium-frontend agentium-backend agentium-worker-cpu agentium-rabbitmq
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

If an SFTP transfer is still active, do not restart Postgres. Safe partial
adoption is:

```bash
# Back up first.
mkdir -p /home/ubuntu/agentium-backups/infra-adoption-$(date +%Y%m%d%H%M%S)
docker exec agentium-pg pg_dump -U agentium -d agentium | gzip -1 > /home/ubuntu/agentium-backups/agentium-postgres.sql.gz

# Qdrant and Keycloak are not in the SFTP data path.
docker stop qdrant && docker rm qdrant
docker compose --env-file ./env/agentium.vm.env -f compose.agentium.yml --profile infra up -d agentium-qdrant

docker stop agentium-kc && docker rm agentium-kc
docker compose --env-file ./env/agentium.vm.env -f compose.agentium.yml --profile infra up -d agentium-kc
```

Postgres adoption remains deferred until `sudo ss -tnp | grep 2222` shows no
active SFTP upload. The SFTP server authenticates deposit links and records file
receipts through Postgres, so keeping the TCP stream open is not sufficient.
