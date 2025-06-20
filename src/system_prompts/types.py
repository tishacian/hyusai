from enum import StrEnum


class SystemPromptTypes(StrEnum):
    """All instruction types."""

    FACTUAL = "factual"
    ANALYTICAL = "analytical"
    COMPARATIVE = "comparative"
    CAUSAL = "causal"
    HYPOTHETICAL = "hypothetical"
    NAIVE = "naive"
