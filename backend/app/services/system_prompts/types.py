"""System prompt types"""
from enum import Enum


class SystemPromptType(Enum):
    """Types of system prompts for different reasoning"""
    FACTUAL = "factual"
    ANALYTICAL = "analytical"
    COMPARATIVE = "comparative"
    CAUSAL = "causal"
    HYPOTHETICAL = "hypothetical"
    TRIVIAL = "trivial"

