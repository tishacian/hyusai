from types import SimpleNamespace

from app.services.ecommerce import claims
from app.services.ecommerce.record_identity import claims_record_identity


def test_claims_reader_supplies_its_identity_only_when_active(monkeypatch):
    workspace = SimpleNamespace(settings={})
    monkeypatch.setattr(claims, "_config", lambda ws: {"allowed_claim_ids": ["RC-1"]})
    assert claims_record_identity(workspace, "reclamations", "showcase.claims.investigate") == {
        "namespace": "claim",
        "input_field": "claim_id",
    }
    assert claims_record_identity(workspace, "other-app", "showcase.claims.investigate") is None
    assert claims_record_identity(workspace, "reclamations", "showcase.claims.refresh_queue") is None

    def disabled(ws):
        raise ValueError("ECOMMERCE_CLAIMS_DISABLED")

    monkeypatch.setattr(claims, "_config", disabled)
    assert claims_record_identity(workspace, "reclamations", "showcase.claims.investigate") is None


def test_the_resolver_loads_the_claims_reader_without_the_api(monkeypatch):
    """An offline script resolves claims identity although nothing imported the API."""
    from app.services.experience import record_identity

    monkeypatch.setattr(record_identity, "_PROVIDERS", [])
    monkeypatch.setattr(record_identity, "_loaded", False, raising=False)
    monkeypatch.setattr(claims, "_config", lambda ws: {"allowed_claim_ids": ["RC-1"]})

    resolved = record_identity.resolve_record_identity(
        {"binding_key": "showcase.claims.investigate"},
        workspace=SimpleNamespace(settings={}),
        experience_slug="reclamations",
    )

    assert resolved == {"namespace": "claim", "input_field": "claim_id"}
