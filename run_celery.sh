#!/bin/sh
set -e

# Default values if env vars are not provided
CELERY_QUEUES=${CELERY_QUEUES:-cpu}
CELERY_LOGLEVEL=${CELERY_LOGLEVEL:-info}
export PYTHONPATH="$(pwd)/backend:$(pwd):${PYTHONPATH:-}"

exec python3.12 -m celery -A app.workers.celery_app:celery_app worker \
	--loglevel "$CELERY_LOGLEVEL" \
	--optimization fair \
	--without-gossip \
	--without-mingle \
	-Q "$CELERY_QUEUES"
