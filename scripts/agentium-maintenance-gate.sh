#!/usr/bin/env bash
# Install and toggle the public API maintenance gate used by safe deployments.
set -Eeuo pipefail

MODE="${1:-}"
REPO_DIR="${OMNIRAG_REPO_DIR:-/home/ubuntu/omnirag}"
GATE_DIR="${AGENTIUM_MAINTENANCE_DIR:-/var/lib/agentium}"
GATE_FILE="$GATE_DIR/deploy-maintenance"
SNIPPET_SOURCE="${AGENTIUM_MAINTENANCE_SNIPPET_SOURCE:-$REPO_DIR/deploy/nginx/agentium-deploy-maintenance.conf}"
SNIPPET_TARGET="${AGENTIUM_MAINTENANCE_SNIPPET:-/etc/nginx/snippets/agentium-deploy-maintenance.conf}"
SITE_SOURCE="${AGENTIUM_NGINX_SITE_SOURCE:-$REPO_DIR/deploy/nginx/agentium-container-frontend.conf}"
SITE_TARGET="${AGENTIUM_NGINX_SITE_TARGET:-/etc/nginx/sites-enabled/agentium}"
BACKUP_DIR="${AGENTIUM_NGINX_BACKUP_DIR:-/etc/nginx/agentium-backups}"
SAFE_ORCHESTRATED="${AGENTIUM_SAFE_DEPLOY_ORCHESTRATED:-0}"
SAFE_DEPLOYMENT_DIR="${AGENTIUM_SAFE_DEPLOYMENT_DIR:-}"
SAFE_DEPLOYMENT_ID="${AGENTIUM_SAFE_DEPLOYMENT_ID:-}"
SAFE_GATE_PURPOSE="${AGENTIUM_SAFE_GATE_PURPOSE:-}"
SAFE_GATE_AUTHORIZATION="${AGENTIUM_SAFE_GATE_AUTHORIZATION:-}"
SAFE_GATE_LOCK_FD="${AGENTIUM_SAFE_GATE_LOCK_FD:-}"
SUDO=()

die() {
	printf 'XX  %s\n' "$*" >&2
	exit 1
}

if [[ "$(id -u)" -ne 0 ]]; then
	command -v sudo >/dev/null 2>&1 || die "sudo est requis pour piloter le gate Nginx"
	SUDO=(sudo)
fi

reload_nginx() {
	"${SUDO[@]}" nginx -t
	"${SUDO[@]}" systemctl reload nginx
}

require_orchestrator_context() {
	local frozen metadata_id
	[[ "$SAFE_ORCHESTRATED" == "1" ]] || die "Mutation du gate réservée à l'orchestrateur sûr"
	[[ "$SAFE_DEPLOYMENT_DIR" == /* && "$SAFE_DEPLOYMENT_DIR" != *..* ]] || die "Répertoire d'orchestration invalide"
	[[ "$SAFE_DEPLOYMENT_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$ ]] || die "Deployment-id d'orchestration invalide"
	[[ -f "$SAFE_DEPLOYMENT_DIR/metadata.tsv" && -f "$SAFE_DEPLOYMENT_DIR/phase" ]] || die "État durable d'orchestration absent"
	frozen="$SAFE_DEPLOYMENT_DIR/agentium-maintenance-gate.sh"
	[[ -f "$frozen" && "$(realpath -e "${BASH_SOURCE[0]}")" == "$(realpath -e "$frozen")" ]] ||
		die "Le gate doit être piloté par le helper candidat figé"
	metadata_id="$(awk -F '\t' '$1 == "deployment_id" {print $2; exit}' "$SAFE_DEPLOYMENT_DIR/metadata.tsv")"
	[[ "$metadata_id" == "$SAFE_DEPLOYMENT_ID" ]] || die "Deployment-id différent des métadonnées figées"
}

assert_terminal_gate_authorization() {
	local terminal_phase="$1" receipt_name authorization_name expected_authorization
	case "$SAFE_GATE_PURPOSE:$terminal_phase" in
	forward-terminal-open:completed)
		receipt_name="release-a-transaction-receipt.json"
		authorization_name="release-a-forward-open-authorization.json"
		;;
	rollback-terminal-open:rolled_back)
		receipt_name="release-a-rollback-receipt.json"
		authorization_name="release-a-rollback-open-authorization.json"
		;;
	*) die "Autorisation terminale inconnue pour purpose=$SAFE_GATE_PURPOSE phase=$terminal_phase" ;;
	esac
	expected_authorization="$SAFE_DEPLOYMENT_DIR/$authorization_name"
	[[ "$SAFE_GATE_AUTHORIZATION" == "$expected_authorization" ]] ||
		die "Autorisation terminale canonique absente"
	[[ "$SAFE_GATE_LOCK_FD" =~ ^[0-9]{1,4}$ && "$SAFE_GATE_LOCK_FD" -ge 3 ]] ||
		die "FD de verrou terminal absent ou invalide"

	# This verifier deliberately does not acquire a previously-unlocked FD.  A
	# fresh contender must first be blocked by an exclusive lock and the
	# inherited FD must then be able to reassert that same lock.  Together those
	# checks distinguish the orchestrator's inherited open-file description from
	# an unlocked FD or a lock held by an unrelated process.
	python3 -I - "$SAFE_DEPLOYMENT_DIR" "$SAFE_DEPLOYMENT_ID" "$SAFE_GATE_PURPOSE" \
		"$terminal_phase" "$receipt_name" "$authorization_name" \
		"$SAFE_GATE_AUTHORIZATION" "$SAFE_GATE_LOCK_FD" <<'PY'
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

(
    deployment_text,
    deployment_id,
    purpose,
    terminal_phase,
    receipt_name,
    authorization_name,
    authorization_text,
    lock_fd_text,
) = sys.argv[1:]
deployment = Path(deployment_text)
authorization = Path(authorization_text)
parent = deployment.parent
lock_fd = int(lock_fd_text)


def fail(message: str) -> "None":
    raise SystemExit(message)


if not deployment.is_absolute() or ".." in deployment.parts:
    fail("unsafe terminal deployment path")
if authorization != deployment / authorization_name:
    fail("terminal authorization is not at its canonical path")

try:
    parent_before = parent.lstat()
    deployment_before = deployment.lstat()
    inherited_lock = os.fstat(lock_fd)
except (FileNotFoundError, OSError) as exc:
    fail(f"terminal lock/deployment identity unavailable: {exc}")
if (
    stat.S_ISLNK(parent_before.st_mode)
    or not stat.S_ISDIR(parent_before.st_mode)
    or stat.S_ISLNK(deployment_before.st_mode)
    or not stat.S_ISDIR(deployment_before.st_mode)
):
    fail("terminal deployment hierarchy is not made of real directories")
if (
    deployment_before.st_uid != os.geteuid()
    or stat.S_IMODE(deployment_before.st_mode) != 0o700
):
    fail("terminal deployment directory is not owner-private")
if not stat.S_ISDIR(inherited_lock.st_mode) or (
    inherited_lock.st_dev,
    inherited_lock.st_ino,
) != (parent_before.st_dev, parent_before.st_ino):
    fail("inherited terminal lock FD does not identify the deployment parent")

directory_flags = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
parent_fd = os.open(parent, directory_flags)
deployment_fd = -1
try:
    parent_opened = os.fstat(parent_fd)
    if (parent_opened.st_dev, parent_opened.st_ino) != (
        parent_before.st_dev,
        parent_before.st_ino,
    ):
        fail("terminal deployment parent changed while opening")
    deployment_fd = os.open(authorization.parent.name, directory_flags, dir_fd=parent_fd)
    deployment_opened = os.fstat(deployment_fd)
    if (deployment_opened.st_dev, deployment_opened.st_ino) != (
        deployment_before.st_dev,
        deployment_before.st_ino,
    ):
        fail("terminal deployment directory changed while opening")

    child = os.fork()
    if child == 0:
        try:
            os.close(lock_fd)
            os.close(deployment_fd)
            contender = os.open(".", directory_flags, dir_fd=parent_fd)
            os.close(parent_fd)
            try:
                fcntl.flock(contender, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                os._exit(0)
            else:
                fcntl.flock(contender, fcntl.LOCK_UN)
                os._exit(1)
        except BaseException:
            os._exit(2)
    _, status = os.waitpid(child, 0)
    if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        fail("deployment parent was not already exclusively locked")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fail("deployment parent lock is not owned by the inherited FD")

    def private_bytes(name: str, maximum: int) -> bytes:
        try:
            path_row = os.stat(name, dir_fd=deployment_fd, follow_symlinks=False)
        except FileNotFoundError:
            fail(f"missing terminal artifact: {name}")
        if (
            stat.S_ISLNK(path_row.st_mode)
            or not stat.S_ISREG(path_row.st_mode)
            or path_row.st_uid != os.geteuid()
            or stat.S_IMODE(path_row.st_mode) != 0o600
            or path_row.st_nlink != 1
            or not 0 < path_row.st_size <= maximum
        ):
            fail(f"unsafe terminal artifact: {name}")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(name, flags, dir_fd=deployment_fd)
        try:
            before = os.fstat(descriptor)
            if (before.st_dev, before.st_ino) != (path_row.st_dev, path_row.st_ino):
                fail(f"terminal artifact changed while opening: {name}")
            body = b""
            while len(body) <= maximum:
                chunk = os.read(descriptor, min(65536, maximum + 1 - len(body)))
                if not chunk:
                    break
                body += chunk
            after = os.fstat(descriptor)
            stable = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            if len(body) > maximum or not stable:
                fail(f"terminal artifact changed while reading: {name}")
            return body
        finally:
            os.close(descriptor)

    def json_object(body: bytes, label: str) -> dict[str, object]:
        def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON key: {key}")
                result[key] = value
            return result

        try:
            value = json.loads(body, object_pairs_hook=no_duplicates)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            fail(f"invalid terminal JSON ({label}): {exc}")
        if not isinstance(value, dict):
            fail(f"invalid terminal JSON object: {label}")
        canonical = json.dumps(value, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        if body != canonical:
            fail(f"non-canonical terminal JSON: {label}")
        return value

    metadata_rows: dict[str, str] = {}
    for line in private_bytes("metadata.tsv", 65536).decode("utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or fields[0] in metadata_rows:
            fail("invalid terminal deployment metadata")
        metadata_rows[fields[0]] = fields[1]
    if metadata_rows.get("deployment_id") != deployment_id:
        fail("terminal metadata deployment identity differs")
    release_a_sha = metadata_rows.get("release_a_sha", "")
    if re.fullmatch(r"[0-9a-f]{40}", release_a_sha) is None:
        fail("terminal metadata Release A SHA is invalid")
    if private_bytes("phase", 128) != f"{terminal_phase}\n".encode():
        fail("terminal phase changed or is non-canonical")

    receipt_body = private_bytes(receipt_name, 2 * 1024 * 1024)
    receipt = json_object(receipt_body, receipt_name)
    if purpose == "forward-terminal-open":
        expected_receipt_keys = {
            "schema_version",
            "kind",
            "result",
            "deployment_id",
            "release_a_sha",
            "release_a_attestation_receipt_sha256",
            "final_evidence_receipt_sha256",
            "manifest_receipt_sha256",
            "preconditions_receipt_sha256",
            "preconditions_evidence_receipt_sha256",
            "runtime_oci_receipt_sha256",
            "sftp_runtime_ready_receipt_sha256",
            "sftp_postgres_ledger_receipt_sha256",
            "completed_at",
        }
        if (
            set(receipt) != expected_receipt_keys
            or receipt.get("schema_version") != 3
            or receipt.get("kind") != "agentium-release-a-transaction-receipt"
            or receipt.get("result") != "passed"
            or receipt.get("deployment_id") != deployment_id
            or receipt.get("release_a_sha") != release_a_sha
        ):
            fail("forward terminal receipt identity/schema differs")
    else:
        expected_receipt_keys = {
            "schema_version",
            "kind",
            "result",
            "deployment_id",
            "restored_sha",
            "rollback_state_sha256",
            "runtime_state_sha256",
            "completed_at",
        }
        if (
            set(receipt) != expected_receipt_keys
            or receipt.get("schema_version") != 2
            or receipt.get("kind") != "agentium-release-a-rollback-receipt"
            or receipt.get("result") != "passed"
            or receipt.get("deployment_id") != deployment_id
            or receipt.get("restored_sha") != metadata_rows.get("live_sha")
        ):
            fail("rollback terminal receipt identity/schema differs")

    authorization_body = private_bytes(authorization_name, 65536)
    authorization_payload = json_object(authorization_body, authorization_name)
    expected_authorization = {
        "schema_version": 1,
        "kind": "agentium-release-a-terminal-gate-authorization",
        "deployment_id": deployment_id,
        "release_a_sha": release_a_sha,
        "purpose": purpose,
        "terminal_phase": terminal_phase,
        "receipt_name": receipt_name,
        "receipt_sha256": hashlib.sha256(receipt_body).hexdigest(),
    }
    if authorization_payload != expected_authorization:
        fail("terminal gate authorization identity/digest differs")
    parent_after = parent.lstat()
    deployment_after = deployment.lstat()
    inherited_after = os.fstat(lock_fd)
    if (
        (parent_after.st_dev, parent_after.st_ino)
        != (parent_opened.st_dev, parent_opened.st_ino)
        or (deployment_after.st_dev, deployment_after.st_ino)
        != (deployment_opened.st_dev, deployment_opened.st_ino)
        or (inherited_after.st_dev, inherited_after.st_ino)
        != (parent_opened.st_dev, parent_opened.st_ino)
    ):
        fail("terminal deployment/lock identity changed during authorization")
finally:
    if deployment_fd >= 0:
        os.close(deployment_fd)
    os.close(parent_fd)
PY
}

write_marker_durably() {
	local candidate_sha site_sha snippet_sha
	candidate_sha="$(awk -F '\t' '$1 == "candidate_sha" {print $2; exit}' "$SAFE_DEPLOYMENT_DIR/metadata.tsv")"
	[[ "$candidate_sha" =~ ^[0-9a-f]{40}$ ]] || die "SHA candidat absent des métadonnées"
	site_sha="$(sha256sum "$SITE_SOURCE" | awk '{print $1}')"
	snippet_sha="$(sha256sum "$SNIPPET_SOURCE" | awk '{print $1}')"
	if "${SUDO[@]}" test -e "$GATE_FILE" || "${SUDO[@]}" test -L "$GATE_FILE"; then
		assert_marker_owned
		return
	fi
	"${SUDO[@]}" python3 -I - "$GATE_DIR" "$GATE_FILE" "$SAFE_DEPLOYMENT_ID" "$candidate_sha" "$site_sha" "$snippet_sha" <<'PY'
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

directory, target = map(Path, sys.argv[1:3])
deployment_id, candidate_sha, site_sha, snippet_sha = sys.argv[3:]
directory.mkdir(parents=True, exist_ok=True, mode=0o755)
temporary = directory / f".{target.name}.{os.getpid()}"
fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"deployment_id\t{deployment_id}\n")
        handle.write(f"candidate_sha\t{candidate_sha}\n")
        handle.write(f"site_sha256\t{site_sha}\n")
        handle.write(f"snippet_sha256\t{snippet_sha}\n")
        handle.write(f"closed_at\t{datetime.now(timezone.utc).isoformat()}\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
except BaseException:
    temporary.unlink(missing_ok=True)
    raise
PY
}

assert_marker_owned() {
	local candidate_sha site_sha snippet_sha
	candidate_sha="$(awk -F '\t' '$1 == "candidate_sha" {print $2; exit}' "$SAFE_DEPLOYMENT_DIR/metadata.tsv")"
	site_sha="$(sha256sum "$SITE_SOURCE" | awk '{print $1}')"
	snippet_sha="$(sha256sum "$SNIPPET_SOURCE" | awk '{print $1}')"
	"${SUDO[@]}" python3 -I - "$GATE_FILE" "$SAFE_DEPLOYMENT_ID" "$candidate_sha" "$site_sha" "$snippet_sha" <<'PY'
import os,re,stat,sys
from pathlib import Path
path=Path(sys.argv[1]); expected=sys.argv[2:]
value=path.lstat()
if not stat.S_ISREG(value.st_mode) or stat.S_ISLNK(value.st_mode) or value.st_nlink!=1:
    raise SystemExit("unsafe maintenance marker")
rows={}
for line in path.read_text(encoding="utf-8").splitlines():
    key,separator,item=line.partition("\t")
    if not separator or key in rows: raise SystemExit("invalid maintenance marker")
    rows[key]=item
if set(rows)!={"deployment_id","candidate_sha","site_sha256","snippet_sha256","closed_at"}:
    raise SystemExit("maintenance marker schema differs")
if [rows["deployment_id"],rows["candidate_sha"],rows["site_sha256"],rows["snippet_sha256"]]!=expected:
    raise SystemExit("maintenance marker identity differs")
if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[^\t\r\n]+",rows["closed_at"]) is None:
    raise SystemExit("maintenance marker timestamp invalid")
PY
}

assert_gate_effective_closed() {
	local nginx_dump source_sha snippet_sha target_sha target_snippet_sha
	assert_marker_owned
	source_sha="$(sha256sum "$SITE_SOURCE" | awk '{print $1}')"
	snippet_sha="$(sha256sum "$SNIPPET_SOURCE" | awk '{print $1}')"
	target_sha="$("${SUDO[@]}" sha256sum "$SITE_TARGET" | awk '{print $1}')"
	target_snippet_sha="$("${SUDO[@]}" sha256sum "$SNIPPET_TARGET" | awk '{print $1}')"
	[[ "$target_sha" == "$source_sha" && "$target_snippet_sha" == "$snippet_sha" ]] ||
		die "Gate fermé non conforme aux blobs candidats"
	"${SUDO[@]}" nginx -t >/dev/null
	nginx_dump="$("${SUDO[@]}" nginx -T 2>&1)" || die "Nginx effectif illisible"
	[[ "$nginx_dump" == *'include /etc/nginx/snippets/agentium-deploy-maintenance.conf;'* ]] ||
		die "Nginx effectif ne charge pas le gate"
	[[ "$nginx_dump" == *'if (-f /var/lib/agentium/deploy-maintenance)'* && "$nginx_dump" == *'if ($server_addr = 127.0.0.2)'* ]] ||
		die "Gate effectif ne borne pas maintenance et destination canari"
}

remove_owned_marker_durably() {
	"${SUDO[@]}" python3 -I - "$GATE_FILE" "$SAFE_DEPLOYMENT_ID" <<'PY'
import os
import sys
from pathlib import Path

target = Path(sys.argv[1])
deployment_id = sys.argv[2]
values = {}
for line in target.read_text(encoding="utf-8").splitlines():
    key, separator, value = line.partition("\t")
    if not separator or key in values:
        raise SystemExit("invalid maintenance marker")
    values[key] = value
if values.get("deployment_id") != deployment_id:
    raise SystemExit("maintenance marker belongs to another deployment")
target.unlink()
directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
}

install_gate() {
	local source_sha target_sha compatible_sha timestamp backup_site backup_snippet
	local nginx_dump had_snippet=0
	[[ -f "$SNIPPET_SOURCE" ]] || die "Snippet de maintenance introuvable: $SNIPPET_SOURCE"
	[[ -f "$SITE_SOURCE" && ! -L "$SITE_SOURCE" ]] || die "Site Nginx canonique introuvable: $SITE_SOURCE"
	"${SUDO[@]}" test -f "$SITE_TARGET" || die "Site Nginx actif introuvable: $SITE_TARGET"
	"${SUDO[@]}" test ! -L "$SITE_TARGET" || die "Le site Nginx actif ne doit pas être un lien symbolique"

	# This is a deliberately narrow one-way adoption.  The live site may either
	# already be the canonical gated file, or be exactly that file with only the
	# maintenance include lines absent.  Any other drift requires human review.
	source_sha="$(sha256sum "$SITE_SOURCE" | awk '{print $1}')"
	compatible_sha="$(sed '\#agentium-deploy-maintenance\.conf#d' "$SITE_SOURCE" | sha256sum | awk '{print $1}')"
	target_sha="$("${SUDO[@]}" sha256sum "$SITE_TARGET" | awk '{print $1}')"
	[[ "$target_sha" == "$source_sha" || "$target_sha" == "$compatible_sha" ]] ||
		die "Site Nginx divergent; adoption automatique refusée ($target_sha)"

	timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
	backup_site="$BACKUP_DIR/agentium.$timestamp.$target_sha.conf"
	backup_snippet="$BACKUP_DIR/maintenance-snippet.$timestamp.conf"
	"${SUDO[@]}" install -d -m 0700 "$BACKUP_DIR"
	"${SUDO[@]}" install -m 0600 "$SITE_TARGET" "$backup_site"
	if "${SUDO[@]}" test -f "$SNIPPET_TARGET"; then
		had_snippet=1
		"${SUDO[@]}" install -m 0600 "$SNIPPET_TARGET" "$backup_snippet"
	fi
	"${SUDO[@]}" install -d -m 0755 "$(dirname "$SNIPPET_TARGET")" "$GATE_DIR"
	"${SUDO[@]}" install -m 0644 "$SNIPPET_SOURCE" "$SNIPPET_TARGET"
	"${SUDO[@]}" install -m 0644 "$SITE_SOURCE" "$SITE_TARGET"

	if ! "${SUDO[@]}" nginx -t; then
		"${SUDO[@]}" install -m 0644 "$backup_site" "$SITE_TARGET"
		if [[ "$had_snippet" -eq 1 ]]; then
			"${SUDO[@]}" install -m 0644 "$backup_snippet" "$SNIPPET_TARGET"
		else
			"${SUDO[@]}" rm -f "$SNIPPET_TARGET"
		fi
		"${SUDO[@]}" nginx -t || true
		die "Configuration Nginx candidate invalide; ancien site restauré"
	fi
	if ! "${SUDO[@]}" systemctl reload nginx; then
		"${SUDO[@]}" install -m 0644 "$backup_site" "$SITE_TARGET"
		if [[ "$had_snippet" -eq 1 ]]; then
			"${SUDO[@]}" install -m 0644 "$backup_snippet" "$SNIPPET_TARGET"
		else
			"${SUDO[@]}" rm -f "$SNIPPET_TARGET"
		fi
		"${SUDO[@]}" nginx -t && "${SUDO[@]}" systemctl reload nginx || true
		die "Reload Nginx impossible; ancien site restauré"
	fi
	nginx_dump="$("${SUDO[@]}" nginx -T 2>&1)" || die "Nginx est illisible après installation"
	[[ "$nginx_dump" == *'include /etc/nginx/snippets/agentium-deploy-maintenance.conf;'* ]] ||
		die "Nginx ne charge pas le gate installé"
}

install_gate_closed() {
	# The historical runtime does not yet have the include installed.  Publish
	# the durable marker first, then install/reload the exact gated site.  Nginx
	# therefore never observes the new include without an already closed gate.
	require_orchestrator_context
	write_marker_durably
	if ! install_gate; then
		# Keep the marker on any ambiguous failure.  It is harmless while the old
		# site has no include and will close traffic if a partial install did win.
		die "Installation fermée du gate incomplète; marqueur conservé"
	fi
	assert_gate_effective_closed
}

case "$MODE" in
install)
	install_gate
	;;
install-closed)
	install_gate_closed
	;;
enter)
	require_orchestrator_context
	[[ -f "$SNIPPET_TARGET" ]] || die "Gate non installé; exécuter '$0 install'"
	write_marker_durably
	reload_nginx
	assert_gate_effective_closed
	;;
exit)
	require_orchestrator_context
	phase="$(<"$SAFE_DEPLOYMENT_DIR/phase")"
	case "$SAFE_GATE_PURPOSE:$phase" in
	forward-open:opening_forward | forward-terminal-open:completed | rollback-open:rollback_opening | rollback-terminal-open:rolled_back | pre-closing-recover:prepared | pre-migration-recover:closing_intent | pre-migration-recover:closing | pre-migration-recover:maintenance_closed | pre-migration-recover:quiesced) ;;
	*) die "Ouverture du gate interdite pour purpose=$SAFE_GATE_PURPOSE phase=$phase" ;;
	esac
	case "$SAFE_GATE_PURPOSE:$phase" in
	forward-terminal-open:completed | rollback-terminal-open:rolled_back)
		assert_terminal_gate_authorization "$phase"
		;;
	esac
	# The marker is evaluated per request, so removing it is itself the public
	# reopen. Validate the complete live configuration first; no reload is
	# required for a file-existence gate. A failed validation therefore leaves
	# the persistent marker untouched and cannot create a fail-open interval.
	"${SUDO[@]}" test -f "$GATE_FILE" || die "Gate déjà ouvert; sortie non idempotente refusée"
	"${SUDO[@]}" nginx -t
	remove_owned_marker_durably
	;;
status)
	if "${SUDO[@]}" test -f "$GATE_FILE"; then
		require_orchestrator_context
		assert_gate_effective_closed
		printf '%s\n' closed
	else
		printf '%s\n' open
	fi
	;;
*)
	die "Usage: $0 {install|install-closed|enter|exit|status}"
	;;
esac
