#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Agentium deployment ==="

# ---- Infrastructure (Docker) ----
echo "[1/5] Ensuring Docker services (Postgres, Qdrant, Keycloak)..."

# Postgres
if ! docker ps --format '{{.Names}}' | grep -q '^agentium-pg$'; then
  docker network create agentium-net 2>/dev/null || true
  docker run -d --name agentium-pg --network agentium-net \
    -e POSTGRES_DB=agentium -e POSTGRES_USER=agentium -e POSTGRES_PASSWORD=agentium \
    -v agentium_pgdata:/var/lib/postgresql/data \
    -p 5432:5432 \
    postgres:17
  echo "  Waiting for Postgres..."
  sleep 5
fi

# Qdrant
if ! docker ps --format '{{.Names}}' | grep -q '^agentium-qdrant$'; then
  docker run -d --name agentium-qdrant --network agentium-net \
    -v agentium_qdrant:/qdrant/storage \
    -p 6333:6333 -p 6334:6334 \
    qdrant/qdrant:v1.12.5
fi

# Keycloak
if ! docker ps --format '{{.Names}}' | grep -q '^agentium-kc$'; then
  docker run -d --name agentium-kc --network agentium-net \
    -p 8080:8080 \
    -e KC_DB=postgres \
    -e KC_DB_URL="jdbc:postgresql://agentium-pg:5432/agentium" \
    -e KC_DB_USERNAME=agentium -e KC_DB_PASSWORD=agentium \
    -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
    -e KC_HEALTH_ENABLED=true -e KC_HTTP_ENABLED=true -e KC_HOSTNAME_STRICT=false \
    -v "$SCRIPT_DIR/backend/keycloak/realm-export.json:/opt/keycloak/data/import/realm.json:ro" \
    quay.io/keycloak/keycloak:26.1.4 start-dev --import-realm
fi

echo "  Docker services running."

# ---- Backend ----
echo "[2/5] Activating venv and installing deps..."
cd "$SCRIPT_DIR/backend"
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt

echo "[3/5] Running Alembic migrations..."
alembic upgrade head 2>/dev/null || echo "  (Alembic migration skipped or already up to date)"

echo "[4/5] Seeding default workspace..."
python -m scripts.seed_workspace 2>/dev/null || echo "  (Seed skipped — may already exist)"

echo "[5/5] Starting Uvicorn..."
pkill -f "uvicorn app.main:app" 2>/dev/null || true
sleep 1
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 > "$SCRIPT_DIR/uvicorn.log" 2>&1 &
echo "  Uvicorn PID: $!"

echo ""
echo "=== Deployment complete ==="
echo "Backend:  http://localhost:8000"
echo "Keycloak: http://localhost:8080 (admin/admin)"
echo "Health:   http://localhost:8000/api/v1/health"
