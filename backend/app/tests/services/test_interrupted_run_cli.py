"""CLI defaults to preview and requires explicit, hashed operator evidence."""

import hashlib
import json
from unittest.mock import MagicMock

import pytest

from app.cli import reconcile_interrupted_run as cli

ARGS = [
    "--workspace-id",
    "00000000-0000-0000-0000-000000000001",
    "--run-id",
    "00000000-0000-0000-0000-000000000002",
    "--decision-id",
    "00000000-0000-0000-0000-000000000003",
    "--invocation-id",
    "00000000-0000-0000-0000-000000000004",
]


def test_default_preview_never_commits_or_reconciles(monkeypatch, capsys):
    manager = MagicMock()
    db = manager.__enter__.return_value
    monkeypatch.setattr(cli, "SessionLocal", lambda: manager)
    read = MagicMock(return_value={"applied": False, "state_sha256": "a" * 64})
    write = MagicMock(side_effect=AssertionError("Preview must never reconcile"))
    monkeypatch.setattr(cli, "preview", read)
    monkeypatch.setattr(cli, "reconcile", write)

    cli.main(ARGS)

    assert json.loads(capsys.readouterr().out)["applied"] is False
    read.assert_called_once()
    write.assert_not_called()
    db.commit.assert_not_called()


def test_apply_without_attestation_is_rejected_before_database_access(monkeypatch):
    database = MagicMock(side_effect=AssertionError("No database access without attestation"))
    monkeypatch.setattr(cli, "SessionLocal", database)
    with pytest.raises(SystemExit, match="explicit process-stop confirmation"):
        cli.main([*ARGS, "--apply"])
    database.assert_not_called()


def test_apply_hashes_evidence_and_commits_without_printing_its_contents(
    monkeypatch, tmp_path, capsys
):
    evidence = tmp_path / "process-stop.txt"
    content = b"Operator has checked the former API process is stopped."
    evidence.write_bytes(content)
    manager = MagicMock()
    db = manager.__enter__.return_value
    monkeypatch.setattr(cli, "SessionLocal", lambda: manager)
    write = MagicMock(
        return_value={"applied": True, "run_status": "failed", "external_effect_status": "unknown"}
    )
    monkeypatch.setattr(cli, "reconcile", write)

    cli.main(
        [
            *ARGS,
            "--apply",
            "--operator",
            "operator-id",
            "--confirm-process-stopped",
            "--expected-state-sha256",
            "a" * 64,
            "--evidence",
            str(evidence),
        ]
    )

    assert write.call_args.kwargs["evidence_sha256"] == hashlib.sha256(content).hexdigest()
    assert write.call_args.kwargs["evidence_ref"] == "process-stop.txt"
    assert write.call_args.kwargs["confirm_process_stopped"] is True
    db.commit.assert_called_once()
    output = capsys.readouterr().out
    assert content.decode() not in output
    assert json.loads(output)["external_effect_status"] == "unknown"
