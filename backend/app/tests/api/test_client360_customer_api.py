from __future__ import annotations

from app.api.v1.endpoints import client360


def _exercise_customer_endpoint(monkeypatch, *, include_ai_summary: bool) -> list[tuple]:
    events: list[tuple] = []

    def _enforce(*_args, **kwargs):
        events.append(("authorize", kwargs["action"], kwargs["resource_attrs"]["operation"]))

    def _payload(*_args, **kwargs):
        events.append(("payload", kwargs["include_ai_summary"]))
        return {"customer": {"id": "customer-a"}, "ai_summary": None}

    monkeypatch.setattr(client360, "_enforce_client360_action", _enforce)
    monkeypatch.setattr(client360, "customer_payload", _payload)

    client360.client360_customer(
        "customer-a",
        include_ai_summary=include_ai_summary,
        workspace=object(),
        user=object(),
        db=object(),
    )
    return events


def test_customer_detail_authorizes_read_before_loading_payload(monkeypatch) -> None:
    assert _exercise_customer_endpoint(monkeypatch, include_ai_summary=False) == [
        ("authorize", "read", "customer_detail"),
        ("payload", False),
    ]


def test_customer_detail_with_ai_authorizes_engine_run_before_loading_payload(
    monkeypatch,
) -> None:
    assert _exercise_customer_endpoint(monkeypatch, include_ai_summary=True) == [
        ("authorize", "engine.run", "customer_summary"),
        ("payload", True),
    ]


def test_customer_summary_authorizes_engine_run_before_loading_payload(
    monkeypatch,
) -> None:
    events: list[tuple] = []

    def _enforce(*_args, **kwargs):
        events.append(("authorize", kwargs["action"], kwargs["resource_attrs"]["operation"]))

    def _payload(*_args, **kwargs):
        events.append(("payload", kwargs["include_ai_summary"]))
        return {
            "customer": {"id": "customer-a"},
            "ai_summary": {"text": "Summary"},
        }

    monkeypatch.setattr(client360, "_enforce_client360_action", _enforce)
    monkeypatch.setattr(client360, "customer_payload", _payload)

    response = client360.client360_customer_summary(
        "customer-a",
        workspace=object(),
        user=object(),
        db=object(),
    )

    assert events == [
        ("authorize", "engine.run", "customer_summary"),
        ("payload", True),
    ]
    assert response["ai_summary"]["text"] == "Summary"
