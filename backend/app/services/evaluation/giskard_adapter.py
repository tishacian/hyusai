"""Optional Giskard/RAGET integration.

This module is intentionally not imported by the chat/orchestrator path.
It gives us a narrow adapter for offline jobs (manual "generate eval set",
nightly QA, future E1.5.5b Hypervisor suggestions) while Agentium remains
usable if the optional ``giskard[llm]`` dependency is not installed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional

_ISOLATED_USAGE: dict[str, Any] = {}


def installed_raget_version() -> str | None:
    from importlib.metadata import PackageNotFoundError, version
    try:
        installed = version("giskard")
    except PackageNotFoundError:
        return None
    try:
        major, minor = (int(part) for part in installed.split(".")[:2])
    except ValueError:
        return None
    return installed if major == 2 and minor >= 15 else None


def generate_isolated(*, rows: list[dict], model: str, embedding_model: str, api_key: str,
                      num_questions: int, language: str, max_calls: int = 40,
                      max_tokens: int = 100_000, timeout_seconds: int = 300,
                      evaluation_cases: list[dict] | None = None) -> dict:
    """One fresh interpreter per job: no tenant model/credential globals survive."""
    import json
    import os
    import subprocess
    import sys
    if not api_key or not model or not embedding_model:
        raise GiskardUnavailable("Explicit model, embedding model and credential required")
    if not 1 <= num_questions <= 20 or not 1 <= max_calls <= 100 or not 1 <= max_tokens <= 200_000:
        raise ValueError("Giskard generation budget exceeds the offline worker limits")
    payload = dict(rows=rows, model=model, embedding_model=embedding_model, api_key=api_key,
                   num_questions=num_questions, language=language, max_calls=max_calls, max_tokens=max_tokens,
                   evaluation_cases=evaluation_cases)
    environment = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "PYTHONPATH", "VIRTUAL_ENV") if key in os.environ}
    environment["GISKARD_DISABLE_ANALYTICS"] = "true"
    try:
        result = subprocess.run([sys.executable, "-m", "app.services.evaluation.giskard_adapter"],
            input=json.dumps(payload), text=True, capture_output=True, env=environment,
            timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired as exc:
        raise GiskardUnavailable("Giskard generation exceeded its execution time budget") from exc
    # Never propagate vendor stderr: it may contain a prompt, endpoint or key.
    lines = [line[18:] for line in result.stdout.splitlines() if line.startswith("AGENTIUM_RAGET_V1: ")]
    if result.returncode or not lines:
        usage = None
        if lines:
            try:
                usage = json.loads(lines[-1]).get("usage")
            except (ValueError, AttributeError):
                pass
        raise GiskardUnavailable("Giskard generation unavailable or budget exhausted; no test cases were approved", usage=usage)
    report = json.loads(lines[-1])
    if not isinstance(report.get("cases"), list):
        raise GiskardUnavailable("Giskard returned an invalid testset")
    return report


def _isolated_main() -> None:
    """Restricted OpenAI RAGET worker; credentials arrive over stdin, never argv."""
    import json
    import sys
    import threading
    import litellm
    payload = json.load(sys.stdin)
    version = installed_raget_version()
    if version is None:
        raise GiskardUnavailable("Install the compatible Giskard 2.x optional worker dependency")
    lock = threading.Lock()
    global _ISOLATED_USAGE
    usage = {"calls": 0, "reserved_tokens": 0, "provider_tokens": 0, "cost_usd": 0.0, "cost_complete": True,
             "cost_basis": "litellm_model_catalogue", "token_basis": "provider_reported"}
    _ISOLATED_USAGE = usage
    # Install before importing Giskard: all synchronous RAGET calls share these
    # bounds inside this disposable interpreter, never across workspaces.
    for name in ("completion", "embedding"):
        original = getattr(litellm, name)
        def bounded(*args, _original=original, _kind=name, **kwargs):
            expected_model = payload["model"] if _kind == "completion" else payload["embedding_model"]
            kwargs["model"], kwargs["api_key"] = expected_model, payload["api_key"]
            kwargs.pop("api_base", None)
            kwargs["timeout"] = 45
            kwargs["num_retries"] = 0
            if _kind == "completion":
                kwargs["max_tokens"] = min(int(kwargs.get("max_tokens") or 2048), 2048)
                incoming = litellm.token_counter(model=expected_model, messages=kwargs.get("messages", []))
                reservation = incoming + kwargs["max_tokens"]
            else:
                incoming = kwargs.get("input", [])
                reservation = litellm.token_counter(model=expected_model, text=json.dumps(incoming))
            with lock:
                if usage["calls"] >= payload["max_calls"] or usage["reserved_tokens"] + reservation > payload["max_tokens"]:
                    raise GiskardUnavailable("Giskard token or call budget exhausted")
                usage["calls"] += 1
                usage["reserved_tokens"] += reservation
            response = _original(*args, **kwargs)
            with lock:
                provider_usage = getattr(response, "usage", None)
                usage["provider_tokens"] += int(getattr(provider_usage, "total_tokens", 0) or 0)
                try:
                    usage["cost_usd"] += float(litellm.completion_cost(completion_response=response))
                except Exception:
                    usage["cost_complete"] = False
            return response
        setattr(litellm, name, bounded)
    configure_giskard_models(llm_model=payload["model"], embedding_model=payload["embedding_model"])
    rows = [KnowledgeBaseRow(text=row["text"], metadata=row.get("metadata")) for row in payload["rows"]]
    if payload.get("evaluation_cases"):
        import pandas as pd
        from giskard.rag import QATestset
        records = payload["evaluation_cases"]
        answers = {record["question"]: record["agent_answer"] for record in records}
        testset = QATestset.from_pandas(pd.DataFrame([{key: value for key, value in record.items() if key != "agent_answer"} for record in records]))
        # The answer function only returns the already persisted canonical Run
        # output. Giskard cannot run a System or trigger any external effect.
        report = evaluate_rag_testset(lambda question: answers[question], testset, rows)
        frame = report.to_pandas()
    else:
        testset = generate_rag_testset(rows, num_questions=payload["num_questions"], language=payload["language"])
        frame = testset.to_pandas()
    if "id" not in frame.columns:
        frame = frame.reset_index()
    cases = json.loads(frame.to_json(orient="records"))
    if not usage["cost_complete"]:
        usage["cost_usd"] = None
    print("AGENTIUM_RAGET_V1: " + json.dumps({"method": "giskard_raget", "version": version,
        "review_status": "evaluated" if payload.get("evaluation_cases") else "proposed", "cases": cases, "usage": usage,
        "models": {"judge": payload["model"], "embedding": payload["embedding_model"]}}))


class GiskardUnavailable(RuntimeError):
    """Raised when optional Giskard features are used without the extra dep."""
    def __init__(self, message: str, *, usage=None):
        super().__init__(message)
        self.usage = usage


@dataclass(frozen=True)
class KnowledgeBaseRow:
    text: str
    metadata: Optional[Mapping[str, Any]] = None


def _import_giskard_rag():
    try:
        from giskard.rag import KnowledgeBase, evaluate, generate_testset  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise GiskardUnavailable(
            "Giskard is not installed. Install backend/requirements_giskard.txt "
            "on the offline eval worker to enable RAGET testset generation."
        ) from exc
    return KnowledgeBase, evaluate, generate_testset


def is_giskard_available() -> bool:
    try:
        _import_giskard_rag()
        return True
    except GiskardUnavailable:
        return False


def configure_giskard_models(
    *,
    llm_model: Optional[str] = None,
    embedding_model: Optional[str] = None,
    api_base: Optional[str] = None,
    disable_structured_output: bool = False,
) -> None:
    """Configure Giskard's LiteLLM-backed model defaults.

    Giskard RAGET needs an embedding model even to build a KnowledgeBase.
    Keeping this explicit avoids surprising network calls from import-time
    defaults and makes the offline worker contract obvious.
    """
    try:
        import giskard  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise GiskardUnavailable(
            "Giskard is not installed. Install backend/requirements_giskard.txt "
            "on the offline eval worker to enable RAGET testset generation."
        ) from exc

    kwargs: dict[str, Any] = {}
    if api_base:
        kwargs["api_base"] = api_base
    if llm_model:
        giskard.llm.set_llm_model(
            llm_model,
            disable_structured_output=disable_structured_output,
            **kwargs,
        )
    if embedding_model:
        giskard.llm.set_embedding_model(embedding_model, **kwargs)


def make_knowledge_base(rows: Iterable[KnowledgeBaseRow]):
    """Build a Giskard KnowledgeBase from Agentium document chunks."""
    KnowledgeBase, _, _ = _import_giskard_rag()
    try:
        import pandas as pd  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise GiskardUnavailable(
            "Giskard RAGET requires pandas; install backend/requirements_giskard.txt."
        ) from exc

    records = [
        {
            "text": row.text,
            "metadata": dict(row.metadata or {}),
        }
        for row in rows
        if row.text and row.text.strip()
    ]
    try:
        return KnowledgeBase.from_pandas(pd.DataFrame(records), columns=["text"])
    except ValueError as exc:
        if "No embeddings model set" in str(exc):
            raise GiskardUnavailable(
                "Giskard KnowledgeBase requires an embedding model. Call "
                "configure_giskard_models(embedding_model=...) before "
                "make_knowledge_base/generate_rag_testset."
            ) from exc
        raise


def generate_rag_testset(
    rows: Iterable[KnowledgeBaseRow],
    *,
    num_questions: int = 30,
    language: Optional[str] = None,
    agent_description: Optional[str] = None,
    min_knowledge_rows: int = 8,
):
    """Generate a synthetic QA testset from Agentium KB rows.

    Returns Giskard's QATestset object. Callers should persist it as JSONL
    or convert to pandas; the adapter does not introduce a new Agentium
    table yet because E1.5.3 only needs online run analytics.
    """
    rows_list = [row for row in rows if row.text and row.text.strip()]
    if len(rows_list) < min_knowledge_rows:
        raise GiskardUnavailable(
            "Giskard RAGET topic discovery needs a non-trivial knowledge base. "
            f"Got {len(rows_list)} usable rows; require at least {min_knowledge_rows}."
        )
    _, _, generate_testset = _import_giskard_rag()
    kb = make_knowledge_base(rows_list)
    kwargs: dict[str, Any] = {"num_questions": num_questions}
    if language:
        kwargs["language"] = language
    if agent_description:
        kwargs["agent_description"] = agent_description
    return generate_testset(kb, **kwargs)


def evaluate_rag_testset(
    answer_fn: Callable[..., str],
    testset: Any,
    rows: Iterable[KnowledgeBaseRow],
):
    """Run Giskard RAGET evaluation against an Agentium answer function."""
    _, evaluate, _ = _import_giskard_rag()
    kb = make_knowledge_base(rows)
    return evaluate(answer_fn, testset=testset, knowledge_base=kb)


if __name__ == "__main__":
    try:
        _isolated_main()
    except Exception:
        import json
        import sys
        # Preserve known billing evidence without reflecting a vendor error.
        if _ISOLATED_USAGE.get("cost_complete") is False:
            _ISOLATED_USAGE["cost_usd"] = None
        print("AGENTIUM_RAGET_V1: " + json.dumps({"status": "failed", "cases": [], "usage": _ISOLATED_USAGE}))
        sys.exit(1)
