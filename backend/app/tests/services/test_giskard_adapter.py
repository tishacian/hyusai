import pytest

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
