#!/usr/bin/env python3
"""Disposable PostgreSQL qualification of authorized activity series.

Run from backend with ACTIVITY_POSTGRES_URL set, e.g.::

    python scripts/qualify_activity_series.py --output /tmp/activity-series.json

Creates and drops only a random ``series_qualification_<uuid>`` schema. The
provided database is never reset. The corpus uses real native permissions: two
members, public Runs, private chat Runs, invocation children, and compute/job
ownership. No permission function is monkeypatched. Timings include native IAM
and aggregation, but exclude HTTP/network and JSON encoding. Ten threads model
concurrent sync handlers in one API process (not ten independent processes).
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from math import ceil
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, event, insert, text
from sqlalchemy.orm import Session

import app.models  # noqa: F401 — register all FK targets
from app.core.config import settings
from app.db.base import Base
from app.models.activity import Activity, measured_columns
from app.models.compute_run import ComputeRun
from app.models.run import Run, SkillInvocation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.models.workspace_job import WorkspaceJob
from app.services.activity_observability.series import activity_series

START = datetime(2026, 1, 1)
UNTIL = START + timedelta(days=30)
WORKSPACE = "series-qualification"
USERS = ("series-reader-a", "series-reader-b")


def rss_bytes():
    """Current resident set, not the seed phase's historical high-water mark."""
    statm = Path("/proc/self/statm")
    if statm.exists():
        return int(statm.read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    import psutil  # macOS/BSD workstations: same current-RSS meaning, no /proc

    return psutil.Process().memory_info().rss


def _first_line(path, prefix):
    file = Path(path)
    if not file.exists():
        return None
    return next((row for row in file.read_text().splitlines() if row.startswith(prefix)), None)


def _sysctl(name):
    try:
        return subprocess.check_output(["sysctl", "-n", name], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def percentile(values, quantile):
    return sorted(values)[ceil(len(values) * quantile) - 1] if values else None


def seed(engine, count):
    runs_count = count // 10
    invocation_count = count * 8 // 10
    compute_count = count // 20
    job_count = count - runs_count - invocation_count - compute_count
    expected = {user: Counter() for user in USERS}

    def owner(index):
        return USERS[index % 2]

    def run_readable(index, user):
        return index % 4 != 3 or owner(index) == user

    def stamp(index):
        return START + timedelta(seconds=(index * 2591) % (30 * 86400 - 600))

    def projection(kind, index, native_id, run_index, native_owner):
        created = stamp(index)
        snapshot = {
            "finished_at": (created + timedelta(seconds=60)).isoformat() + "Z",
            "measurements": {"duration_ms": (index % 1000) + 1},
        }
        return dict(
            id=f"{kind[:2]}-{index:012d}",
            workspace_id=WORKSPACE,
            kind=kind,
            native_id=native_id,
            run_id=f"run-{run_index:012d}" if run_index is not None else None,
            owner_id=native_owner,
            system_id=None,
            parent_activity_id=None,
            status="succeeded",
            native_status="completed",
            version=1,
            snapshot=snapshot,
            # Core inserts bypass the ORM hook; derive like the projection does.
            **measured_columns(snapshot),
            snapshot_digest="0" * 64,
            origin="observed",
            created_at=created,
            updated_at=created + timedelta(seconds=60),
        )

    def bulk(connection, model, rows):
        for offset in range(0, len(rows), 1000):
            connection.execute(insert(model.__table__), rows[offset : offset + 1000])

    with engine.begin() as connection:
        connection.execute(
            insert(Workspace), dict(id=WORKSPACE, name="Series qualification", slug=WORKSPACE)
        )
        connection.execute(
            insert(User),
            [dict(id=user, username=user, role="user", is_active=True) for user in USERS],
        )
        connection.execute(
            insert(WorkspaceMember),
            [dict(workspace_id=WORKSPACE, user_id=user, role="member") for user in USERS],
        )
        connection.execute(
            insert(WorkspaceIAMConfig),
            dict(
                workspace_id=WORKSPACE,
                capability_overrides={
                    "authorization_v2": {"policy_version": 2, "default_mode": "compat"}
                },
                role_flags={},
            ),
        )
        native, projected = [], []
        for i in range(runs_count):
            identifier = f"run-{i:012d}"
            native.append(
                dict(
                    id=identifier,
                    workspace_id=WORKSPACE,
                    initiated_by_user_id=owner(i),
                    trigger="chat_agentic" if i % 4 == 3 else "manual",
                    status="completed",
                    started_at=stamp(i),
                    completed_at=stamp(i) + timedelta(seconds=60),
                    duration_ms=i % 1000 + 1,
                )
            )
            projected.append(projection("run", i, identifier, i, owner(i)))
            for user in USERS:
                expected[user]["run"] += run_readable(i, user)
        bulk(connection, Run, native)
        bulk(connection, Activity, projected)
        native, projected = [], []
        for i in range(invocation_count):
            r = i % runs_count
            identifier = f"inv-{i:012d}"
            native.append(
                dict(
                    id=identifier,
                    run_id=f"run-{r:012d}",
                    status="completed",
                    started_at=stamp(i),
                    completed_at=stamp(i) + timedelta(seconds=60),
                    cost=0.1,
                    provider_cost_usd=0.1,
                    cost_measured=True,
                    metrics={"cost_evidence": {"state": "measured", "currency": "USD"}},
                )
            )
            projected.append(projection("skill_invocation", i, identifier, r, owner(r)))
            for user in USERS:
                expected[user]["skill_invocation"] += run_readable(r, user)
        bulk(connection, SkillInvocation, native)
        bulk(connection, Activity, projected)
        for kind, model, size in (
            ("compute_run", ComputeRun, compute_count),
            ("workspace_job", WorkspaceJob, job_count),
        ):
            native, projected = [], []
            for i in range(size):
                r = i % runs_count
                identifier = f"{kind[:2]}-{i:012d}"
                if kind == "compute_run":
                    row = dict(
                        id=identifier,
                        workspace_id=WORKSPACE,
                        run_id=f"run-{r:012d}",
                        user_id=owner(i),
                        kind="dataops",
                        operation="prepare",
                        status="succeeded",
                        deadline_at=UNTIL,
                        created_at=stamp(i),
                        started_at=stamp(i),
                        finished_at=stamp(i) + timedelta(seconds=60),
                        cost_usd=0.2,
                    )
                else:
                    row = dict(
                        id=identifier,
                        workspace_id=WORKSPACE,
                        run_id=f"run-{r:012d}",
                        created_by_user_id=owner(i),
                        kind="qualification",
                        title="Qualification",
                        status="completed",
                        created_at=stamp(i),
                        started_at=stamp(i),
                        completed_at=stamp(i) + timedelta(seconds=60),
                    )
                native.append(row)
                projected.append(projection(kind, i, identifier, r, owner(i)))
                for user in USERS:
                    expected[user][kind] += run_readable(r, user) and owner(i) == user
            bulk(connection, model, native)
            bulk(connection, Activity, projected)
    return {user: dict(counts) for user, counts in expected.items()}


def qualify(engine, args, expected):
    local = threading.local()
    queries = Counter()
    examples = {}
    query_lock = threading.Lock()

    @event.listens_for(engine, "before_cursor_execute")
    def count_sql(connection, cursor, statement, parameters, context, executemany):
        if getattr(local, "reader", False):
            local.sql += 1
            # No SQL parameter values are retained. Cap examples, normalize the
            # varying number of IN placeholders to keep the report readable.
            table = re.search(r"\bFROM\s+([A-Za-z0-9_.]+)", statement, re.IGNORECASE)
            category = table.group(1) if table else statement.split()[0]
            with query_lock:
                queries[category] += 1
                if category not in examples:
                    examples[category] = " ".join(statement.split())[:1400]

    failures, writes, writer_errors = [], [], []
    stop, started = threading.Event(), threading.Barrier(args.readers + 1)
    peak = [rss_bytes()]
    baseline = peak[0]
    lock_wait_samples = []

    def monitor():
        with engine.connect() as connection:
            while not stop.wait(0.02):
                peak[0] = max(peak[0], rss_bytes())
                # Observe actual PostgreSQL lock waits attributed to this
                # benchmark's writer, independently from latency alone.
                if len(lock_wait_samples) < 50:
                    rows = connection.execute(
                        text(
                            "SELECT wait_event_type, wait_event FROM pg_stat_activity WHERE application_name = 'series-qualification-writer' AND wait_event_type = 'Lock'"
                        )
                    ).all()
                    lock_wait_samples.extend([list(row) for row in rows])
                    connection.commit()

    def writer():
        counter = 0
        while not stop.is_set():
            began = time.perf_counter()
            try:
                with Session(engine) as db:
                    db.execute(text("SET LOCAL application_name = 'series-qualification-writer'"))
                    db.execute(text("SET LOCAL lock_timeout = '200ms'"))
                    # Outside the fixed observation window. Uses the real
                    # native ORM/observer commit path while readers aggregate.
                    db.add(
                        Run(
                            id=f"writer-{counter:012d}",
                            workspace_id=WORKSPACE,
                            initiated_by_user_id=USERS[0],
                            started_at=UNTIL + timedelta(days=1),
                        )
                    )
                    db.commit()
                writes.append(time.perf_counter() - began)
            except Exception as exc:
                writer_errors.append(type(exc).__name__ + ": " + str(exc)[:200])
                break
            counter += 1
            stop.wait(0.05)

    def read(index):
        user_id = USERS[index % 2]
        local.reader, local.sql = True, 0
        started.wait()
        began = time.perf_counter()
        try:
            with engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection:
                with Session(connection) as db:
                    workspace = db.get(Workspace, WORKSPACE)
                    user = db.get(User, user_id)
                    result = activity_series(
                        db,
                        workspace,
                        user,
                        start=START,
                        until=UNTIL,
                        bucket="day",
                        metric=args.metric,
                        kind="skill_invocation" if args.metric == "cost" else None,
                        time_basis="finished" if args.metric == "cost" else "created",
                    )
                    wanted = expected[user_id]
                    wanted = (
                        {"skill_invocation": wanted["skill_invocation"]}
                        if args.metric == "cost"
                        else wanted
                    )
                    if result["totals"]["by_kind"] != wanted:
                        raise AssertionError(
                            f"Authorized population mismatch: {result['totals']['by_kind']} != {wanted}"
                        )
                    return dict(
                        reader=index,
                        user=user_id,
                        elapsed_s=time.perf_counter() - began,
                        sql_queries=local.sql,
                        authorized_total=result["totals"]["total"],
                    )
        finally:
            local.reader = False

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    writer_thread = threading.Thread(target=writer, daemon=True)
    monitor_thread.start()
    writer_thread.start()
    try:
        with ThreadPoolExecutor(max_workers=args.readers) as pool:
            futures = [pool.submit(read, i) for i in range(args.readers)]
            started.wait()
            results = []
            for future in futures:
                try:
                    results.append(future.result())
                except Exception as exc:
                    failures.append(type(exc).__name__ + ": " + str(exc)[:500])
    finally:
        stop.set()
        monitor_thread.join(5)
        writer_thread.join(5)
        event.remove(engine, "before_cursor_execute", count_sql)
    elapsed = [row["elapsed_s"] for row in results]
    delta = max(0, peak[0] - baseline) / 1024**2
    return dict(
        readers=results,
        errors=failures,
        series_p95_s=percentile(elapsed, 0.95),
        rss_baseline_mib=baseline / 1024**2,
        rss_peak_mib=peak[0] / 1024**2,
        rss_delta_all_readers_mib=delta,
        memory_method="Shared-process RSS increase for all simultaneous readers after seed and GC (allocator arenas may be reused); conservative per-request upper bound, sampled every 20ms",
        timing_scope="Service + native authorization + aggregation; excludes HTTP transport and JSON encoding",
        sql_query_counts=dict(queries),
        sql_examples=examples,
        writes=dict(
            completed=len(writes),
            p95_s=percentile(writes, 0.95),
            max_s=max(writes, default=None),
            errors=writer_errors,
            postgres_lock_wait_samples=lock_wait_samples,
        ),
        pass_criteria=dict(
            correct_authorized_totals=not failures and len(results) == args.readers,
            series_p95_le_2s=bool(elapsed) and percentile(elapsed, 0.95) <= 2,
            rss_delta_le_256mib=delta <= 256,
            writer_not_blocked=bool(writes) and not writer_errors and not lock_wait_samples,
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activities", type=int, default=100_000)
    parser.add_argument("--readers", type=int, default=10)
    parser.add_argument("--metric", choices=("activity", "cost"), default="activity")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.activities < 100 or args.activities % 20 or not 1 <= args.readers <= 20:
        parser.error("activities must be >=100 and divisible by 20; readers must be 1..20")
    url = os.environ.get("ACTIVITY_POSTGRES_URL")
    if not url or not url.startswith("postgresql"):
        parser.error("ACTIVITY_POSTGRES_URL must identify a disposable-capable PostgreSQL database")
    schema = "series_qualification_" + uuid4().hex
    admin = create_engine(url)
    engine = None
    previous = settings.activity_observability_enabled
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            pg_version = connection.execute(text("SHOW server_version")).scalar_one()
        engine = create_engine(
            url,
            pool_size=args.readers + 3,
            max_overflow=0,
            connect_args={
                "options": f"-csearch_path={schema} -clock_timeout=5000 -cstatement_timeout=120000"
            },
        )
        settings.activity_observability_enabled = False
        Base.metadata.create_all(engine)
        expected = seed(engine, args.activities)
        with engine.begin() as connection:
            connection.execute(text("ANALYZE"))
        settings.activity_observability_enabled = True
        # Ensure the observer hook is installed as in the API host.
        from app.services.activity_observability.observer import install_observers

        install_observers()
        gc.collect()
        report = dict(
            schema_version=1,
            timestamp=datetime.utcnow().isoformat() + "Z",
            corpus=dict(
                activities=args.activities,
                days=30,
                status_distribution={"succeeded": args.activities},
                coverage_exclusions=[
                    "HTTP transport",
                    "SSE clients",
                    "service windows and asset-protected delivery receipts (native fallback)",
                    "large native payloads",
                    "enforcement attestations and strict-mode throughput",
                ],
                expected_by_reader=expected,
                authorization="Native private-chat and compute/job ownership; authorization_v2 COMPAT uses the tested SQL translation, while SHADOW/ENFORCE and unsupported cases retain native authorization",
                distribution="10% Runs, 80% SkillInvocations, 5% ComputeRuns, 5% WorkspaceJobs",
            ),
            host=dict(
                platform=platform.platform(),
                python=platform.python_version(),
                cpu_count=os.cpu_count(),
                affinity_count=len(os.sched_getaffinity(0))
                if hasattr(os, "sched_getaffinity")
                else os.cpu_count(),
                cpu_model=(
                    (_first_line("/proc/cpuinfo", "model name") or "").split(":", 1)[-1].strip()
                    or _sysctl("machdep.cpu.brand_string")
                    or "unknown"
                ),
                cgroup_cpu_max=Path("/sys/fs/cgroup/cpu.max").read_text().strip()
                if Path("/sys/fs/cgroup/cpu.max").exists()
                else None,
                cgroup_memory_max=Path("/sys/fs/cgroup/memory.max").read_text().strip()
                if Path("/sys/fs/cgroup/memory.max").exists()
                else None,
                postgres=pg_version,
                mem_total_kib=_first_line("/proc/meminfo", "MemTotal:")
                or f"hw.memsize: {int(_sysctl('hw.memsize') or 0) // 1024} kB",
            ),
            source=dict(
                git_head=subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], text=True, cwd=Path(__file__).resolve().parents[2]
                ).strip(),
                file_sha256={
                    name: hashlib.sha256(
                        (Path(__file__).resolve().parents[1] / name).read_bytes()
                    ).hexdigest()
                    for name in (
                        "app/services/activity_observability/series.py",
                        "app/services/activity_observability/series_sql.py",
                        "app/services/activity_observability/queries.py",
                        "app/services/activity_observability/execution_metadata.py",
                        "app/api/v1/endpoints/workspace_jobs.py",
                        "app/services/run_access.py",
                        "scripts/qualify_activity_series.py",
                    )
                },
            ),
            invocation=dict(readers=args.readers, metric=args.metric),
            result=qualify(engine, args, expected),
        )
        serialized = json.dumps(report, indent=2, sort_keys=True)
        if args.output:
            args.output.write_text(serialized + "\n")
        print(serialized)
        return 0 if all(report["result"]["pass_criteria"].values()) else 1
    finally:
        settings.activity_observability_enabled = previous
        if engine is not None:
            engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
