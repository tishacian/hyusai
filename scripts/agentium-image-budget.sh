#!/usr/bin/env bash
# Report, and optionally bound, the size of one release's Agentium images.
#
# usage: scripts/agentium-image-budget.sh <tag>
#
# Prints each image's size, then how many filesystem layers the API and worker
# images share: both Dockerfiles open on an identical Python prefix, so a
# release that suddenly shares none has rebuilt the multi-gigabyte stack twice.
#
# The forecasting image (agentium-ml-ts) is optional: built only where the
# ml-ts profile runs, reported when present, never required.
#
# A budget is enforced only when its variable is set, in MB:
#   AGENTIUM_IMAGE_BUDGET_MB_BACKEND, AGENTIUM_IMAGE_BUDGET_MB_WORKER,
#   AGENTIUM_IMAGE_BUDGET_MB_FRONTEND, AGENTIUM_IMAGE_BUDGET_MB_ML_TS
# Record the sizes this prints in the release notes, then set each budget a few
# percent above them; the release process says where.
set -euo pipefail

tag="${1:?usage: $0 <tag>}"
status=0

layers_of() {
	docker image inspect --format '{{range .RootFS.Layers}}{{println .}}{{end}}' "$1" | sed '/^$/d' | sort
}

printf 'image\tsize_mb\tbudget_mb\tverdict\n'
for name in backend worker frontend ml-ts; do
	image="agentium-${name}:${tag}"
	if ! bytes="$(docker image inspect --format '{{.Size}}' "$image" 2>/dev/null)"; then
		if [[ "$name" == "ml-ts" ]]; then
			printf '%s\t-\t-\tnot built (optional)\n' "$image"
			continue
		fi
		printf '%s\t-\t-\tmissing\n' "$image"
		status=1
		continue
	fi
	size_mb=$((bytes / 1048576))
	budget_var="AGENTIUM_IMAGE_BUDGET_MB_$(printf '%s' "$name" | tr '[:lower:]' '[:upper:]' | tr '-' '_')"
	budget="${!budget_var:-}"
	verdict="unbounded"
	if [[ -n "$budget" ]]; then
		if ((size_mb > budget)); then
			verdict="OVER"
			status=1
		else
			verdict="ok"
		fi
	fi
	printf '%s\t%s\t%s\t%s\n' "$image" "$size_mb" "${budget:--}" "$verdict"
done

backend="agentium-backend:${tag}"
worker="agentium-worker:${tag}"
if docker image inspect "$backend" "$worker" >/dev/null 2>&1; then
	shared="$(comm -12 <(layers_of "$backend") <(layers_of "$worker") | wc -l | tr -d ' ')"
	printf 'layers shared by backend and worker: %s\n' "$shared"
	if ((shared < 5)); then
		echo "backend and worker no longer share their Python layers: check the" \
			"shared prefix of docker/Dockerfile.agentium-{backend,worker}" >&2
		status=1
	fi
fi

ml_ts="agentium-ml-ts:${tag}"
if docker image inspect "$backend" "$ml_ts" >/dev/null 2>&1; then
	shared="$(comm -12 <(layers_of "$backend") <(layers_of "$ml_ts") | wc -l | tr -d ' ')"
	printf 'layers shared by backend and ml-ts: %s\n' "$shared"
	if ((shared < 5)); then
		echo "the forecasting image no longer shares the Python layers: check the" \
			"shared prefix of docker/Dockerfile.agentium-ml-ts" >&2
		status=1
	fi
fi

exit "$status"
