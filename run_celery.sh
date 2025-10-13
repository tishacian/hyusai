#!/bin/sh
set -e

# Default values if env vars are not provided
CELERY_QUEUES=${CELERY_QUEUES:-cpu}
CELERY_LOGLEVEL=${CELERY_LOGLEVEL:-info}

exec python3.12 -m celery -A connections.celery.app worker \
    --loglevel "$CELERY_LOGLEVEL" \
    --optimization fair \
    --without-gossip \
    --without-mingle \
    -Q "$CELERY_QUEUES"