#!/bin/sh
set -e

# Default values if env vars are not provided
CELERY_QUEUES=${CELERY_QUEUES:-cpu}
CELERY_LOGLEVEL=${CELERY_LOGLEVEL:-info}
CELERY_CONCURRENCY=${CELERY_CONCURRENCY:-2}
export PYTHONPATH="$(pwd)/backend:$(pwd):${PYTHONPATH:-}"

# Embed Celery beat in this worker (single-instance deployments only —
# beat must not run twice or periodic tasks double-fire).
BEAT_ARGS=""
if [ "${CELERY_BEAT:-0}" = "1" ]; then
	BEAT_ARGS="--beat --schedule /tmp/celerybeat-schedule"
fi

# shellcheck disable=SC2086 — BEAT_ARGS is intentionally word-split
exec python -m celery -A app.workers.celery_app:celery_app worker \
	--loglevel "$CELERY_LOGLEVEL" \
	--concurrency "$CELERY_CONCURRENCY" \
	--optimization fair \
	--without-gossip \
	--without-mingle \
	$BEAT_ARGS \
	-Q "$CELERY_QUEUES"
