#!/usr/bin/env bash
# Build one release's images on omnirag-demo: every agentium-*:<sha12> image the
# VM Compose renders, the LiveKit sidecar included, then the size budgets.
# Supersedes the untracked /tmp/deploy-reorg.sh.
#
# usage, as ubuntu (docker group), running this script as of <sha40>:
#   R=/srv/agentium-data/worktrees/demo-agentic
#   sudo git -C "$R" fetch -q origin demo/agentic
#   bash <(git -C "$R" show <sha40>:scripts/agentium-vm-build.sh) <sha40>
#
# The worktree is root-administered: it is fetched and fast-forwarded to
# <sha40> with sudo -n, never reset. Then, as root, with AGENTIUM_IMAGE_TAG=<sha12>:
# agentium-vm-deploy.sh storage-check, migrate (only if backend/alembic
# changed), up, catalog-check, and livekit-up when the sidecar must move to
# this tag. See docs/agentium-release-process.md.
#
#   AGENTIUM_PYTHON_BASE_IMAGE   Python base pinned by digest (default: the
#                                one qualified on the VM)
#   AGENTIUM_IMAGE_BUDGET_MB_*   override a budget below, in MB
set -euo pipefail

fail() {
	printf '%s\n' "$*" >&2
	exit 1
}

readonly R=/srv/agentium-data/worktrees/demo-agentic
readonly LOCK=/tmp/agentium-vm-build.lock
readonly BRANCH=demo/agentic
readonly DEFAULT_PYTHON_BASE_IMAGE=python:3.12-slim@sha256:ec948fa5f90f4f8907e89f4800cfd2d2e91e391a4bce4a6afa77ba265bc3a2fe
# Every image docker/compose.agentium*.yml tags ${AGENTIUM_IMAGE_TAG}. The
# sidecar is part of it: the VM runs the realtime profile.
readonly IMAGES=(backend worker frontend ml-ts ml-deep hub-fetch livekit-agent)

SHA="${1:-}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || fail "usage: $0 <sha40 on origin/$BRANCH>"
readonly SHA SHA12="${SHA:0:12}"
BASE="${AGENTIUM_PYTHON_BASE_IMAGE:-$DEFAULT_PYTHON_BASE_IMAGE}"
[[ "$BASE" =~ @sha256:[0-9a-f]{64}$ ]] || fail "AGENTIUM_PYTHON_BASE_IMAGE must be pinned by digest"
readonly BASE

exec 9>"$LOCK"
flock -n 9 || fail "another build holds $LOCK"

advance_worktree() {
	sudo -n git -C "$R" fetch -q origin "$BRANCH"
	git -C "$R" merge-base --is-ancestor "$SHA" FETCH_HEAD ||
		fail "$SHA is not on origin/$BRANCH"
	if [[ "$(git -C "$R" rev-parse HEAD)" != "$SHA" ]]; then
		sudo -n git -C "$R" merge -q --ff-only "$SHA"
	fi
	# Root creates the files; the docker client reads the build context as ubuntu.
	sudo -n chmod -R a+rX "$R"
	[[ "$(git -C "$R" rev-parse HEAD)" == "$SHA" ]] || fail "worktree is not at $SHA"
	[[ -z "$(git -C "$R" status --porcelain)" ]] || fail "worktree has local changes"
}

build_image() {
	local name="$1"
	local args=(--build-arg AGENTIUM_IMAGE_REVISION="$SHA")
	case "$name" in
	backend | worker | ml-ts | ml-deep | hub-fetch)
		args+=(--build-arg PYTHON_BASE_IMAGE="$BASE" --build-arg PIP_INDEX_URL=https://pypi.org/simple
			--build-arg USER_UID=1000 --build-arg USER_GID=1000)
		;;
	esac
	case "$name" in
	backend) args+=(--build-arg INSTALL_HF_RAG=1) ;;
	worker) args+=(--build-arg INSTALL_HF_RAG=1 --build-arg INSTALL_GISKARD_RAGET=true) ;;
	esac
	printf '=== build agentium-%s:%s %s\n' "$name" "$SHA12" "$(date -u +%T)"
	docker build -q -f "docker/Dockerfile.agentium-$name" "${args[@]}" -t "agentium-$name:$SHA12" . </dev/null
}

advance_worktree
cd "$R"
for name in "${IMAGES[@]}"; do
	build_image "$name" || build_image "$name" || fail "build failed: agentium-$name:$SHA12"
	revision="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "agentium-$name:$SHA12")"
	[[ "$revision" == "$SHA" ]] || fail "agentium-$name:$SHA12 carries revision '$revision', not $SHA"
done

: "${AGENTIUM_IMAGE_BUDGET_MB_BACKEND:=1400}"
: "${AGENTIUM_IMAGE_BUDGET_MB_WORKER:=1760}"
: "${AGENTIUM_IMAGE_BUDGET_MB_FRONTEND:=40}"
: "${AGENTIUM_IMAGE_BUDGET_MB_ML_TS:=1240}"
: "${AGENTIUM_IMAGE_BUDGET_MB_LIVEKIT_AGENT:=110}"
export AGENTIUM_IMAGE_BUDGET_MB_BACKEND AGENTIUM_IMAGE_BUDGET_MB_WORKER AGENTIUM_IMAGE_BUDGET_MB_FRONTEND \
	AGENTIUM_IMAGE_BUDGET_MB_ML_TS AGENTIUM_IMAGE_BUDGET_MB_LIVEKIT_AGENT
AGENTIUM_IMAGE_REQUIRE_LIVEKIT_AGENT=1 scripts/agentium-image-budget.sh "$SHA12" </dev/null ||
	fail "image budget failed for $SHA12"
printf 'build ok: %s images at %s, revision %s\n' "${#IMAGES[@]}" "$SHA12" "$SHA"
