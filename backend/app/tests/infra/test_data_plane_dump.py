"""The pre-release dump, executed rather than read.

``scripts/agentium-data-plane-dump.sh`` is the routine that decides whether a
migration is reversible. Its own header names the failure it exists to prevent:
a Postgres dump restored without the objects its rows point at is "the worst kind
of backup, the one that looks like it worked". A contract test that only asserted
the script *contains* the right strings would be exactly that failure applied to
the test suite, so this runs the script.

How it runs without a VM
------------------------
Every privileged operation in the script goes through ``docker exec`` or
``docker cp``, which makes it shimmable: a fake ``docker`` on ``PATH`` drops the
container name and runs the command here, against a real PostgreSQL instance and
a directory standing in for the bucket. A fake ``mc`` answers the two
subcommands the mirror uses. What is exercised is therefore the script's own
logic — both ``pg_dump`` invocations, the registry-presence probe, the workspace
scoping query, the three artifact checks, the manifest and the ``.ready`` gate —
rather than a paraphrase of it.

``DATA_ROOT`` is a ``readonly`` assignment to ``/srv/agentium-data``, and it stays
that way: an environment override would hand an operator with a stale variable a
"backup" written somewhere they never look, which is the same silent success the
script is written against. The test rewrites that one line in a copy, and asserts
the line it is rewriting first, so restructuring the script breaks this loudly
instead of quietly testing nothing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.config import settings

ROOT = Path(__file__).resolve().parents[4]
DUMP_SCRIPT = ROOT / "scripts" / "agentium-data-plane-dump.sh"
BUCKET = "agentium-artifacts"
SHA = "abcdef123456"

# Standing in for the two databases the routine takes. Named apart from the
# application's own so a run cannot touch a developer's data.
APP_DB = "agentium_dump_probe"
REGISTRY_DB_FIXTURE = "mlflow_dump_probe"

pytestmark = pytest.mark.postgresql


# ---------------------------------------------------------------------------
# The shims
# ---------------------------------------------------------------------------

FAKE_DOCKER = """#!/bin/sh
# `docker exec <container> cmd...` -> run cmd here; `docker cp a:b c` -> copy.
set -e
case "$1" in
  exec)
    shift
    shift
    exec "$@"
    ;;
  cp)
    shift
    src=${1#*:}
    dst=${2#*:}
    exec cp -a "$src" "$dst"
    ;;
  *)
    echo "fake docker: unsupported verb $1" >&2
    exit 64
    ;;
esac
"""

# `mc du --json <target>` and `mc mirror --quiet <src> <dst>`, where a target is
# `dump/<bucket>/<prefix>` and the bucket is a directory on this filesystem.
FAKE_MC = '''#!/usr/bin/env python3
import json
import os
import shutil
import sys

ROOT = os.environ["FAKE_MC_ROOT"]
BUCKET = os.environ["FAKE_MC_BUCKET"]


def local(target: str) -> str:
    parts = target.split("/")
    assert parts[0] == "dump", target
    assert parts[1] == BUCKET, target
    return os.path.join(ROOT, *parts[2:])


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    verb = args[0]
    if verb == "du":
        path = local(args[1])
        if not os.path.isdir(path):
            # `mc du` on an empty prefix is a fatal error, not a zero. The
            # script relies on that and reads the failure as 0.
            print(f"mc: <ERROR> Unable to stat {args[1]}", file=sys.stderr)
            return 1
        total = 0
        for base, _, files in os.walk(path):
            for name in files:
                total += os.path.getsize(os.path.join(base, name))
        print(json.dumps({"size": total, "objects": 1, "prefix": args[1]}))
        return 0
    if verb == "mirror":
        source, target = local(args[1]), args[2]
        if not os.path.isdir(source):
            return 1
        shutil.copytree(source, target, dirs_exist_ok=True)
        return 0
    print(f"fake mc: unsupported verb {verb}", file=sys.stderr)
    return 64


sys.exit(main(sys.argv[1:]))
'''


def _have(binary: str) -> bool:
    return shutil.which(binary) is not None


def _connection() -> dict[str, str]:
    """Where to reach PostgreSQL, taken from the app's own URL rather than pinned.

    The script names the user it runs as (``agentium``) because on the VM it runs
    inside the database container. Here the instance is whatever this checkout is
    configured against, so CI's credentials work without a second place to keep
    them in step.
    """

    from sqlalchemy.engine import make_url

    url = make_url(settings.database_url)
    environment = {}
    if url.host:
        environment["PGHOST"] = url.host
    if url.port:
        environment["PGPORT"] = str(url.port)
    if url.username:
        environment["PGUSER"] = url.username
    if url.password:
        environment["PGPASSWORD"] = url.password
    return environment


def _psql(database: str, sql: str) -> str:
    """One statement against the probe instance."""

    result = subprocess.run(
        ["psql", "-d", database, "-At", "-c", sql],
        capture_output=True,
        text=True,
        env={**os.environ, **_connection()},
    )
    if result.returncode != 0:
        raise RuntimeError(f"{sql}: {result.stderr.strip()}")
    return result.stdout.strip()


def _maintenance(sql: str) -> None:
    _psql("postgres", sql)


@pytest.fixture()
def probe_databases():
    """An application database with a plane in it, and a registry beside it."""

    if not (_have("psql") and _have("pg_dump")):
        pytest.skip("psql/pg_dump are not installed")
    try:
        _maintenance("select 1")
    except Exception as exc:  # noqa: BLE001 - no instance is a skip, not a failure
        pytest.skip(f"no reachable PostgreSQL: {exc}")

    for database in (APP_DB, REGISTRY_DB_FIXTURE):
        _maintenance(f'drop database if exists "{database}"')
        _maintenance(f'create database "{database}"')
    # Only the columns the dump script reads. A copy of the real DDL would drift
    # against the migrations; what has to stay true is the shape of the queries.
    _psql(
        APP_DB,
        """
        create table tabular_datasets (
            id text primary key,
            workspace_id text not null,
            storage_key text,
            status text not null
        );
        create table ml_models (
            id text primary key,
            workspace_id text not null,
            model_uri text,
            metrics_json jsonb,
            status text not null
        );
        """,
    )
    # `model_versions` is the table the script counts to report registry depth.
    _psql(
        REGISTRY_DB_FIXTURE,
        "create table model_versions (name text, version int);"
        "insert into model_versions values ('ws.churn', 1), ('ws.churn', 2);",
    )
    yield
    for database in (APP_DB, REGISTRY_DB_FIXTURE):
        _maintenance(f'drop database if exists "{database}"')


@pytest.fixture()
def harness(tmp_path, probe_databases):
    """The script, its shims, a bucket directory and a data root."""

    data_root = tmp_path / "srv" / "agentium-data"
    data_root.mkdir(parents=True)
    bucket = tmp_path / "bucket"
    bucket.mkdir()
    binaries = tmp_path / "bin"
    binaries.mkdir()

    original = DUMP_SCRIPT.read_text(encoding="utf-8")
    marker = 'readonly DATA_ROOT=/srv/agentium-data\n'
    assert marker in original, (
        "the dump script no longer declares DATA_ROOT the way this test "
        "redirects it — update the test rather than the script"
    )
    # Also pinned so the databases and containers this shim answers for stay the
    # ones the script asks about.
    for expected in (
        'readonly PG_CONTAINER=agentium-pg',
        'readonly MINIO_CONTAINER=agentium-minio',
        'readonly BACKEND_CONTAINER=agentium-backend',
        'readonly REGISTRY_DB=mlflow',
        'readonly DB=agentium',
        'readonly DB_USER=agentium',
    ):
        assert expected in original, expected
    user = _connection().get("PGUSER", "agentium")
    script = tmp_path / "dump.sh"
    script.write_text(
        original.replace(marker, f'readonly DATA_ROOT={data_root}\n')
        .replace('readonly DB=agentium\n', f'readonly DB={APP_DB}\n')
        .replace('readonly DB_USER=agentium\n', f'readonly DB_USER={user}\n')
        .replace(
            'readonly REGISTRY_DB=mlflow\n',
            f'readonly REGISTRY_DB={REGISTRY_DB_FIXTURE}\n',
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)

    (binaries / "docker").write_text(FAKE_DOCKER, encoding="utf-8")
    (binaries / "docker").chmod(0o755)
    (binaries / "mc").write_text(FAKE_MC, encoding="utf-8")
    (binaries / "mc").chmod(0o755)

    return {
        "script": script,
        "bucket": bucket,
        "data_root": data_root,
        "env": {
            **os.environ,
            **_connection(),
            "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
            "OBJECT_STORE_S3_BUCKET": BUCKET,
            "FAKE_MC_ROOT": str(bucket),
            "FAKE_MC_BUCKET": BUCKET,
        },
    }


def _run(harness, *, sha: str = SHA):
    return subprocess.run(
        [str(harness["script"]), sha, "probe"],
        capture_output=True,
        text=True,
        env=harness["env"],
        cwd=str(harness["script"].parent),
    )


def _seed_plane(harness, *, with_report_state: bool = True) -> dict[str, str]:
    """One ready dataset and one ready model, with their bytes in the bucket."""

    workspace = "ws-1"
    dataset_key = f"workspaces/{workspace}/tabular/datasets/ds-1/data.parquet"
    model_uri = f"workspaces/{workspace}/ml/models/m-1/model"
    report_key = f"workspaces/{workspace}/ml/models/m-1/report/state.joblib"

    bucket = harness["bucket"]
    (bucket / dataset_key).parent.mkdir(parents=True, exist_ok=True)
    (bucket / dataset_key).write_bytes(b"PAR1parquet-bytes")
    (bucket / model_uri).mkdir(parents=True, exist_ok=True)
    (bucket / model_uri / "MLmodel").write_text("flavors: {}\n", encoding="utf-8")
    if with_report_state:
        (bucket / report_key).parent.mkdir(parents=True, exist_ok=True)
        (bucket / report_key).write_bytes(b"skore-state")

    _psql(
        APP_DB,
        f"""
        insert into tabular_datasets values
            ('ds-1', '{workspace}', '{dataset_key}', 'ready');
        insert into ml_models values
            ('m-1', '{workspace}', '{model_uri}',
             '{{"report": {{"key": "{report_key}"}}}}'::jsonb, 'ready');
        """,
    )
    return {"dataset_key": dataset_key, "model_uri": model_uri, "report": report_key}


def _manifest(harness) -> dict:
    window = next(
        (harness["data_root"] / "probe-deployments").iterdir()
    )
    return json.loads((window / "MANIFEST.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The happy path is the whole claim
# ---------------------------------------------------------------------------


def test_a_complete_window_takes_both_databases_and_the_bytes_they_name(harness):
    """The pair, plus the check that makes it a backup rather than two files."""

    keys = _seed_plane(harness)

    result = _run(harness)

    assert result.returncode == 0, result.stderr
    window = harness["data_root"] / "probe-deployments" / f"{_today()}-{SHA}"
    assert (window / ".ready").exists(), "a passing window has to declare itself"

    # Both databases, each with its checksum beside it.
    assert (window / f"pre-{SHA}.dump").stat().st_size > 0
    assert (window / f"pre-{SHA}.dump.sha256").exists()
    assert (window / f"pre-{SHA}-{REGISTRY_DB_FIXTURE}.dump").stat().st_size > 0
    assert (window / f"pre-{SHA}-{REGISTRY_DB_FIXTURE}.dump.sha256").exists()

    # The objects the rows name, and only the prefixes the plane owns.
    assert (window / "objects" / keys["dataset_key"]).is_file()
    assert (window / "objects" / keys["model_uri"] / "MLmodel").is_file()
    assert (window / "objects" / keys["report"]).is_file()

    manifest = _manifest(harness)
    assert manifest["sha12"] == SHA
    assert manifest["slice"] == "probe"
    assert manifest["data_plane_deployed"] is True
    assert manifest["registry_database"] == REGISTRY_DB_FIXTURE
    assert manifest["registry_model_versions"] == 2
    assert manifest["registry_artifacts_missing"] == 0
    assert manifest["report_states"] == 1
    assert manifest["report_states_missing"] == 0
    assert manifest["object_files"] == 3


def test_the_mirror_is_scoped_from_the_registry_and_not_from_the_bucket(harness):
    """A workspace that owns no plane rows must not be dragged in.

    The scope matters more than it looks: knowledge collections live under the
    same bucket and are an order of magnitude larger, so a path glob would turn a
    pre-migration step into a multi-gigabyte copy.
    """

    _seed_plane(harness)
    stranger = harness["bucket"] / "workspaces/ws-2/knowledge/collections/c/big.bin"
    stranger.parent.mkdir(parents=True, exist_ok=True)
    stranger.write_bytes(b"x" * 4096)
    # ...and a prefix of the *same* workspace that the plane does not own.
    other = harness["bucket"] / "workspaces/ws-1/knowledge/collections/c/also.bin"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_bytes(b"y" * 2048)

    assert _run(harness).returncode == 0
    window = harness["data_root"] / "probe-deployments" / f"{_today()}-{SHA}"

    copied = {
        str(path.relative_to(window / "objects"))
        for path in (window / "objects").rglob("*")
        if path.is_file()
    }
    assert not any("knowledge" in name for name in copied), copied
    assert not any(name.startswith("workspaces/ws-2") for name in copied), copied


# ---------------------------------------------------------------------------
# What it refuses
# ---------------------------------------------------------------------------


def test_a_named_artifact_that_is_absent_stops_the_window_from_being_ready(harness):
    """The one refusal that matters: do not migrate against an incomplete window."""

    keys = _seed_plane(harness)
    (harness["bucket"] / keys["model_uri"] / "MLmodel").unlink()

    result = _run(harness)

    assert result.returncode != 0
    assert "MISSING model artifact" in result.stderr
    assert "do NOT migrate" in result.stderr
    window = harness["data_root"] / "probe-deployments" / f"{_today()}-{SHA}"
    # The manifest is still written — it is the evidence of what was wrong — but
    # the marker a restore would look for is not.
    assert _manifest(harness)["registry_artifacts_missing"] == 1
    assert not (window / ".ready").exists()


def test_a_dropped_evaluation_is_counted_and_not_fatal(harness):
    """A model whose report state was too large to keep still trains and serves."""

    keys = _seed_plane(harness)
    (harness["bucket"] / keys["report"]).unlink()

    result = _run(harness)

    assert result.returncode == 0, result.stderr
    manifest = _manifest(harness)
    assert manifest["report_states"] == 0
    assert manifest["report_states_missing"] == 1
    assert manifest["registry_artifacts_missing"] == 0


def test_a_finished_window_is_never_overwritten(harness):
    """The second run of a sha must not quietly replace the evidence of the first."""

    _seed_plane(harness)
    assert _run(harness).returncode == 0

    again = _run(harness)

    assert again.returncode != 0
    assert "already a completed window" in again.stderr


def test_a_database_from_before_the_plane_says_so_instead_of_mirroring_nothing(
    harness,
):
    """An empty ``objects/`` is otherwise indistinguishable from a failed mirror."""

    _psql(APP_DB, "drop table tabular_datasets; drop table ml_models;")

    result = _run(harness)

    assert result.returncode == 0, result.stderr
    assert "predates the data plane" in result.stdout
    manifest = _manifest(harness)
    assert manifest["data_plane_deployed"] is False
    assert manifest["object_files"] == 0
    # The registry is a separate database, so it is still taken.
    assert manifest["registry_database"] == REGISTRY_DB_FIXTURE


def test_a_deployment_without_a_registry_database_is_reported_not_failed(harness):
    """Survivable by design: ``ml_models`` keeps training, serving and promoting."""

    _seed_plane(harness)
    _maintenance(f'drop database if exists "{REGISTRY_DB_FIXTURE}"')

    result = _run(harness)

    assert result.returncode == 0, result.stderr
    assert f"no {REGISTRY_DB_FIXTURE} database" in result.stdout
    manifest = _manifest(harness)
    assert manifest["registry_database"] is None
    assert manifest["registry_dump"] is None
    assert manifest["registry_model_versions"] is None
    # And the rest of the window is still a window.
    assert (
        harness["data_root"] / "probe-deployments" / f"{_today()}-{SHA}" / ".ready"
    ).exists()


def test_a_sha_that_is_not_twelve_hex_characters_is_refused(harness):
    for bad in ("abc", "ABCDEF123456", "abcdef12345g", ""):
        result = _run(harness, sha=bad)
        assert result.returncode != 0, bad
        assert "sha12 is exactly 12 hex characters" in result.stderr


def _today() -> str:
    from datetime import date

    return date.today().isoformat()


def test_the_settings_default_matches_the_database_the_dump_takes():
    """One name for the registry, or the routine backs up the wrong database.

    The script hardcodes ``mlflow``; the application derives the same name from
    ``DATABASE_URL``. If those ever diverge the dump succeeds and covers nothing.
    """

    from app.services import ml_registry

    original = settings.ml_registry_uri
    try:
        settings.ml_registry_uri = ""
        settings.database_url = "postgresql://agentium:secret@db:5432/agentium"
        assert ml_registry.registry_uri().endswith("/mlflow")
    finally:
        settings.ml_registry_uri = original
    assert "readonly REGISTRY_DB=mlflow" in DUMP_SCRIPT.read_text(encoding="utf-8")


@pytest.mark.parametrize("state", ["present", "missing", "corrupt"])
def test_brd_original_is_copied_and_digest_verified(harness, state):
    import hashlib

    original = b"retained business requirements"
    key = "workspaces/ws-brd/brd/author/requirements.docx"
    digest = hashlib.sha256(original).hexdigest()
    _psql(APP_DB, "create table brd_documents (id text, workspace_id text, storage_key text, sha256 text);")
    _psql(APP_DB, f"insert into brd_documents values ('brd-1', 'ws-brd', '{key}', '{digest}');")
    path = harness["bucket"] / key
    if state != "missing":
        path.parent.mkdir(parents=True)
        path.write_bytes(original if state == "present" else b"corrupt")
    result = _run(harness)
    manifest = _manifest(harness)
    window = harness["data_root"] / "probe-deployments" / f"{_today()}-{SHA}"
    assert manifest["brd_documents"] == 1
    assert (window / ".ready").exists() == (state == "present")
    assert (result.returncode == 0) == (state == "present"), result.stderr
    if state == "present":
        assert (window / "objects" / key).read_bytes() == original
    else:
        assert manifest["registry_artifacts_missing"] == 1
        assert f"{state.upper()} BRD original" in result.stderr
