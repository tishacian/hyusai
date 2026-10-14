"""Preview formulas run under OS limits, never in the API interpreter."""

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.core.config import settings
from app.schemas.data_prep import DataPrepSpec
from app.services.dataops import preview as previews
from app.services.dataops import preview_runner as runner
from app.services.dataops.compiler import compile_prep
from app.services.dataops.storage import file_digest
from app.services.dataops.types import describe
from app.services.object_store import get_object_store


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "dataops_preview_memory_mb", 512)
    monkeypatch.setattr(settings, "dataops_preview_timeout_s", 10)
    table = pa.table({"n": [1, 2], "label": ["été", None]})
    path = tmp_path / "source.parquet"
    pq.write_table(table, path)
    key = "workspaces/test/sample.parquet"
    get_object_store().write_file(key, path)
    dataset = SimpleNamespace(
        id=uuid4().hex,
        workspace_id=uuid4().hex,
        version=7,
        row_count=1000,
        lineage_json={
            "sample": {
                "key": key,
                "sha256": file_digest(path),
                "method": "reservoir_seeded",
                "version": 1,
            }
        },
    )
    return dataset, table


def prepared(source, expression="n*2"):
    dataset, table = source
    spec = DataPrepSpec(
        operation="prepare",
        steps=[
            {
                "id": "formula",
                "action": "formula",
                "params": {"output": "value", "expression": expression},
            }
        ],
        outputs=[{"name": "Result"}],
    )
    compiled = compile_prep(
        spec, {"in": describe(table.schema)}, arrow_schemas={"in": table.schema}
    )
    return compiled, {"in": dataset}, spec


def test_ordinary_preview_preserves_rows_profiles_metadata_and_cache(source):
    args = prepared(source)
    result = previews.preview(*args, limit=1)
    assert result["rows"] == [{"n": 1, "label": "été", "value": 2}]
    assert result["stats"]["value"]["mean"] == 3
    assert result["sample_info"] == {"rows": 2, "of_rows": 1000, "version": {"in": 7}}
    assert result["counters"]["outputs"] == {"out": 2}
    assert result["stats_scope"] == "sample"
    assert result["step_schemas"][0]["id"] == "formula"
    assert result["cache_hit"] is False
    assert previews.preview(*args, limit=1)["cache_hit"] is True


@pytest.mark.parametrize(
    "expression",
    [
        "lpad('x',1000000000,'x')",
        "rpad('x',CAST(n*1000000000 AS INTEGER),'x')",
        "replace(lpad('x',10000,'x'),'x',lpad('y',100000,'y'))",
        "concat(lpad('x',300000000,'x'),lpad('y',300000000,'y'))",
    ],
)
def test_expansion_refused_by_os_budget_and_parent_still_serves(source, expression):
    pid = os.getpid()
    with pytest.raises(ValueError) as error:
        previews.preview(*prepared(source, expression))
    # Either enforced budget can win on a constrained runner: even lpad may
    # exhaust its CPU/wall deadline before allocating the oversized value.
    # Both outcomes must leave the parent alive and able to serve the next call.
    expected = {"DATAPREP_PREVIEW_MEMORY_LIMIT", "DATAPREP_PREVIEW_TIMEOUT"}
    assert str(error.value) in expected
    assert os.getpid() == pid
    assert previews.preview(*prepared(source))["rows"][1]["value"] == 4


def test_error_never_contains_authored_sql_or_cell_contents(source, caplog, capsys):
    marker = "private-cell-never-in-error"
    with pytest.raises(ValueError) as caught:
        previews.preview(*prepared(source, f"CAST('{marker}' AS BIGINT)"))
    assert str(caught.value) == "DATAPREP_TYPE_MISMATCH"
    captured = capsys.readouterr()
    assert marker not in caplog.text + captured.out + captured.err


def test_runtime_salt_is_rejected_before_starting_child(source, monkeypatch):
    compiled, datasets, spec = prepared(source)
    compiled = replace(compiled, preview_parameters={"dp_salt_0": "not-a-preview-placeholder"})
    monkeypatch.setattr(
        runner.subprocess, "Popen", lambda *a, **k: pytest.fail("secret crossed process boundary")
    )
    with pytest.raises(ValueError, match="^DATAPREP_PREVIEW_PARAMETERS_INVALID$"):
        previews.preview(compiled, datasets, spec)


def test_preview_salt_is_redacted_without_resolving_secret(source, monkeypatch):
    from app.services.secrets import registry

    dataset, table = source
    spec = DataPrepSpec(
        operation="prepare",
        steps=[
            {
                "id": "hash",
                "action": "hash",
                "params": {
                    "columns": ["n"],
                    "output": "masked",
                    "salt_secret_ref": "secret://workspace/hash-salt#1",
                },
            }
        ],
        outputs=[{"name": "Result"}],
    )
    compiled = compile_prep(
        spec, {"in": describe(table.schema)}, arrow_schemas={"in": table.schema}
    )
    monkeypatch.setattr(
        registry, "resolve", lambda *a, **k: pytest.fail("preview resolved a secret")
    )
    result = previews.preview(compiled, {"in": dataset}, spec)
    expected = [
        hashlib.sha256(
            json.dumps(
                {"salt": "[preview-redacted]", "value": {"n": n}}, separators=(",", ":")
            ).encode()
        ).hexdigest()
        for n in (1, 2)
    ]
    assert [row["masked"] for row in result["rows"]] == expected
    assert "hash-salt" not in json.dumps(result)


def test_changed_sample_is_rejected_before_starting_child(source, monkeypatch):
    dataset, _ = source
    dataset.lineage_json["sample"]["sha256"] = "changed"
    monkeypatch.setattr(
        runner.subprocess, "Popen", lambda *a, **k: pytest.fail("unverified sample executed")
    )
    with pytest.raises(ValueError, match="^DATAPREP_SAMPLE_CHANGED$"):
        previews.preview(*prepared(source))


def child_script(tmp_path, monkeypatch, source):
    script = tmp_path / "isolated-test-child.py"
    script.write_text(source)
    monkeypatch.setattr(runner, "__file__", str(script))


def test_deadline_stops_leader_and_descendant_before_return(tmp_path, monkeypatch):
    child_script(
        tmp_path,
        monkeypatch,
        """
import os, pathlib, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
pathlib.Path('pids').write_text(str(os.getpid()) + ',' + str(child.pid))
time.sleep(60)
""",
    )
    started = time.monotonic()
    with pytest.raises(ValueError, match="^DATAPREP_PREVIEW_TIMEOUT$"):
        runner.run_isolated({}, tmp_path, memory_mb=512, timeout_s=0.5)
    assert time.monotonic() - started < 4
    leader, _ = map(int, (tmp_path / "pids").read_text().split(","))
    assert runner._active_members(leader) == []
    with pytest.raises(ChildProcessError):
        os.waitpid(leader, os.WNOHANG)


def test_caller_interruption_also_reaps_child(tmp_path, monkeypatch):
    child_script(tmp_path, monkeypatch, "import time; time.sleep(60)")
    original = subprocess.Popen
    children = []

    def popen(*args, **kwargs):
        child = original(*args, **kwargs)
        wait = child.wait
        calls = 0

        def interrupted(*a, **kw):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise KeyboardInterrupt
            return wait(*a, **kw)

        child.wait = interrupted
        children.append(child)
        return child

    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    with pytest.raises(KeyboardInterrupt):
        runner.run_isolated({}, tmp_path, memory_mb=512, timeout_s=10)
    assert children[0].returncode == -signal.SIGKILL
    assert runner._active_members(children[0].pid) == []


def test_child_has_no_application_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATABASE_SECRET", "never-inherited")
    child_script(
        tmp_path,
        monkeypatch,
        """
import json, os, pathlib
pathlib.Path('result.json').write_text(json.dumps({'rows': [], 'env': dict(os.environ)}))
""",
    )
    value = runner.run_isolated({}, tmp_path, memory_mb=512, timeout_s=3)
    assert "APP_DATABASE_SECRET" not in value["env"]
    assert "PYTHONPATH" not in value["env"]
    assert value["env"]["OPENBLAS_NUM_THREADS"] == "1"


def test_parent_rejects_oversized_ipc_before_loading(tmp_path, monkeypatch):
    child_script(
        tmp_path,
        monkeypatch,
        """
import pathlib
with pathlib.Path('result.json').open('wb') as out:
    out.truncate(33554433)
""",
    )
    with pytest.raises(ValueError, match="^DATAPREP_PREVIEW_OUTPUT_LIMIT$"):
        runner.run_isolated({}, tmp_path, memory_mb=512, timeout_s=3)


def test_limits_are_installed_before_native_imports(tmp_path):
    # A direct fresh process observes real limits; no inherited parent modules.
    code = """
import importlib.util, json, resource, sys
spec=importlib.util.spec_from_file_location('runner',sys.argv[1]); runner=importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
assert 'duckdb' not in sys.modules and 'pyarrow' not in sys.modules
runner._limits(512,5)
print(json.dumps({'as':resource.getrlimit(resource.RLIMIT_AS),'core':resource.getrlimit(resource.RLIMIT_CORE)}))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, runner.__file__],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    assert json.loads(result.stdout) == {"as": [1024 * 1024**2] * 2, "core": [0, 0]}


def test_unavailable_os_limit_fails_closed(monkeypatch):
    import resource

    def unsupported(*args):
        raise OSError("not supported")

    monkeypatch.setattr(resource, "setrlimit", unsupported)
    with pytest.raises(OSError):
        runner._limits(512, 5)


def test_child_refuses_execution_when_os_limit_installation_fails(tmp_path, monkeypatch):
    real_runner = runner.__file__
    child_script(
        tmp_path,
        monkeypatch,
        f"""
import importlib.util, resource
spec=importlib.util.spec_from_file_location('runner',{real_runner!r})
runner=importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
def unsupported(*args):
    raise OSError('unavailable')
resource.setrlimit=unsupported
runner._execute=lambda job: (_ for _ in ()).throw(AssertionError('must not execute'))
raise SystemExit(runner.main())
""",
    )
    with pytest.raises(ValueError, match="^DATAPREP_PREVIEW_ISOLATION_UNAVAILABLE$"):
        runner.run_isolated({}, tmp_path, memory_mb=512, timeout_s=3)
