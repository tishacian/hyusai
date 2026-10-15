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

# The short control queue must never share compute slots or embedded beat.
# Removing whitespace closes accidental mixed-queue configuration too.
CELERY_ORCHESTRATION_QUEUE=${CELERY_ORCHESTRATION_QUEUE:-orchestration}
case ",$(printf '%s' "$CELERY_QUEUES" | tr -d '[:space:]')," in
*,control,*)
	[ "$CELERY_APP" = app.workers.execution_control:app ] || {
		echo "control queue requires the dedicated execution control worker" >&2
		exit 2
	}
	;;
esac
case ",$(printf '%s' "$CELERY_QUEUES" | tr -d '[:space:]')," in
*,"$CELERY_ORCHESTRATION_QUEUE",*)
	[ "$CELERY_APP" = app.workers.temporal_execution:app ] || {
		echo "orchestration queue requires the dedicated Temporal starter" >&2
		exit 2
	}
	;;
esac
if [ "$CELERY_APP" = app.workers.execution_control:app ]; then
	[ "$CELERY_QUEUES" = control ] && [ "$CELERY_CONCURRENCY" = 1 ] && [ "${CELERY_POOL:-solo}" = solo ] && [ "${CELERY_BEAT:-0}" = 0 ] || {
		echo "control worker requires queue control, concurrency 1, solo pool and separate beat" >&2
		exit 2
	}
	CELERY_POOL=solo
fi
if [ "$CELERY_APP" = app.workers.temporal_execution:app ]; then
	[ "$CELERY_QUEUES" = "$CELERY_ORCHESTRATION_QUEUE" ] && [ "$CELERY_CONCURRENCY" = 1 ] && [ "${CELERY_POOL:-solo}" = solo ] && [ "${CELERY_BEAT:-0}" = 0 ] || {
		echo "Temporal starter requires its dedicated orchestration queue, concurrency 1, solo pool and separate beat" >&2
		exit 2
	}
	CELERY_POOL=solo
fi

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
