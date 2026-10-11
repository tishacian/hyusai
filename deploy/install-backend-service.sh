#!/usr/bin/env bash
# Adopt the canonical Agentium legacy-backend unit and bind it to the private
# runtime environment snapshot captured by deploy-agentium-safe.sh.
set -Eeuo pipefail
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_NAME="agentium-backend.service"
UNIT_SRC="${AGENTIUM_BACKEND_UNIT_SOURCE:-$HERE/agentium-backend.service}"
UNIT_DST="${AGENTIUM_BACKEND_UNIT_TARGET:-/etc/systemd/system/$UNIT_NAME}"
BACKUP_DIR="${AGENTIUM_BACKEND_UNIT_BACKUP_DIR:-/etc/systemd/system/agentium-backend-backups}"
DEPLOYMENT_DIR="${AGENTIUM_SAFE_DEPLOYMENT_DIR:-}"
ENV_FILE="${AGENTIUM_BACKEND_ENV_FILE:-}"
DROPIN_TARGET="${AGENTIUM_BACKEND_ENV_DROPIN_TARGET:-/etc/systemd/system/$UNIT_NAME.d/99-agentium-safe-runtime-env.conf}"
DROPIN_STATE="${AGENTIUM_BACKEND_ENV_DROPIN_STATE:-}"
DROPIN_BACKUP="${AGENTIUM_BACKEND_ENV_DROPIN_BACKUP:-}"
EXPECTED_REVISION="${AGENTIUM_BACKEND_EXPECTED_SHA:-}"
MODE="${1:-install}"
BACKUP_PATH=""
INSTALL_STARTED=0
DROPIN_CAPTURED=0

say() { printf '==> %s\n' "$*"; }
ok() { printf 'OK  %s\n' "$*"; }
die() { printf 'XX  %s\n' "$*" >&2; exit 1; }

[[ "$MODE" == "install" || "$MODE" == "verify" || "$MODE" == "restore-env" ]] ||
	die "Usage: sudo $0 [install|verify|restore-env]"
[[ "$EXPECTED_REVISION" =~ ^[0-9a-f]{40}$ ]] || die "AGENTIUM_BACKEND_EXPECTED_SHA invalide"
[[ "${EUID:-$(id -u)}" -eq 0 ]] || die "Exécuter ce helper avec sudo"
[[ -f "$UNIT_SRC" && ! -L "$UNIT_SRC" ]] || die "Unité source canonique introuvable"
[[ -f "$UNIT_DST" && ! -L "$UNIT_DST" ]] ||
	die "Unité live absente ou symbolique; adoption automatique refusée"

source_loopback_count="$(grep -Ec -- '--host[[:space:]]+127\.0\.0\.1([[:space:]]|$)' "$UNIT_SRC" || true)"
source_public_count="$(grep -Ec -- '--host[[:space:]]+0\.0\.0\.0([[:space:]]|$)' "$UNIT_SRC" || true)"
[[ "$source_loopback_count" == "1" && "$source_public_count" == "0" ]] ||
	die "L'unité source ne porte pas exactement le bind loopback attendu"

source_sha="$(sha256sum "$UNIT_SRC" | awk '{print $1}')"
loopback_no_env_sha="$(sed '/^Environment=STARTUP_RECONCILIATION=disabled$/d; /^Environment=AGENTIUM_DISABLE_DOTENV=1$/d' "$UNIT_SRC" | sha256sum | awk '{print $1}')"
public_no_env_sha="$(sed '/^Environment=STARTUP_RECONCILIATION=disabled$/d; /^Environment=AGENTIUM_DISABLE_DOTENV=1$/d; s/--host 127\.0\.0\.1/--host 0.0.0.0/' "$UNIT_SRC" | sha256sum | awk '{print $1}')"
target_sha="$(sha256sum "$UNIT_DST" | awk '{print $1}')"
[[ "$target_sha" == "$source_sha" || "$target_sha" == "$loopback_no_env_sha" || "$target_sha" == "$public_no_env_sha" ]] ||
	die "Unité live divergente; adoption automatique refusée ($target_sha)"

validate_env_contract() {
	local deploy_real bundle_real env_real owner env_owner
	[[ "$DEPLOYMENT_DIR" == /* && "$DEPLOYMENT_DIR" != *..* && -d "$DEPLOYMENT_DIR" && ! -L "$DEPLOYMENT_DIR" ]] ||
		die "AGENTIUM_SAFE_DEPLOYMENT_DIR persistant invalide"
	deploy_real="$(realpath -e "$DEPLOYMENT_DIR")"
	bundle_real="$(realpath -e "$DEPLOYMENT_DIR/runtime-env")"
	env_real="$(realpath -e "$ENV_FILE")"
	[[ "$bundle_real" == "$deploy_real/runtime-env" && "$env_real" == "$bundle_real"/* ]] ||
		die "Env systemd hors du bundle figé"
	[[ "$ENV_FILE" == "$env_real" && -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] ||
		die "Env systemd figé non canonique"
	[[ "$ENV_FILE" =~ ^[A-Za-z0-9_./-]+$ ]] || die "Chemin env systemd non sûr"
	[[ "$(stat -c '%a' "$ENV_FILE")" == "600" ]] || die "Env systemd figé doit être 0600"
	owner="$(stat -c '%u' "$bundle_real")"
	env_owner="$(stat -c '%u' "$ENV_FILE")"
	[[ "$env_owner" == "$owner" ]] || die "Propriétaire env systemd incohérent"
	[[ "$DROPIN_TARGET" == "/etc/systemd/system/$UNIT_NAME.d/99-agentium-safe-runtime-env.conf" ]] ||
		die "Cible drop-in systemd inattendue"
	[[ "$DROPIN_STATE" == "$deploy_real/systemd-env-dropin.state" ]] ||
		die "État drop-in hors du deployment persistant"
	[[ "$DROPIN_BACKUP" == "$deploy_real/systemd-env-dropin.previous" ]] ||
		die "Backup drop-in hors du deployment persistant"
}

durable_copy() {
	local source="$1" target="$2" mode="$3" uid="$4" gid="$5"
	python3 - "$source" "$target" "$mode" "$uid" "$gid" <<'PY'
import os
import stat
import sys
from pathlib import Path

source, target = map(Path, sys.argv[1:3])
mode, uid, gid = int(sys.argv[3], 8), int(sys.argv[4]), int(sys.argv[5])
flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
source_fd = os.open(source, flags)
try:
    before = os.fstat(source_fd)
    if not stat.S_ISREG(before.st_mode):
        raise SystemExit("source is not a regular file")
    chunks = []
    while True:
        chunk = os.read(source_fd, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    after = os.fstat(source_fd)
finally:
    os.close(source_fd)
if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
    after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
):
    raise SystemExit("source changed during copy")
target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
if target.parent.is_symlink():
    raise SystemExit("target parent is a symlink")
temporary = target.parent / f".{target.name}.{os.getpid()}"
fd = os.open(
    temporary,
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
    0o600,
)
try:
    with os.fdopen(fd, "wb", closefd=False) as handle:
        handle.write(b"".join(chunks))
        handle.flush()
        os.fsync(handle.fileno())
    os.fchmod(fd, mode)
    os.fchown(fd, uid, gid)
    os.fsync(fd)
finally:
    os.close(fd)
os.replace(temporary, target)
directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
}

durable_write_dropin() {
	python3 - "$DROPIN_TARGET" "$ENV_FILE" <<'PY'
import os
import sys
from pathlib import Path

target, env_file = map(Path, sys.argv[1:])
content = f"[Service]\nEnvironmentFile=\nEnvironmentFile={env_file}\n".encode()
target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
if target.parent.is_symlink():
    raise SystemExit("drop-in directory is a symlink")
temporary = target.parent / f".{target.name}.{os.getpid()}"
fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
try:
    with os.fdopen(fd, "wb", closefd=False) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.fchmod(fd, 0o644)
    os.fchown(fd, 0, 0)
    os.fsync(fd)
finally:
    os.close(fd)
os.replace(temporary, target)
directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
}

durable_write_state() {
	local prior_state="$1" prior_sha="${2:--}" prior_mode="${3:--}" prior_uid="${4:--}" prior_gid="${5:--}"
	python3 - "$DROPIN_STATE" "$prior_state" "$prior_sha" "$prior_mode" "$prior_uid" "$prior_gid" <<'PY'
import os
import sys
from pathlib import Path

target = Path(sys.argv[1])
values = sys.argv[2:]
content = (
    "format\t1\n"
    f"state\t{values[0]}\n"
    f"sha256\t{values[1]}\n"
    f"mode\t{values[2]}\n"
    f"uid\t{values[3]}\n"
    f"gid\t{values[4]}\n"
).encode()
temporary = target.parent / f".{target.name}.{os.getpid()}"
fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    with os.fdopen(fd, "wb", closefd=False) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.fchmod(fd, 0o600)
    os.fchown(fd, 0, 0)
    os.fsync(fd)
finally:
    os.close(fd)
os.replace(temporary, target)
directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
}

durable_remove() {
	local target="$1"
	python3 - "$target" <<'PY'
import os
import sys
from pathlib import Path

target = Path(sys.argv[1])
try:
    target.unlink()
except FileNotFoundError:
    pass
directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
}

state_value() {
	local key="$1"
	awk -F '\t' -v key="$key" '$1 == key {print $2; found++} END {exit found == 1 ? 0 : 1}' "$DROPIN_STATE"
}

verify_saved_dropin() {
	local saved_state saved_sha saved_mode saved_uid saved_gid
	[[ -f "$DROPIN_STATE" && ! -L "$DROPIN_STATE" && "$(stat -c '%a:%u' "$DROPIN_STATE")" == "600:0" ]] ||
		die "État drop-in privé absent ou altéré"
	[[ "$(state_value format)" == "1" ]] || die "Format état drop-in invalide"
	saved_state="$(state_value state)"
	saved_sha="$(state_value sha256)"
	saved_mode="$(state_value mode)"
	saved_uid="$(state_value uid)"
	saved_gid="$(state_value gid)"
	case "$saved_state" in
	absent)
		[[ "$saved_sha" == "-" && "$saved_mode" == "-" && "$saved_uid" == "-" && "$saved_gid" == "-" ]] ||
			die "Contrat drop-in absent incohérent"
		[[ ! -e "$DROPIN_BACKUP" && ! -L "$DROPIN_BACKUP" ]] || die "Backup inattendu pour un drop-in absent"
		;;
	present)
		[[ "$saved_sha" =~ ^[0-9a-f]{64}$ && "$saved_mode" =~ ^[0-7]{3,4}$ && "$saved_uid" =~ ^[0-9]+$ && "$saved_gid" =~ ^[0-9]+$ ]] ||
			die "Contrat drop-in précédent invalide"
		[[ -f "$DROPIN_BACKUP" && ! -L "$DROPIN_BACKUP" && "$(stat -c '%a:%u' "$DROPIN_BACKUP")" == "600:0" ]] ||
			die "Backup drop-in privé absent ou altéré"
		[[ "$(sha256sum "$DROPIN_BACKUP" | awk '{print $1}')" == "$saved_sha" ]] || die "Backup drop-in altéré"
		;;
	*) die "État drop-in précédent invalide" ;;
	esac
}

capture_previous_dropin() {
	local before after prior_sha prior_mode prior_uid prior_gid
	if [[ -e "$DROPIN_STATE" || -L "$DROPIN_STATE" ]]; then
		verify_saved_dropin
		DROPIN_CAPTURED=1
		return
	fi
	[[ ! -e "$DROPIN_BACKUP" && ! -L "$DROPIN_BACKUP" ]] || die "Backup drop-in orphelin"
	if [[ -e "$DROPIN_TARGET" || -L "$DROPIN_TARGET" ]]; then
		[[ -f "$DROPIN_TARGET" && ! -L "$DROPIN_TARGET" ]] || die "Drop-in existant non régulier refusé"
		before="$(stat -c '%d:%i:%s:%Y' "$DROPIN_TARGET")"
		prior_sha="$(sha256sum "$DROPIN_TARGET" | awk '{print $1}')"
		prior_mode="$(stat -c '%a' "$DROPIN_TARGET")"
		prior_uid="$(stat -c '%u' "$DROPIN_TARGET")"
		prior_gid="$(stat -c '%g' "$DROPIN_TARGET")"
		durable_copy "$DROPIN_TARGET" "$DROPIN_BACKUP" 0600 0 0
		after="$(stat -c '%d:%i:%s:%Y' "$DROPIN_TARGET")"
		[[ "$before" == "$after" && "$(sha256sum "$DROPIN_TARGET" | awk '{print $1}')" == "$prior_sha" ]] ||
			die "Drop-in existant modifié pendant sa capture"
		durable_write_state present "$prior_sha" "$prior_mode" "$prior_uid" "$prior_gid"
	else
		durable_write_state absent
	fi
	DROPIN_CAPTURED=1
	verify_saved_dropin
}

assert_effective_environment() {
	local expected_sha actual_sha
	expected_sha="$(printf '[Service]\nEnvironmentFile=\nEnvironmentFile=%s\n' "$ENV_FILE" | sha256sum | awk '{print $1}')"
	[[ -f "$DROPIN_TARGET" && ! -L "$DROPIN_TARGET" ]] || die "Drop-in runtime absent"
	actual_sha="$(sha256sum "$DROPIN_TARGET" | awk '{print $1}')"
	[[ "$actual_sha" == "$expected_sha" && "$(stat -c '%a:%u:%g' "$DROPIN_TARGET")" == "644:0:0" ]] ||
		die "Drop-in runtime différent du contrat figé"
	# Read effective systemd properties directly in the checker process. In
	# particular, never put Environment= values in shell arguments, diagnostics,
	# or deployment artifacts: they may contain credentials on a compromised
	# unit. The canonical fragment, sole drop-in and frozen EnvironmentFile are
	# all checked independently before the two non-mutating startup controls.
	python3 - "$UNIT_NAME" "$UNIT_DST" "$DROPIN_TARGET" "$ENV_FILE" "$EXPECTED_REVISION" <<'PY'
import os
import re
import shlex
import stat
import subprocess
import sys

unit_name, expected_fragment, expected_dropin, expected_env_file, expected_revision = sys.argv[1:]
required_environment = {
    "STARTUP_RECONCILIATION": "disabled",
    "AGENTIUM_DISABLE_DOTENV": "1",
}


def fail(message: str) -> None:
    raise SystemExit(message)


def show_property(name: str) -> str:
    try:
        completed = subprocess.run(
            ["systemctl", "show", unit_name, f"--property={name}", "--value"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        fail(f"effective systemd {name} is unavailable")
    if completed.returncode != 0:
        fail(f"effective systemd {name} is unavailable")
    try:
        return completed.stdout.decode("utf-8").strip()
    except UnicodeDecodeError:
        fail(f"effective systemd {name} is invalid")


def split_property(raw: str, name: str) -> list[str]:
    try:
        return shlex.split(raw, posix=True)
    except ValueError:
        fail(f"effective systemd {name} is invalid")


if show_property("FragmentPath") != expected_fragment:
    fail("effective FragmentPath is not the canonical unit")

dropins = split_property(show_property("DropInPaths"), "DropInPaths")
if dropins != [expected_dropin]:
    fail("effective DropInPaths is not the sole frozen drop-in")

environment_files = show_property("EnvironmentFiles")
escaped_env_file = re.escape(expected_env_file)
environment_file_contracts = (
    rf"{escaped_env_file}",
    rf"{escaped_env_file}\s+\(ignore_errors=(?:yes|no)\)",
    rf"\{{\s*path={escaped_env_file}\s*;\s*ignore_errors=(?:yes|no)\s*\}}",
    rf"path={escaped_env_file}\s+ignore_errors=(?:yes|no)",
)
if not any(re.fullmatch(contract, environment_files) for contract in environment_file_contracts):
    fail("effective EnvironmentFiles is not the unique frozen snapshot")

# EnvironmentFile= is evaluated close to exec time and is not expanded into
# systemctl show Environment=. Refuse either control variable in the frozen
# file, even with a nominally safe value, so the canonical unit remains their
# unique owner.
flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
try:
    descriptor = os.open(expected_env_file, flags)
except OSError:
    fail("frozen EnvironmentFile is unavailable")
try:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_size > 16 * 1024 * 1024:
        fail("frozen EnvironmentFile is invalid")
    chunks: list[bytes] = []
    remaining = 16 * 1024 * 1024 + 1
    while remaining:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    after = os.fstat(descriptor)
finally:
    os.close(descriptor)
identity_before = (
    before.st_dev,
    before.st_ino,
    before.st_mode,
    before.st_uid,
    before.st_gid,
    before.st_nlink,
    before.st_size,
    before.st_mtime_ns,
)
identity_after = (
    after.st_dev,
    after.st_ino,
    after.st_mode,
    after.st_uid,
    after.st_gid,
    after.st_nlink,
    after.st_size,
    after.st_mtime_ns,
)
raw_env_file = b"".join(chunks)
if identity_before != identity_after or len(raw_env_file) != after.st_size:
    fail("frozen EnvironmentFile changed while being checked")
try:
    env_file_text = raw_env_file.decode("utf-8")
except UnicodeDecodeError:
    fail("frozen EnvironmentFile is invalid")
assignment = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", re.MULTILINE)
if any(match.group(1) in required_environment for match in assignment.finditer(env_file_text)):
    fail("frozen EnvironmentFile shadows a non-mutating startup control")
revision = re.findall(
    r"^AGENTIUM_IMAGE_REVISION=([0-9a-f]{40})$", env_file_text, re.MULTILINE
)
if revision != [expected_revision]:
    fail("frozen EnvironmentFile is not bound to the expected revision")

effective_assignments: dict[str, str] = {}
environment_tokens = split_property(show_property("Environment"), "Environment")
for token in environment_tokens:
    name, separator, value = token.partition("=")
    if (
        not separator
        or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None
        or name in effective_assignments
    ):
        fail("effective systemd Environment is invalid")
    effective_assignments[name] = value
if effective_assignments != required_environment:
    fail("effective systemd Environment does not enforce the startup controls")

if split_property(show_property("PassEnvironment"), "PassEnvironment"):
    fail("effective PassEnvironment must be empty")
if split_property(show_property("UnsetEnvironment"), "UnsetEnvironment"):
    fail("effective UnsetEnvironment must be empty")
PY
}

restore_previous_dropin() {
	local saved_state saved_sha saved_mode saved_uid saved_gid
	verify_saved_dropin
	saved_state="$(state_value state)"
	if [[ "$saved_state" == "absent" ]]; then
		durable_remove "$DROPIN_TARGET"
		[[ ! -e "$DROPIN_TARGET" && ! -L "$DROPIN_TARGET" ]] || die "Drop-in runtime non supprimé"
	else
		saved_sha="$(state_value sha256)"
		saved_mode="$(state_value mode)"
		saved_uid="$(state_value uid)"
		saved_gid="$(state_value gid)"
		durable_copy "$DROPIN_BACKUP" "$DROPIN_TARGET" "$saved_mode" "$saved_uid" "$saved_gid"
		[[ "$(sha256sum "$DROPIN_TARGET" | awk '{print $1}')" == "$saved_sha" ]] || die "Drop-in précédent non restauré"
		[[ "$(stat -c '%a:%u:%g' "$DROPIN_TARGET")" == "$saved_mode:$saved_uid:$saved_gid" ]] ||
			die "Métadonnées du drop-in précédent non restaurées"
	fi
	systemctl daemon-reload
}

assert_effective_loopback() {
	local effective listeners
	effective="$(systemctl show "$UNIT_NAME" --property=ExecStart --value)"
	[[ "$effective" == *'--host 127.0.0.1'* && "$effective" != *'--host 0.0.0.0'* ]] ||
		die "ExecStart effectif n'impose pas le bind loopback"
	if systemctl is-active --quiet "$UNIT_NAME"; then
		listeners="$(ss -Hltpn 'sport = :8000')"
		[[ -n "$listeners" ]] || die "Backend legacy actif sans listener TCP/8000"
		awk '
			{
				address=$4
				if (address == "127.0.0.1:8000" || address == "[::1]:8000" || address == "::1:8000") next
				bad=1
			}
			END { exit bad ? 1 : 0 }
		' <<<"$listeners" || die "Backend legacy encore exposé hors loopback"
	fi
}

wait_for_health() {
	local attempt
	for attempt in $(seq 1 30); do
		if curl --silent --show-error --fail --noproxy '*' --max-time 3 \
			http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1 &&
			curl --silent --show-error --fail --noproxy '*' --max-time 3 \
			http://127.0.0.1:8000/api/v1/build-info 2>/dev/null |
			python3 -c '
import json, sys
raw = sys.stdin.buffer.read(4097)
if not raw or len(raw) > 4096:
    raise SystemExit(1)
try:
    payload = json.loads(raw)
except (UnicodeDecodeError, json.JSONDecodeError):
    raise SystemExit(1)
if payload.get("service") != "backend" or payload.get("revision") != sys.argv[1]:
    raise SystemExit(1)
if payload.get("revision_verified") is not True:
    raise SystemExit(1)
' "$EXPECTED_REVISION"; then
			return
		fi
		sleep 2
	done
	die "Backend legacy non sain après adoption"
}

restore_previous_unit() {
	local code="${1:-$?}"
	trap - ERR EXIT
	set +e
	if [[ "$INSTALL_STARTED" -eq 1 && -n "$BACKUP_PATH" && -f "$BACKUP_PATH" ]]; then
		printf 'XX  Adoption échouée; restauration de %s\n' "$BACKUP_PATH" >&2
		install -m 0644 "$BACKUP_PATH" "$UNIT_DST"
	fi
	if [[ "$DROPIN_CAPTURED" -eq 1 ]]; then restore_previous_dropin; fi
	systemctl daemon-reload
	systemctl stop "$UNIT_NAME"
	exit "$code"
}

validate_env_contract

if [[ "$MODE" == "verify" ]]; then
	systemctl daemon-reload
	assert_effective_loopback
	assert_effective_environment
	if systemctl is-active --quiet "$UNIT_NAME"; then wait_for_health; fi
	ok "Unité backend loopback liée au snapshot env; état enable/running inchangé"
	exit 0
fi

[[ "${AGENTIUM_SAFE_DEPLOY_ORCHESTRATED:-0}" == "1" ]] ||
	die "L'installation/restauration est réservée à deploy-agentium-safe.sh"
! systemctl is-active --quiet "$UNIT_NAME" ||
	die "L'unité doit être arrêtée sous gates avant mutation"

if [[ "$MODE" == "restore-env" ]]; then
	restore_previous_dropin
	ok "Drop-in EnvironmentFile précédent restauré exactement; unité laissée arrêtée"
	exit 0
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP_DIR"
BACKUP_PATH="$BACKUP_DIR/$UNIT_NAME.$timestamp.$target_sha"
install -m 0600 "$UNIT_DST" "$BACKUP_PATH"
trap 'restore_previous_unit $?' ERR EXIT

capture_previous_dropin
INSTALL_STARTED=1
say "Adoption de l'unité canonique et du snapshot env sous transaction fermée"
durable_write_dropin
install -m 0644 "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload
systemctl stop "$UNIT_NAME"
assert_effective_loopback
assert_effective_environment

# This helper intentionally never calls enable/disable: boot policy belongs to
# the existing installation and must survive the hardening unchanged.
trap - ERR EXIT
ok "Unité adoptée et laissée arrêtée; backup privé: $BACKUP_PATH"
