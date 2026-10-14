#!/bin/sh
set -e

# Default values if env vars are not provided
CELERY_QUEUES=${CELERY_QUEUES:-cpu}
CELERY_LOGLEVEL=${CELERY_LOGLEVEL:-info}
CELERY_CONCURRENCY=${CELERY_CONCURRENCY:-2}
# A model-family image runs app.workers.celery_ml:celery_ml, which registers the
# ML tasks only; the general worker keeps the full app.
CELERY_APP=${CELERY_APP:-app.workers.celery_app:celery_app}
# Exported: a family worker's heartbeat reports the queues it consumes.
export CELERY_QUEUES
PYTHONPATH="$(pwd)/backend:$(pwd):${PYTHONPATH:-}"
export PYTHONPATH

# Connector pools reserve independent capacity. A misconfigured queue list
# must not let the general worker steal their tasks, or merge both pools.
case "$CELERY_APP" in
app.workers.celery_connectors:celery_connectors)
	case "$CELERY_QUEUES" in
	connectors | connectors_interactive) ;;
	*)
		echo "connector workers require exactly one dedicated queue" >&2
		exit 2
		;;
	esac
	[ "${CELERY_BEAT:-0}" = 0 ] || {
		echo "connector workers cannot run beat" >&2
		exit 2
	}
	;;
*)
	case ",$CELERY_QUEUES," in
	*,connectors,* | *,connectors_interactive,*)
		echo "connector queues require the dedicated connector worker" >&2
		exit 2
		;;
	esac
	;;
esac

# Embed Celery beat in this worker (single-instance deployments only —
# beat must not run twice or periodic tasks double-fire).
BEAT_ARGS=""
if [ "${CELERY_BEAT:-0}" = "1" ]; then
	BEAT_ARGS="--beat --schedule /tmp/celerybeat-schedule"
fi

# A serving worker shares one in-process model cache across threads.
POOL_ARGS=""
if [ -n "${CELERY_POOL:-}" ]; then
	POOL_ARGS="--pool $CELERY_POOL"
fi

# BEAT_ARGS and POOL_ARGS are intentionally word-split.
# shellcheck disable=SC2086
exec python -m celery -A "$CELERY_APP" worker \
	--loglevel "$CELERY_LOGLEVEL" \
	--concurrency "$CELERY_CONCURRENCY" \
	--optimization fair \
	--without-gossip \
	--without-mingle \
	$BEAT_ARGS \
	$POOL_ARGS \
	-Q "$CELERY_QUEUES"
