"""Mutation tests for the Release A pre-mutation backup/capacity gate."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[4]
HELPER = ROOT / "scripts" / "agentium_release_a_preconditions.py"
LIVE_SHA = "a" * 40
RELEASE_SHA = "b" * 40
HOST = "agentium.papai.ai"
NOW = datetime(2026, 7, 22, 18, tzinfo=UTC)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_a_preconditions_test", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def module() -> ModuleType:
    return _load()


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _stamp(minutes: int) -> str:
    return (NOW - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _payload() -> dict[str, object]:
    mounts = [
        ("/", "/dev/sda1", 40 * 1024**3, 400 * 1024**3),
        ("/srv/agentium-data", "/dev/sdb", 64 * 1024**3, 500 * 1024**3),
        (
            "/home/ubuntu/omnirag/backend/data/secure_deposit",
            "/dev/sdc",
            64 * 1024**3,
            1200 * 1024**3,
        ),
    ]
    return {
        "profile": "agentium-release-a-preconditions-v1",
        "result": "passed",
        "environment": "production",
        "live_sha": LIVE_SHA,
        "release_a_sha": RELEASE_SHA,
        "hostname": HOST,
        "attested_at": _stamp(0),
        "off_vm_backups": [
            {
                "source_device": device,
                "provider": f"provider-{index}",
                "backup_id_sha256": _digest(f"backup-{index}"),
                "completed_at": _stamp(20 - index),
                "restore_check": {
                    "result": "passed",
                    "proof_sha256": _digest(f"restore-{index}"),
                    "completed_at": _stamp(10 - index),
                },
            }
            for index, device in enumerate(("/dev/sda1", "/dev/sdb", "/dev/sdc"))
        ],
        "capacity": [
            {
                "mountpoint": mountpoint,
                "source_device": device,
                "total_bytes": total,
                "available_bytes": max(minimum, total // 10) + 1024**3,
                "total_inodes": 1_000_000,
                "available_inodes": 200_000,
                "proof_sha256": _digest(f"capacity-{index}"),
                "measured_at": _stamp(5),
            }
            for index, (mountpoint, device, minimum, total) in enumerate(mounts)
        ],
    }


def _verify(module: ModuleType, payload: object) -> dict[str, object]:
    return module.verify(
        payload,
        live_sha=LIVE_SHA,
        release_a_sha=RELEASE_SHA,
        hostname=HOST,
        now=NOW,
    )


def test_exact_three_backup_restore_and_capacity_contract_passes(module) -> None:
    receipt = _verify(module, _payload())
    assert receipt["profile"] == "agentium-release-a-preconditions-receipt-v1"
    assert receipt["result"] == "passed"
    assert receipt["live_sha"] == LIVE_SHA
    assert receipt["release_a_sha"] == RELEASE_SHA


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["off_vm_backups"].pop(), "exactly three"),
        (
            lambda value: value["off_vm_backups"][1].update(source_device="/dev/sda1"),
            "incomplete or duplicated",
        ),
        (
            lambda value: value["off_vm_backups"][0]["restore_check"].update(
                result="waived"
            ),
            "restore rehearsal",
        ),
        (lambda value: value["capacity"].pop(), "exactly three"),
        (
            lambda value: value["capacity"][0].update(available_bytes=40 * 1024**3 - 1),
            "below",
        ),
        (
            lambda value: value["capacity"][2].update(source_device="/dev/sdb"),
            "source device differs",
        ),
        (
            lambda value: value["capacity"][2].update(
                available_bytes=value["capacity"][2]["total_bytes"] // 10 - 1
            ),
            "below",
        ),
        (
            lambda value: value["capacity"][1].update(available_inodes=99_999),
            "inode capacity",
        ),
        (
            lambda value: value["off_vm_backups"][1]["restore_check"].update(
                proof_sha256=value["off_vm_backups"][0]["restore_check"][
                    "proof_sha256"
                ]
            ),
            "restore proofs",
        ),
        (
            lambda value: value["capacity"][1].update(
                proof_sha256=value["capacity"][0]["proof_sha256"]
            ),
            "capacity proofs",
        ),
        (lambda value: value.update(extra=True), "invalid field set"),
    ],
)
def test_preconditions_fail_closed(module, mutation, message) -> None:
    payload = copy.deepcopy(_payload())
    mutation(payload)
    with pytest.raises(module.PreconditionsError, match=message):
        _verify(module, payload)


def test_private_file_loader_rejects_symlink_hardlink_and_open_mode(module, tmp_path) -> None:
    source = tmp_path / "preconditions.json"
    source.write_text(json.dumps(_payload()), encoding="utf-8")
    source.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(source)
    with pytest.raises(module.PreconditionsError, match="unsafe"):
        module._private_json(link)
    hard = tmp_path / "hard.json"
    os.link(source, hard)
    with pytest.raises(module.PreconditionsError, match="single-link"):
        module._private_json(source)
    hard.unlink()
    source.chmod(0o640)
    with pytest.raises(module.PreconditionsError, match="mode"):
        module._private_json(source)


def test_cli_receipt_is_exclusive_private_and_content_free(module, tmp_path) -> None:
    payload = _payload()
    payload["attested_at"] = datetime.now(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    for index, row in enumerate(payload["off_vm_backups"]):
        row["completed_at"] = (
            datetime.now(UTC) - timedelta(minutes=20 - index)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        row["restore_check"]["completed_at"] = (
            datetime.now(UTC) - timedelta(minutes=10 - index)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for row in payload["capacity"]:
        row["measured_at"] = (datetime.now(UTC) - timedelta(minutes=5)).replace(
            microsecond=0
        ).isoformat().replace("+00:00", "Z")
    source = tmp_path / "preconditions.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    source.chmod(0o600)
    output = tmp_path / "receipt.json"
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--preconditions",
            str(source),
            "--expected-live-sha",
            LIVE_SHA,
            "--expected-release-a-sha",
            RELEASE_SHA,
            "--expected-hostname",
            HOST,
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "passed\n"
    assert output.stat().st_mode & 0o777 == 0o600
    rendered = output.read_text()
    assert "provider-0" not in rendered
    assert _digest("backup-0") not in rendered
    second = subprocess.run(result.args, text=True, capture_output=True, check=False)
    assert second.returncode == 1
