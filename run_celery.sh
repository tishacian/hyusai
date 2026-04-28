#!/bin/sh
set -e

# Default values if env vars are not provided
CELERY_QUEUES=${CELERY_QUEUES:-cpu}
LOG_LEVEL=${LOG_LEVEL:-info}

exec python3.12 -m celery -A connections.celery.app worker \
	--loglevel "$LOG_LEVEL" \
	--optimization fair \
	--without-gossip \
	--without-mingle \
	-Q "$CELERY_QUEUES"
