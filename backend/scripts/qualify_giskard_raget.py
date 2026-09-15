"""Offline SDK qualification with synthetic data and explicit mocked model calls.

Run with the optional Giskard Python 3.12 environment and PYTHONPATH=backend.
This exercises real QATestset, KnowledgeBase, evaluate and RAGReport objects.
It does not qualify a provider or report real model quality.
"""
import json
import os
from importlib.metadata import version

os.environ["GISKARD_DISABLE_ANALYTICS"] = "true"

import numpy as np
import pandas as pd
from giskard.rag import QATestset
from giskard.llm.client import ChatMessage, LLMClient, set_default_client
from giskard.llm.embeddings import set_default_embedding, set_embedding_model
from giskard.llm.embeddings.base import BaseEmbedding
from app.services.evaluation.giskard_adapter import KnowledgeBaseRow, evaluate_rag_testset


class FixtureJudge(LLMClient):
    calls = 0

    def complete(self, messages, **kwargs):
        self.calls += 1
        if kwargs.get("format") == "json_object":
            passed = self.calls != 1
            return ChatMessage(role="assistant", content=json.dumps({"correctness": passed,
                "correctness_reason": "Fixture verdict for SDK plumbing qualification."}))
        return ChatMessage(role="assistant", content="Fixture recommendation; no provider was called.")

    def get_config(self):
        return {"kind": "offline_fixture"}


class FixtureEmbedding(BaseEmbedding):
    def embed(self, texts):
        return np.random.default_rng(42).random((len(texts), 16))


def main():
    judge = FixtureJudge()
    set_default_client(judge)
    set_embedding_model("offline-fixture")
    set_default_embedding(FixtureEmbedding())
    rows = [KnowledgeBaseRow(text=f"NorthForge synthetic manual section {index}. Nominal pressure is 6 bar. Inspection occurs before maintenance.") for index in range(8)]
    records = [{"id": f"case-{index}", "question": question, "reference_answer": reference,
        "reference_context": rows[0].text, "conversation_history": [],
        "metadata": {"run_id": f"synthetic-run-{index}", "question_type": "reviewed", "topic": "maintenance"}}
        for index, (question, reference) in enumerate([
            ("What is nominal pressure?", "6 bar"), ("Which pressure should be used?", "6 bar"),
            ("What is the unavailable serial number?", "The supplied manual does not specify it.")])]
    testset = QATestset.from_pandas(pd.DataFrame(records))
    answers = {records[0]["question"]: "8 bar", records[1]["question"]: "6 bar",
               records[2]["question"]: "The supplied manual does not specify it."}
    report = evaluate_rag_testset(lambda question: answers[question], testset, rows)
    encoded = json.loads(report.to_pandas().reset_index().to_json(orient="records"))
    assert len(encoded) == 3
    assert [row["correctness"] for row in encoded] == [False, True, True]
    assert [row["metadata"]["run_id"] for row in encoded] == [f"synthetic-run-{index}" for index in range(3)]
    assert all(row["agent_answer"] == answers[row["question"]] for row in encoded)
    print(json.dumps({"sdk": version("giskard"), "python_scope": "isolated_optional_environment",
        "cases": 3, "judge_calls": judge.calls, "models": "mocked", "provider_live_run": "NOT RUN",
        "qatestset": "PASS", "knowledge_base": "PASS", "rag_report": "PASS", "canonical_reference_serialization": "PASS"}))


if __name__ == "__main__":
    main()
