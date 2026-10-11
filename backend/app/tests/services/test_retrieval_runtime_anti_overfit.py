from __future__ import annotations

from pathlib import Path


def test_runtime_retrieval_does_not_import_golden_cases():
    app_root = Path(__file__).resolve().parents[2]
    forbidden = (
        "retrieval_golden",
        "andritz_spl_dense",
        "expected_sources",
        "expected_evidence_terms",
        "spl_001",
    )
    excluded = {
        app_root / "services" / "rag" / "offline_eval.py",
        app_root / "services" / "rag" / "retrieval_golden.py",
    }

    offenders: list[tuple[str, str]] = []
    for path in app_root.rglob("*.py"):
        if "/tests/" in path.as_posix() or path in excluded:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in forbidden:
            if needle in text:
                offenders.append((str(path.relative_to(app_root)), needle))

    assert offenders == []
