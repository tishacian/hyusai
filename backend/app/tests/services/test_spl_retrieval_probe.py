from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


def _load_probe_module():
    script = Path(__file__).resolve().parents[4] / "scripts" / "probe_spl_retrieval_scaling.py"
    spec = importlib.util.spec_from_file_location("probe_spl_retrieval_scaling", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(**overrides):
    base = {
        "api_base": "https://agentium.example/api/v1",
        "workspace_slug": "andritz",
        "collection": "andritz-notices-techniques-spl-pilot",
        "max_tokens": 120,
        "timeout": 12.0,
        "fast_budget_seconds": 8.0,
        "stream_budget_seconds": 30.0,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_probe_stream_chat_parses_sse_retrieval_and_text(monkeypatch):
    probe = _load_probe_module()
    lines = [
        {
            "chunk_type": "retrieval",
            "phase": "completed",
            "details": {
                "dense_policy": "fast_scoped_dense_auto",
                "scope_confidence": 0.42,
                "latency_budget": {"profile": "fast", "candidate_pool_k": 20},
            },
        },
        {"chunk_type": "text", "content": "answer"},
    ]

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def __iter__(self):
            encoded = [f"data: {json.dumps(item)}\n".encode("utf-8") for item in lines]
            encoded.append(b"data: [DONE]\n")
            return iter(encoded)

    monkeypatch.setattr(probe.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())

    status, payload, elapsed_ms = probe._stream_chat(
        _args(),
        "token",
        query="Analyse les procedures de securite SPL",
        mode="chah",
    )

    assert status == 200
    assert elapsed_ms >= 0
    assert payload["done"] is True
    assert payload["chat_stream_timeout"] is False
    assert payload["event_counts"] == {"retrieval": 1, "text": 1}
    assert payload["retrieval_details"]["dense_policy"] == "fast_scoped_dense_auto"
    assert payload["retrieval_details"]["latency_budget"]["candidate_pool_k"] == 20
    assert isinstance(payload["first_text_ms"], int)


def test_probe_stream_checks_require_no_timeout_done_and_first_text():
    probe = _load_probe_module()
    checks = []

    probe._check_stream(
        checks,
        label="quick_chah",
        status=200,
        payload={
            "done": False,
            "chat_stream_timeout": True,
            "stream_deadline_exceeded": True,
            "first_event_ms": 10,
            "first_retrieval_ms": 20,
            "first_text_ms": None,
            "event_counts": {"retrieval": 1, "error": 1},
            "retrieval_details": {
                "latency_budget": {"profile": "fast", "candidate_pool_k": 999},
            },
            "sample_events": [{"chunk_type": "error", "code": "CHAT_STREAM_TIMEOUT"}],
        },
        elapsed_ms=30_500,
        args=_args(),
    )

    by_label = {check.label: check for check in checks}
    assert by_label["quick_chah_stream_http_200"].passed is True
    assert by_label["quick_chah_stream_no_chat_timeout"].passed is False
    assert by_label["quick_chah_stream_done"].passed is False
    assert by_label["quick_chah_stream_first_text_fast"].passed is False
    assert by_label["quick_chah_stream_candidate_pool_bounded"].passed is False
    assert by_label["quick_chah_stream_policy_visible"].passed is False


def test_probe_parse_args_accepts_existing_token_without_password():
    probe = _load_probe_module()

    args = probe.parse_args(
        [
            "--host",
            "https://agentium.example/api/v1",
            "--workspace-slug",
            "andritz",
            "--token",
            "token",
        ]
    )

    assert args.api_base == "https://agentium.example/api/v1"
    assert args.token == "token"
    assert args.workspace_slug == "andritz"
