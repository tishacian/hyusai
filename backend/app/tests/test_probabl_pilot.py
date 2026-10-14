"""Pilot guardrails: no final-test tuning, honest budgets, real offline boundary."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import platform
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "probabl_pilot_test_module", ROOT / "backend/app/resources/probabl_pilot.py"
)
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)

# The synthetic generators go through libm and BLAS, whose last bits differ by
# platform: the contract's fingerprints were frozen on the Linux x86-64 runtime.
frozen_platform = pytest.mark.skipif(
    (sys.platform, platform.machine()) != ("linux", "x86_64"),
    reason="dataset fingerprints are frozen on Linux x86-64",
)
# The bounded runner measures through /proc and blocks the network with seccomp.
linux_sandbox = pytest.mark.skipif(
    sys.platform != "linux", reason="the pilot sandbox requires Linux procfs and seccomp"
)


@pytest.fixture(scope="module")
def contract():
    return json.loads((ROOT / "config/ml/probabl-pilot.v1.json").read_text())


@frozen_platform
def test_contract_hashes_and_final_reserve_are_disjoint(contract):
    pilot.validate_contract(contract)
    for task in contract["tasks"]:
        _, y = pilot.dataset(task)
        splits = pilot.partitions(task, contract, y)
        final = set(splits["final"]["validation"])
        for name, split in splits.items():
            assert not set(split["train"]) & set(split["validation"])
            if name != "final":
                assert not final & (set(split["train"]) | set(split["validation"]))


@pytest.mark.parametrize("alteration", ["fingerprint", "temporal", "threads", "business"])
def test_changed_protocol_is_rejected(contract, alteration):
    changed = copy.deepcopy(contract)
    if alteration == "fingerprint":
        changed["tasks"][0]["sha256"] = "0" * 64
    elif alteration == "temporal":
        changed["partition"]["strategy"] = "temporal"
    elif alteration == "threads":
        changed["budgets"]["threads"] = 8
    else:
        changed["decision"]["business_value_status"] = "proven"
    with pytest.raises(ValueError):
        pilot.validate_contract(changed)


def test_schedule_is_balanced_and_missing_challenger_does_not_open_final(contract):
    schedule = pilot.balanced_schedule(contract)
    assert len(schedule) == 108
    assert len({case["candidate"] for case in schedule[:6]}) == 6
    assert {schedule[index * 6]["candidate"] for index in range(6)} == set(contract["candidates"])
    selected = pilot.select_candidates(contract, [])
    assert all(not candidates for candidates in selected.values())
    assert pilot.balanced_schedule(contract, "final", selected) == []


def test_selection_requires_three_matching_development_partitions(contract):
    rows = [
        {
            "task": contract["tasks"][0]["id"],
            "candidate": candidate,
            "status": "evaluated",
            "split": f"dev-{split}",
            "split_sha256": contract["tasks"][0]["partition_sha256"][f"dev-{split}"],
            "metric_value": 0.8,
            "resources": {"cpu_seconds": 1},
        }
        for candidate in ("dummy", "sklearn_linear", "tabicl_plain")
        for split in range(3)
    ]
    assert pilot.select_candidates(contract, rows)[contract["tasks"][0]["id"]] == [
        "dummy",
        "sklearn_linear",
        "tabicl_plain",
    ]
    rows[-1]["split"] = "final"
    assert not pilot.select_candidates(contract, rows)[contract["tasks"][0]["id"]]


@frozen_platform
def test_revision_two_preserves_reserve_and_excludes_uncached_regression_even_if_it_passes(
    contract,
):
    revised = json.loads((ROOT / "config/ml/probabl-pilot.v2.json").read_text())
    pilot.validate_contract(revised)
    for key in ("partition", "tasks", "decision", "budgets", "search", "serving", "runtime"):
        assert revised[key] == contract[key]
    schedule = pilot.balanced_schedule(revised)
    assert len(schedule) == 108
    assert (
        sum(bool(pilot.exclusion_reason(revised, r["task"], r["candidate"])) for r in schedule) == 9
    )
    task = next(task for task in revised["tasks"] if task["kind"] == "regression")
    rows = [
        {
            "task": task["id"],
            "candidate": candidate,
            "status": "evaluated",
            "split": f"dev-{split}",
            "split_sha256": task["partition_sha256"][f"dev-{split}"],
            # An excluded profile winning every rerun still cannot be nominated.
            "metric_value": 0.0 if candidate == "tabicl_plain" else 1.0,
            "resources": {"cpu_seconds": 1},
        }
        for candidate in ("dummy", "sklearn_linear", "tabicl_plain", "tabicl_cache")
        for split in range(3)
    ]
    assert pilot.select_candidates(revised, rows)[task["id"]] == [
        "dummy",
        "sklearn_linear",
        "tabicl_cache",
    ]
    assert not pilot.select_candidates(
        revised, [r for r in rows if r["candidate"] != "tabicl_cache"]
    )[task["id"]]
    revised["exclusions"].pop()
    with pytest.raises(ValueError, match="exclude every"):
        pilot.validate_contract(revised)


def test_paired_interval_respects_metric_direction_and_sample_support():
    truth = list(range(100))
    baseline = [value + 2 for value in truth]
    challenger = [value + 1 for value in truth]
    interval = pilot.paired_interval(
        "regression", truth, baseline, challenger, seed=42, repetitions=30
    )
    assert interval["gain"] == 0.5 and interval["lower"] == 0.5
    assert (
        pilot.paired_interval("classification", [0, 1], [0, 1], [0, 1], seed=42)["status"]
        == "insufficient_independent_units"
    )


def test_full_cycle_includes_startup_and_children_without_double_counting(contract):
    timings = {"fit": {"cpu_seconds": 3.0}, "export_reload": {"cpu_seconds": 2.0}}
    serving = {
        "1": [{"cpu_seconds": 1.0}],
        "100": [{"cpu_seconds": 2.0}],
        "1000": [{"cpu_seconds": 3.0}],
    }
    projection = pilot.project_full_cycle_cpu(20.0, timings, serving, contract)
    # Total 20 includes phases 5, disposable probes 6, and startup/other 9.
    assert projection["startup_imports_and_unattributed_cpu_seconds"] == 9.0
    assert projection["projected_cpu_seconds"] == 20.0 - 6.0 + 100 * 2.0


@linux_sandbox
def test_seccomp_blocks_real_native_network_syscalls():
    code = f"""
import sys, socket, ctypes, errno
sys.path.insert(0, {str(ROOT / "backend/app/resources")!r})
from probabl_pilot import block_network
assert block_network().startswith('linux_seccomp')
connection = socket.socket()
try:
    connection.connect(('127.0.0.1', 9))
except PermissionError:
    pass
else:
    raise AssertionError('connect was not denied')
native = ctypes.CDLL(None, use_errno=True)
assert native.sendto(connection.fileno(), b'x', 1, 0, None, 0) == -1
assert ctypes.get_errno() == errno.EPERM
"""
    measured = pilot.run_bounded(
        [sys.executable, "-c", code],
        env=os.environ.copy(),
        wall_seconds=10,
        cpu_seconds=10,
        memory_bytes=1024**3,
    )
    assert measured["exit_code"] == 0, measured


@linux_sandbox
def test_cpu_budget_counts_children_and_timeout_kills_process_group(tmp_path):
    child = "import time; end=time.process_time()+0.25\nwhile time.process_time()<end: pass"
    code = f"import subprocess,sys; subprocess.run([sys.executable,'-c',{child!r}],check=True)"
    measured = pilot.run_bounded(
        [sys.executable, "-c", code],
        env=os.environ.copy(),
        wall_seconds=5,
        cpu_seconds=5,
        memory_bytes=1024**3,
    )
    assert measured["exit_code"] == 0
    assert measured["cpu_seconds"] >= 0.25
    measured = pilot.run_bounded(
        [sys.executable, "-c", "while True: pass"],
        env=os.environ.copy(),
        wall_seconds=5,
        cpu_seconds=0.1,
        memory_bytes=1024**3,
    )
    assert measured["stopped_by"] == "campaign_cpu_budget"
    child_pid = tmp_path / "child.pid"
    code = f"import subprocess,sys,time; child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); open({str(child_pid)!r},'w').write(str(child.pid)); time.sleep(30)"
    measured = pilot.run_bounded(
        [sys.executable, "-c", code],
        env=os.environ.copy(),
        wall_seconds=2,
        cpu_seconds=10,
        memory_bytes=1024**3,
    )
    assert measured["stopped_by"] == "case_wall_budget"
    stat = Path("/proc") / child_pid.read_text() / "stat"
    assert not stat.exists() or stat.read_text().rsplit(")", 1)[1].split()[0] == "Z"


@linux_sandbox
def test_return_waits_until_a_delayed_descendant_kill_has_taken_effect(tmp_path, monkeypatch):
    """Signal delivery and waiting for the group leader are not an exit barrier."""
    child_pid = tmp_path / "child.pid"
    code = f"import subprocess,sys,time; child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); open({str(child_pid)!r},'w').write(str(child.pid)); time.sleep(30)"
    real_killpg = os.killpg
    timers = []
    groups = []
    delivered = threading.Event()

    def delayed_killpg(group, sig):
        groups.append(group)
        try:
            os.kill(group, sig)  # The leader dies immediately; the descendant remains alive.
        except ProcessLookupError:
            pass
        if timers:
            return

        def kill_descendant():
            delivered.set()
            try:
                real_killpg(group, sig)
            except ProcessLookupError:
                pass

        timer = threading.Timer(0.15, kill_descendant)
        timers.append(timer)
        timer.start()

    monkeypatch.setattr(pilot.os, "killpg", delayed_killpg)
    try:
        measured = pilot.run_bounded(
            [sys.executable, "-c", code],
            env=os.environ.copy(),
            wall_seconds=2,
            cpu_seconds=10,
            memory_bytes=1024**3,
        )
        assert measured["stopped_by"] == "case_wall_budget"
        assert delivered.is_set(), "run_bounded returned while its descendant was still alive"
        try:
            state = (
                (Path("/proc") / child_pid.read_text() / "stat")
                .read_text()
                .rsplit(")", 1)[1]
                .split()[0]
            )
        except FileNotFoundError:
            state = None
        assert state in {None, "Z", "X"}
    finally:
        for timer in timers:
            timer.join(timeout=2)
        for group in set(groups):
            try:
                real_killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass


@linux_sandbox
def test_normal_leader_exit_also_waits_for_orphaned_descendants(tmp_path):
    child_pid = tmp_path / "child.pid"
    code = f"import subprocess,sys; child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); open({str(child_pid)!r},'w').write(str(child.pid))"
    measured = pilot.run_bounded(
        [sys.executable, "-c", code],
        env=os.environ.copy(),
        wall_seconds=5,
        cpu_seconds=5,
        memory_bytes=1024**3,
    )
    assert measured["exit_code"] == 0 and measured["stopped_by"] is None
    try:
        state = (
            (Path("/proc") / child_pid.read_text() / "stat")
            .read_text()
            .rsplit(")", 1)[1]
            .split()[0]
        )
    except FileNotFoundError:
        state = None
    assert state in {None, "Z", "X"}


@linux_sandbox
@pytest.mark.parametrize("leader_exits", [False, True])
def test_unconfirmed_process_group_cleanup_is_bounded_and_raises(
    tmp_path, monkeypatch, leader_exits
):
    child_pid = tmp_path / "child.pid"
    if leader_exits:
        code = f"import subprocess,sys; child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); open({str(child_pid)!r},'w').write(str(child.pid))"
    else:
        code = "import time; time.sleep(30)"
    process = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
    real_killpg = os.killpg
    monkeypatch.setattr(pilot.os, "killpg", lambda *_: None)
    try:
        if leader_exits:
            process.wait(timeout=5)
            assert child_pid.exists()
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="PROCESS_GROUP_CLEANUP_TIMEOUT"):
            pilot._terminate_process_group(process, timeout_s=0.05)
        assert time.monotonic() - started < 1
    finally:
        try:
            real_killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def test_process_group_cleanup_does_not_read_an_unrelated_inaccessible_stat(tmp_path, monkeypatch):
    foreign = tmp_path / "101"
    own = tmp_path / "102"
    foreign.mkdir()
    own.mkdir()
    (own / "stat").write_text("102 (worker) S 1 777")
    real_read_text = Path.read_text

    def restricted_read_text(path, *args, **kwargs):
        if path == foreign / "stat":
            pytest.fail("Cleanup must not inspect an unrelated process's restricted stat")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(pilot, "Path", lambda _: tmp_path)
    monkeypatch.setattr(pilot.os, "getpgid", lambda pid: {101: 999, 102: 777}[pid])
    monkeypatch.setattr(Path, "read_text", restricted_read_text)
    assert pilot._active_process_group_members(777) == [102]


def test_process_group_cleanup_fails_if_its_own_member_is_inaccessible(tmp_path, monkeypatch):
    own = tmp_path / "102"
    own.mkdir()

    def restricted_read_text(*args, **kwargs):
        raise PermissionError("stat is inaccessible")

    monkeypatch.setattr(pilot, "Path", lambda _: tmp_path)
    monkeypatch.setattr(pilot.os, "getpgid", lambda _: 777)
    monkeypatch.setattr(Path, "read_text", restricted_read_text)
    with pytest.raises(RuntimeError, match="PROCESS_GROUP_CLEANUP_UNVERIFIED"):
        pilot._active_process_group_members(777)


def test_process_group_cleanup_rechecks_membership_after_reading_stat(tmp_path, monkeypatch):
    own = tmp_path / "102"
    own.mkdir()
    (own / "stat").write_text("102 (replacement) S 1 999")
    monkeypatch.setattr(pilot, "Path", lambda _: tmp_path)
    monkeypatch.setattr(pilot.os, "getpgid", lambda _: 777)
    assert pilot._active_process_group_members(777) == []


def test_summary_never_averages_incomparable_metrics_or_claims_business_value(contract):
    summary = pilot.summarize(contract, [])
    assert summary["aggregate_metric"] is None
    assert summary["business_value"] == "not_evaluated"
    assert summary["energy"] == "not_measured"
    assert summary["adoption"] == "experimental"
    assert all(task["status"] == "not_evaluated" for task in summary["tasks"])
