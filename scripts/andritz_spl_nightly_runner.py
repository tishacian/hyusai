#!/usr/bin/env python3
"""Run controlled Andritz SPL indexing waves on the production VM.

This host-side runner intentionally shells out to the already deployed Docker
services. It executes one deterministic archive set at a time per folder. The
dry-run batch index is mutable, so the runner filters out files already marked
``promoted`` and executes the next exact archive path(s) with ``--archive``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COLLECTION = "andritz-notices-techniques-spl-pilot"
WORKSPACE = "andritz"
FOLDERS: list[tuple[str, str]] = [
    ("O", "canary"),
    ("S", "canary"),
    ("C", "moderate"),
    ("D", "moderate"),
    ("E", "moderate"),
    ("L", "moderate"),
    ("R", "moderate"),
    ("P", "moderate"),
    ("F", "heavy"),
    ("G", "heavy"),
    ("J", "heavy"),
    ("K", "heavy"),
    ("M", "heavy"),
    ("H", "final_heavy"),
    ("N", "final_heavy"),
]
FULL_GOLDEN_AFTER_GROUPS = {"moderate", "heavy", "final_heavy"}
POLL_SECONDS = 60
REPORT = Path("/tmp/andritz_spl_nightly_events.jsonl")
DUPLICATE_ONLY_MARKER = "were duplicates"
START_FOLDER = os.environ.get("START_FOLDER")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit(event: str, **payload: Any) -> None:
    row = {"ts": now(), "event": event, **payload}
    print(json.dumps(row, ensure_ascii=False), flush=True)
    with REPORT.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def run(cmd: list[str], *, timeout: int | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    if check and result.returncode != 0:
        emit("command_failed", cmd=cmd, returncode=result.returncode, output_tail=result.stdout[-4000:])
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(cmd)}")
    return result


def backend_python(*args: str, timeout: int | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["docker", "exec", "agentium-backend", "python", *args], timeout=timeout, check=check)


def dry_run(folder: str) -> dict[str, Any]:
    result = backend_python(
        "-m",
        "scripts.promote_spl_wave_v3",
        "--workspace",
        WORKSPACE,
        "--collection",
        COLLECTION,
        "--dry-run",
        "--folder",
        folder,
        timeout=1200,
    )
    return json.loads(result.stdout)


def eligible_plans(plan: dict[str, Any], skip_archives: set[str] | None = None) -> list[dict[str, Any]]:
    skip_archives = skip_archives or set()
    filtered: list[dict[str, Any]] = []
    for item in plan.get("plans") or []:
        archives = [
            archive
            for archive in item.get("archives") or []
            if archive.get("promotable")
            and archive.get("deposit_file_id")
            and str(archive.get("status") or "") != "promoted"
            and str(archive.get("filename") or "") not in skip_archives
        ]
        if not archives:
            continue
        current = dict(item)
        current["archives"] = archives
        current["archive_count"] = len(archives)
        current["total_documents"] = sum(int(archive.get("supported_files") or 0) for archive in archives)
        current["total_uncompressed_mb"] = round(
            sum(float(archive.get("supported_uncompressed_mb") or 0.0) for archive in archives),
            2,
        )
        filtered.append(current)
    return filtered


def summarize_eligible(plan: dict[str, Any], skip_archives: set[str] | None = None) -> dict[str, int]:
    plans = eligible_plans(plan, skip_archives)
    return {
        "remaining_batches": len(plans),
        "remaining_archives": sum(len(item.get("archives") or []) for item in plans),
        "remaining_documents": sum(int(item.get("total_documents") or 0) for item in plans),
    }


def execute_archives(archives: list[str]) -> tuple[str | None, dict[str, Any]]:
    cmd = [
        "-m",
        "scripts.promote_spl_wave_v3",
        "--workspace",
        WORKSPACE,
        "--collection",
        COLLECTION,
        "--execute",
        "--ocr",
        "auto",
    ]
    for archive in archives:
        cmd.extend(["--archive", archive])
    result = backend_python(
        *cmd,
        timeout=1800,
    )
    job_id = None
    match = re.search(r'"job_id"\s*:\s*"([^"]+)"', result.stdout)
    if match:
        job_id = match.group(1)
    return job_id, {"output_tail": result.stdout[-6000:]}


def execute_next_batch(
    folder: str, plan: dict[str, Any], skip_archives: set[str] | None = None
) -> tuple[str | None, dict[str, Any]]:
    next_plan = (eligible_plans(plan, skip_archives) or [{}])[0]
    archives = [str(item.get("filename") or "") for item in next_plan.get("archives") or []]
    archives = [item for item in archives if item]
    if not archives:
        return None, {"reason": "no_eligible_archives"}
    job_id, result = execute_archives(archives)
    result["archives"] = archives
    result["archive_count"] = len(archives)
    return job_id, result


def execute_next_mutable_batch(folder: str) -> tuple[str | None, dict[str, Any]]:
    result = backend_python(
        "-m",
        "scripts.promote_spl_wave_v3",
        "--workspace",
        WORKSPACE,
        "--collection",
        COLLECTION,
        "--execute",
        "--folder",
        folder,
        "--batch",
        "1",
        "--ocr",
        "auto",
        timeout=1800,
    )
    job_id = None
    match = re.search(r'"job_id"\s*:\s*"([^"]+)"', result.stdout)
    if match:
        job_id = match.group(1)
    return job_id, {"output_tail": result.stdout[-6000:]}


def sql(query: str) -> list[list[str]]:
    result = run(
        [
            "docker",
            "exec",
            "agentium-pg",
            "psql",
            "-U",
            "agentium",
            "-d",
            "agentium",
            "-t",
            "-A",
            "-F",
            "|",
            "-c",
            query,
        ],
        timeout=120,
    )
    rows: list[list[str]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(line.split("|"))
    return rows


def job_status(job_id: str) -> dict[str, Any]:
    rows = sql(
        "select status, coalesce(progress,0), "
        "coalesce(left(error,240),''), "
        "coalesce(extract(epoch from now()-created_at)::int,0) "
        f"from worker_jobs where id='{job_id}'"
    )
    if not rows:
        return {"status": "missing", "progress": 0, "error": "", "age_seconds": 0}
    row = rows[0]
    return {
        "status": row[0],
        "progress": int(row[1] or 0),
        "error": row[2],
        "age_seconds": int(row[3] or 0),
    }


def wait_job(job_id: str) -> dict[str, Any]:
    last_progress = None
    while True:
        status = job_status(job_id)
        if status["status"] in {"completed", "failed", "cancelled"}:
            emit("job_finished", job_id=job_id, **status)
            return status
        if status["progress"] != last_progress:
            emit("job_wait", job_id=job_id, **status)
            last_progress = status["progress"]
        time.sleep(POLL_SECONDS)


def collection_snapshot(folder: str | None = None) -> dict[str, Any]:
    rows = sql(
        "select c.status, coalesce(c.document_count,0), coalesce(c.chunk_count,0), "
        "count(s.*), coalesce(sum(coalesce(s.chunk_count,0)),0) "
        "from knowledge_collections c "
        "left join knowledge_collection_sources s on s.collection_id=c.id "
        f"where c.slug='{COLLECTION}' group by c.status,c.document_count,c.chunk_count"
    )
    source_rows = []
    if folder:
        source_rows = sql(
            "select count(*), coalesce(sum(coalesce(chunk_count,0)),0) "
            "from knowledge_collection_sources "
            f"where collection_id=(select id from knowledge_collections where slug='{COLLECTION}') "
            f"and source_metadata->>'source_deposit_path' like 'Notices_Techniques_SPL/{folder}/%'"
        )
    qdrant = {}
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:6333/collections/andritz__andritz-notices-techniques-spl-pilot",
            timeout=10,
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
            result = data.get("result") or {}
            qdrant = {
                "points_count": result.get("points_count"),
                "indexed_vectors_count": result.get("indexed_vectors_count"),
                "segments_count": result.get("segments_count"),
            }
    except Exception as exc:  # noqa: BLE001
        qdrant = {"error": str(exc)}
    out: dict[str, Any] = {"qdrant": qdrant}
    if rows:
        out.update(
            {
                "collection_status": rows[0][0],
                "document_count": int(rows[0][1] or 0),
                "chunk_count": int(rows[0][2] or 0),
                "source_rows": int(rows[0][3] or 0),
                "source_chunks": int(rows[0][4] or 0),
            }
        )
    if source_rows:
        out["folder_sources"] = int(source_rows[0][0] or 0)
        out["folder_chunks"] = int(source_rows[0][1] or 0)
    return out


def mini_smoke(folder: str) -> dict[str, Any]:
    output = f"/tmp/andritz_spl_smoke_{folder}.json"
    result = backend_python(
        "-m",
        "scripts.run_retrieval_golden_live",
        "--workspace",
        WORKSPACE,
        "--limit",
        "1",
        "--case-timeout",
        "90",
        "--output",
        output,
        timeout=180,
        check=False,
    )
    return {"returncode": result.returncode, "output_tail": result.stdout[-2000:]}


def full_golden(label: str) -> dict[str, Any]:
    output = f"/tmp/andritz_spl_golden_{label}.json"
    result = backend_python(
        "-m",
        "scripts.run_retrieval_golden_live",
        "--workspace",
        WORKSPACE,
        "--case-timeout",
        "90",
        "--output",
        output,
        timeout=3600,
        check=False,
    )
    return {"returncode": result.returncode, "output_tail": result.stdout[-3000:], "output": output}


def process_folder(folder: str, group: str) -> bool:
    emit("folder_start", folder=folder, group=group, snapshot=collection_snapshot(folder))
    batch_count = 0
    last_eligible_names: set[str] | None = None
    duplicate_only_archives: set[str] = set()
    while True:
        plan = dry_run(folder)
        summary = summarize_eligible(plan, duplicate_only_archives)
        remaining_batches = summary["remaining_batches"]
        remaining_archives = summary["remaining_archives"]
        remaining_documents = summary["remaining_documents"]
        eligible_names = {
            str(archive.get("filename") or "")
            for item in eligible_plans(plan, duplicate_only_archives)
            for archive in item.get("archives") or []
            if archive.get("filename")
        }
        emit(
            "folder_plan",
            folder=folder,
            remaining_batches=remaining_batches,
            remaining_archives=remaining_archives,
            remaining_documents=remaining_documents,
        )
        if remaining_batches <= 0 or remaining_documents <= 0:
            break
        if last_eligible_names is not None and eligible_names == last_eligible_names:
            emit(
                "folder_failed",
                folder=folder,
                reason="eligible_archives_did_not_advance",
                archives=sorted(eligible_names),
            )
            return False
        last_eligible_names = set(eligible_names)
        batch_count += 1
        first = (eligible_plans(plan, duplicate_only_archives) or [{}])[0]
        emit(
            "batch_start",
            folder=folder,
            batch=batch_count,
            wave_id=first.get("wave_id"),
            archive_count=first.get("archive_count"),
            documents=first.get("total_documents"),
            uncompressed_mb=first.get("total_uncompressed_mb"),
        )
        job_id, execution = execute_next_batch(folder, plan, duplicate_only_archives)
        emit("batch_queued", folder=folder, batch=batch_count, job_id=job_id, **execution)
        if not job_id:
            emit("folder_failed", folder=folder, reason="missing_job_id")
            return False
        status = wait_job(job_id)
        if status["status"] == "failed" and DUPLICATE_ONLY_MARKER in str(status.get("error") or ""):
            skipped = {str(item) for item in execution.get("archives") or [] if item}
            duplicate_only_archives.update(skipped)
            emit(
                "batch_duplicate_only",
                folder=folder,
                batch=batch_count,
                job_id=job_id,
                archives=sorted(skipped),
                status=status,
            )
            continue
        if status["status"] != "completed":
            emit("folder_failed", folder=folder, job_id=job_id, status=status)
            return False
    snapshot = collection_snapshot(folder)
    smoke = mini_smoke(folder)
    emit(
        "folder_done",
        folder=folder,
        group=group,
        batches=batch_count,
        duplicate_only_archives=sorted(duplicate_only_archives),
        snapshot=snapshot,
        smoke=smoke,
    )
    return True


def main() -> int:
    REPORT.touch(exist_ok=True)
    emit("runner_start", folders=FOLDERS, start_folder=START_FOLDER, snapshot=collection_snapshot())
    previous_group = None
    processed_groups: set[str] = set()
    started = START_FOLDER is None
    for folder, group in FOLDERS:
        if not started:
            if folder == START_FOLDER:
                started = True
            else:
                continue
        if previous_group and group != previous_group and previous_group in FULL_GOLDEN_AFTER_GROUPS:
            emit("golden_start", group=previous_group)
            emit("golden_done", group=previous_group, result=full_golden(previous_group))
            processed_groups.add(previous_group)
        previous_group = group
        ok = process_folder(folder, group)
        if not ok:
            emit("runner_stop", folder=folder, group=group, reason="folder_failed")
            return 2
    if previous_group and previous_group in FULL_GOLDEN_AFTER_GROUPS and previous_group not in processed_groups:
        emit("golden_start", group=previous_group)
        emit("golden_done", group=previous_group, result=full_golden(previous_group))
    emit("runner_done", snapshot=collection_snapshot())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
