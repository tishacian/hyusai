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


@pytest.mark.parametrize("model,temperature", [("gpt-5", None), ("openai/gpt-5-mini", None), ("gpt-4o-mini", 0)])
def test_raget_respects_canonical_openai_temperature_constraint(monkeypatch, model, temperature):
    import io
    import sys
    from app.services.evaluation import giskard_adapter as adapter
    calls = []
    def complete(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(usage=SimpleNamespace(total_tokens=10))
    llm = SimpleNamespace(completion=complete, embedding=complete,
        token_counter=lambda **kwargs: 10, completion_cost=lambda **kwargs: 0.01)
    monkeypatch.setitem(sys.modules, "litellm", llm)
    monkeypatch.setattr(adapter, "installed_raget_version", lambda: "2.19.2")
    monkeypatch.setattr(adapter, "configure_giskard_models", lambda **kwargs: None)
    frame = SimpleNamespace(columns=["id"], to_json=lambda **kwargs: "[]")
    def generate(*args, **kwargs):
        llm.completion(messages=[{"role": "user", "content": "Synthetic"}], temperature=0, max_tokens=100)
        return SimpleNamespace(to_pandas=lambda: frame)
    monkeypatch.setattr(adapter, "generate_rag_testset", generate)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"model":model, "embedding_model":"text-embedding-3-small",
        "api_key":"fixture", "max_calls":2, "max_tokens":1000, "rows":[], "num_questions":1, "language":"en"})))
    adapter._isolated_main()
    assert calls[0].get("temperature") == temperature
    assert calls[0]["max_tokens"] == 100
    assert calls[0]["model"] == model
