#!/usr/bin/env bash
# Versioned VM deployment path — supersedes the ad-hoc /root/release-b-deploy.sh
# and the untracked /root/release-b-{images,restart,workers}.yml overlays.
#
# Same invocation shape as the 30/07 release-b landing: Release A base compose
# from the build worktree, frozen env, opened overlay — plus the single
# versioned runtime overlay (restart policies + digest pins for the services
# that must never be recreated).  Image tags and worker count now flow through
# the environment instead of a hardcoded overlay:
#
#   export AGENTIUM_IMAGE_TAG="${SHA:0:12}"   # immutable <sha12>, or demo-agentic
#   export AGENTIUM_BACKEND_WORKERS=8         # default below
#
# Rollback to any iteration: AGENTIUM_IMAGE_TAG=<previous sha12>, then `up`.
set -euo pipefail

D=/srv/agentium-data/release-a-deployments/release-a-2026-07-27-omnirag-demo
W=/srv/agentium-data/worktrees/demo-agentic/docker

# Fail closed on an unset or malformed tag: the compose default (`local`) points
# the backend at the stale pre-release-b image.
TAG="${AGENTIUM_IMAGE_TAG:-}"
case "$TAG" in
  demo-agentic|[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo "AGENTIUM_IMAGE_TAG must be 'demo-agentic' or a 12-hex SHA prefix" >&2; exit 2 ;;
esac

# The admin Qdrant key lives in the running container; the backend needs it or
# the chat comes back read-only.  Never logged.
ADMIN=$(docker inspect qdrant --format "{{range .Config.Env}}{{println .}}{{end}}" | sed -n "s/^QDRANT__SERVICE__API_KEY=//p")
[ -n "$ADMIN" ] || { echo "Qdrant admin key not found" >&2; exit 1; }

export COMPOSE_PROJECT_NAME=agentium
export AGENTIUM_IMAGE_TAG="$TAG"
export AGENTIUM_QDRANT_EFFECTIVE_API_KEY="$ADMIN"
export AGENTIUM_BACKEND_WORKERS="${AGENTIUM_BACKEND_WORKERS:-8}"
export AGENTIUM_CELERY_BEAT=0
export AGENTIUM_STARTUP_RECONCILIATION=disabled

compose() {
  docker compose -p agentium \
    --env-file "$D/runtime-env/compose.effective.env" \
    -f "$W/compose.agentium.yml" \
    -f "$D/compose.agentium.opened.yml" \
    -f "$W/compose.agentium.vm-runtime.yml" \
    "$@"
}

case "${1:-}" in
  images)   compose config --images ;;
  migrate)  compose run --rm --no-deps agentium-migrate ;;
  up)       compose up -d --no-build --no-deps agentium-backend agentium-worker-cpu agentium-frontend ;;
  ps)       compose ps ;;
  *)        echo "usage: $0 {images|migrate|up|ps}" >&2; exit 2 ;;
esac
