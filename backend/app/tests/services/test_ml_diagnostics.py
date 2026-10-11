"""Real Skore findings and bounded optional development diagnostics."""

import time

import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyClassifier
from sklearn.tree import DecisionTreeClassifier
from skore import Check, EstimatorReport

from app.resources import ml_diagnostics as diagnostics
from app.services.tabular_ml import _write_manifest
from app.tests.services.test_ml_training import dataset, enabled, store, workspace  # noqa: F401


def noisy_report():
    rng = np.random.default_rng(9)
    x = pd.DataFrame(rng.normal(size=(600, 5)))
    y = pd.Series(rng.integers(0, 2, size=len(x)))
    return EstimatorReport(
        DecisionTreeClassifier(random_state=9),
        X_train=x.iloc[:400],
        y_train=y.iloc[:400],
        X_test=x.iloc[400:],
        y_test=y.iloc[400:],
        pos_label=1,
    )


def test_real_overfitting_and_costly_check_statuses():
    rows = {row["code"]: row for row in diagnostics.collect(noisy_report())}
    assert rows["SKD001"]["section"] == "issue"
    assert rows["SKD001"]["explanation"]
    assert rows["SKD009"]["section"] == "skipped"
    assert "ignored" in {row["section"] for row in rows.values()}
    assert "not_applicable" in {row["section"] for row in rows.values()}


def test_real_temporal_leakage_is_identified_with_its_feature():
    x = pd.DataFrame({"event_date": pd.date_range("2026-01-01", periods=60)})
    y = pd.Series([0, 1] * 30)
    report = EstimatorReport(
        DummyClassifier(),
        X_train=x.iloc[30:],
        y_train=y.iloc[30:],
        X_test=x.iloc[:30],
        y_test=y.iloc[:30],
        pos_label=1,
    )
    row = next(row for row in diagnostics.collect(report) if row["code"] == "SKD013")
    assert row["section"] == "issue"
    assert "event_date" in row["explanation"]


def test_failed_check_keeps_other_findings():
    class FailingCheck(Check):
        code = "HYU001"
        title = "Unavailable diagnostic"
        docs_url = None
        report_types = ["estimator"]
        slow = False

        def check_function(self, report):
            raise RuntimeError("controlled failure")

    report = noisy_report()
    report.checks.add([FailingCheck()])
    rows = {row["code"]: row for row in diagnostics.collect(report, selected=("SKD001", "HYU001"))}
    assert rows["HYU001"]["section"] == "error"
    assert rows["SKD001"]["section"] == "issue"


def test_actual_child_uses_only_given_training_rows_and_is_portable(tmp_path):
    rng = np.random.default_rng(8)
    x = pd.DataFrame({"x": rng.normal(size=200)})
    y = pd.Series(rng.integers(0, 2, size=200))
    model = DecisionTreeClassifier(random_state=8)
    answer = diagnostics.run(
        model,
        x,
        y,
        config={"enabled": True, "budget_s": 20},
        seed=8,
        task="classification",
        positive_class=1,
        scratch=tmp_path,
    )
    assert answer["status"] == "completed", answer
    assert answer["role"] == "development" and answer["served_model"] is False
    assert sum(answer["rows"].values()) == 200
    assert not hasattr(model, "tree_")
    assert not list(tmp_path.glob("diagnostics-*"))


def test_timeout_kills_child_and_preserves_fit(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    execute = diagnostics.subprocess.run

    def hanging(argv, **kwargs):
        Path(argv[3]).write_text(
            json.dumps(
                {
                    "status": "running",
                    "checks": [
                        {"code": "SKD001", "section": "passed"},
                        {"code": "SKD002", "section": "pending"},
                    ],
                }
            )
        )
        return execute([argv[0], "-c", "import time; time.sleep(10)"], **kwargs)

    monkeypatch.setattr(diagnostics.subprocess, "run", hanging)
    start = time.monotonic()
    answer = diagnostics.run(
        DecisionTreeClassifier(),
        pd.DataFrame({"x": range(100)}),
        pd.Series([0, 1] * 50),
        config={"enabled": True, "budget_s": 1},
        seed=0,
        task="classification",
        positive_class=1,
        scratch=tmp_path,
    )
    assert answer["status"] == "timed_out"
    assert [row["section"] for row in answer["checks"]] == ["passed", "skipped"]
    assert time.monotonic() - start < 2.5
    assert not list(tmp_path.glob("diagnostics-*"))


def test_activation_requires_runtime_and_workspace_allowlist(
    tmp_path, workspace, dataset, monkeypatch
):
    import json

    from app.core.config import settings
    from app.models.tabular import MLModel

    model = MLModel(
        workspace_id=workspace.id,
        dataset_id=dataset.id,
        params_json={},
        features=["x"],
        task="classification",
        target="churn",
    )
    monkeypatch.setattr(settings, "ml_skore_checks_enabled", True)
    monkeypatch.setattr(settings, "ml_skore_checks_workspaces", [])
    path = _write_manifest(tmp_path, model, tmp_path / "input.parquet", dataset=dataset)
    assert json.loads(path.read_text())["diagnostics"]["enabled"] is False
    monkeypatch.setattr(settings, "ml_skore_checks_workspaces", [workspace.id])
    path = _write_manifest(tmp_path, model, tmp_path / "input.parquet", dataset=dataset)
    assert json.loads(path.read_text())["diagnostics"]["enabled"] is True
    model.family = "forecasting"
    path = _write_manifest(tmp_path, model, tmp_path / "input.parquet", dataset=dataset)
    assert json.loads(path.read_text())["diagnostics"]["enabled"] is False


def test_supervisor_cancellation_reaches_the_diagnostic_child(tmp_path):
    import os
    import sys
    from pathlib import Path

    from app.services.recipe_executions import supervise_harness

    if not Path("/proc/self").exists():
        pytest.skip("This cancellation probe requires Linux procfs")

    backend = Path(__file__).resolve().parents[3]
    script = tmp_path / "cancel-probe.py"
    pid_file = tmp_path / "parent.pid"
    child_file = tmp_path / "child.pid"
    child_code = (
        "import os, time\nfrom pathlib import Path\n"
        f"Path({str(child_file)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    script.write_text(
        f"import os, sys\nsys.path.insert(0, {str(backend)!r})\n"
        f"from pathlib import Path\nPath({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "import pandas as pd\nfrom sklearn.dummy import DummyClassifier\n"
        "from app.resources import ml_diagnostics as diagnostics\n"
        "execute = diagnostics.subprocess.run\n"
        "def blocking_child(argv, **kwargs):\n"
        f"    return execute([sys.executable, '-c', {child_code!r}], **kwargs)\n"
        "diagnostics.subprocess.run = blocking_child\n"
        f"print(diagnostics.run(DummyClassifier(), pd.DataFrame({{'x': range(1000)}}), pd.Series([0, 1] * 500), "
        f"config={{'enabled': True, 'budget_s': 120}}, seed=0, task='classification', "
        f"positive_class=1, scratch={str(tmp_path)!r}), flush=True)\n"
    )
    children = []

    def cancel_when_child_starts():
        if not child_file.exists():
            return False
        parent = int(pid_file.read_text())
        children.append(int(child_file.read_text()))
        assert all(os.getpgid(child) == os.getpgid(parent) for child in children)
        return True

    answer = supervise_harness(
        [sys.executable, str(script)],
        venv_python=Path(sys.executable),
        scratch=tmp_path,
        timeout_s=45,
        memory_limit_mb=6144,
        cpu_limit_s=30,
        should_cancel=cancel_when_child_starts,
        extra_env={"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
    )
    assert answer.status == "cancelled", answer
    assert children
    for child in children:
        for _ in range(20):
            try:
                # A killed orphan may briefly remain a zombie until init reaps it.
                state = Path(f"/proc/{child}/stat").read_text().split(")", 1)[1].split()[0]
            except FileNotFoundError:
                break
            if state == "Z":
                break
            time.sleep(0.05)
        else:
            pytest.fail("Diagnostic process survived supervisor cancellation")
