#!/bin/sh
set -e

# Default values if env vars are not provided
CELERY_QUEUES=${CELERY_QUEUES:-cpu}
CELERY_LOGLEVEL=${CELERY_LOGLEVEL:-info}
CELERY_CONCURRENCY=${CELERY_CONCURRENCY:-2}
export PYTHONPATH="$(pwd)/backend:$(pwd):${PYTHONPATH:-}"

exec python -m celery -A app.workers.celery_app:celery_app worker \
	--loglevel "$CELERY_LOGLEVEL" \
	--concurrency "$CELERY_CONCURRENCY" \
	--optimization fair \
	--without-gossip \
	--without-mingle \
	-Q "$CELERY_QUEUES"
