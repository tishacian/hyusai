import pytest
import json
from types import SimpleNamespace

from app.services.evaluation.giskard_adapter import (
    GiskardUnavailable,
    KnowledgeBaseRow,
    generate_rag_testset,
)


def test_generate_rag_testset_rejects_tiny_knowledge_base_before_importing_giskard():
    with pytest.raises(GiskardUnavailable, match="require at least 8"):
        generate_rag_testset(
            [KnowledgeBaseRow(text="Tiny KB row")],
            num_questions=1,
        )


def test_isolated_generation_does_not_inherit_credentials_or_change_parent(monkeypatch):
    from app.services.evaluation.giskard_adapter import generate_isolated
    monkeypatch.setenv("OPENAI_API_KEY", "parent-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "other-tenant-secret")
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert "OPENAI_API_KEY" not in kwargs["env"]
        assert "ANTHROPIC_API_KEY" not in kwargs["env"]
        payload = json.loads(kwargs["input"])
        assert payload["api_key"] == "workspace-key"
        assert "workspace-key" not in str(command)
        return SimpleNamespace(returncode=0, stdout='noise\nAGENTIUM_RAGET_V1: {"cases":[],"review_status":"proposed"}\n', stderr="")
    monkeypatch.setattr("subprocess.run", run)
    result = generate_isolated(rows=[], model="gpt-4o-mini", embedding_model="text-embedding-3-small",
        api_key="workspace-key", num_questions=3, language="fr")
    assert result["review_status"] == "proposed"
    import os
    assert os.environ["OPENAI_API_KEY"] == "parent-secret"
    assert len(calls) == 1


def test_vendor_error_does_not_expose_stderr(monkeypatch):
    from app.services.evaluation.giskard_adapter import generate_isolated
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="secret-token and private document"))
    with pytest.raises(GiskardUnavailable) as error:
        generate_isolated(rows=[], model="gpt-4o-mini", embedding_model="text-embedding-3-small",
            api_key="workspace-key", num_questions=3, language="fr")
    assert "secret-token" not in str(error.value)


def test_excessive_budget_rejected_before_subprocess():
    from app.services.evaluation.giskard_adapter import generate_isolated
    with pytest.raises(ValueError):
        generate_isolated(rows=[], model="gpt-4o-mini", embedding_model="text-embedding-3-small",
            api_key="workspace-key", num_questions=3, language="fr", max_tokens=200_001)
