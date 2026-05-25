#!/usr/bin/env python3
"""Standalone test of the SENTINEL-CI S3 action resolver.

Builds a minimal Workspace stub mirroring the production
``ensure_sentinel_ci_workspace`` settings (so the
``sentinel_ci_aya_security_v1`` pack is active), then exercises the 6 S3
phrases against ``resolve_action`` and prints a verdict table.

Run from the repo root so ``backend.app`` imports resolve:

    cd /Users/thib/Developer/PAPAI/omnirag/backend
    PYTHONPATH=$(pwd) python3 ../scripts/test_s3_resolver.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@dataclass
class _WorkspaceStub:
    id: str = "ws-sentinel-ci-stub"
    slug: str = "sentinel-ci"
    name: str = "SENTINEL-CI"
    settings: dict[str, Any] = field(default_factory=dict)


def _build_workspace() -> _WorkspaceStub:
    return _WorkspaceStub(
        settings={
            "actions": {
                "enabled_packs": [
                    "global_voice_v1",
                    "sentinel_ci_aya_v1",
                    "sentinel_ci_aya_security_v1",
                ],
                "confirmation_policy": "confirm_side_effects",
            },
            "voice_loop": {
                "command_packs": [
                    "global_voice_v1",
                    "sentinel_ci_aya_v1",
                    "sentinel_ci_aya_security_v1",
                ],
            },
            "capabilities": {
                "enabled": ["aya_voice_command"],
            },
        }
    )


PHRASES = [
    # Trame verbatim S3.1 -> S3.6 (carte de présentateur).
    ("S3.1", "AYA, montre-moi la posture sécuritaire du jour.", "aya.show_security_posture"),
    ("S3.2", "AYA, montre la pulsation sociale à Abidjan.", "aya.show_social_pulse"),
    ("S3.3", "AYA, d'où vient la rumeur frontière Nord ?", "aya.trace_rumor_origin"),
    ("S3.4", "AYA, montre les mouvements de troupes au Sahel.", "aya.show_troops_movement"),
    ("S3.5", "AYA, montre le drill de réputation 2 positifs et 1 critique.", "aya.show_reputation_drill"),
    ("S3.6", "AYA, prépare un communiqué de sécurité sur la rumeur frontière Nord.", "aya.draft_security_communique"),
    # Smoke-probe phrases (scripts/smoke_predeploy_probe.py) — should match too.
    ("S3.1b", "AYA, montre-moi la posture securitaire du jour", "aya.show_security_posture"),
    ("S3.2b", "AYA, montre la pulsation sociale a Abidjan", "aya.show_social_pulse"),
    ("S3.3b", "AYA, d'ou vient la rumeur frontiere Nord ?", "aya.trace_rumor_origin"),
    ("S3.4b", "AYA, montre les mouvements de troupes au Sahel", "aya.show_troops_movement"),
    ("S3.5b", "AYA, montre le drill de réputation 2 positifs 1 critique", "aya.show_reputation_drill"),
    ("S3.6b", "AYA, prepare un communique de securite sur la rumeur Nord", "aya.draft_security_communique"),
]


def main() -> int:
    from app.services.actions.registry import resolve_action

    workspace = _build_workspace()
    rows: list[dict[str, Any]] = []
    pass_count = 0
    for step_id, phrase, expected in PHRASES:
        res = resolve_action(workspace, text=phrase, surface="chat", assistant_profile="vigie_executive")
        matched = bool(res.matched and res.action_id == expected)
        confidence = float(res.confidence or 0.0)
        deterministic = confidence >= 0.85
        verdict = "PASS" if matched and deterministic else ("PARTIAL" if matched else "FAIL")
        if verdict == "PASS":
            pass_count += 1
        rows.append(
            {
                "step": step_id,
                "phrase": phrase,
                "expected_action": expected,
                "matched_action": res.action_id,
                "confidence": round(confidence, 3),
                "verdict": verdict,
                "reason": res.reason,
            }
        )

    width = max(len(r["phrase"]) for r in rows) + 2
    print(f"{'step':<6} {'verdict':<8} {'conf':>6} {'action':<32} phrase")
    print("-" * (6 + 8 + 6 + 32 + width + 4))
    for r in rows:
        print(
            f"{r['step']:<6} {r['verdict']:<8} {r['confidence']:>6.3f} {str(r['matched_action'] or '-'):<32} {r['phrase']}"
        )
    print()
    print(f"Result: {pass_count}/{len(rows)} PASS deterministic (confidence >= 0.85)")
    out_path = Path(__file__).resolve().parent.parent / "docs" / "status-screenshots" / "2026-05-25-qa-s3-trame" / "s3-resolver-results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0 if pass_count == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
