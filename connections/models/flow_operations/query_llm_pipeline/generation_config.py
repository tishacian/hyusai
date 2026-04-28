from typing import Literal, get_args

from pydantic import BaseModel, Field, model_validator

# All model identifiers accepted when provider == "openai".
OpenAIModelName = Literal[
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
    "o1",
    "o1-mini",
    "o3",
    "o3-mini",
    "o4-mini",
    "gpt-5",
]

# Subset that supports reasoning — used to conditionally enable encrypted
# reasoning tokens for ZDR compliance (include=["reasoning.encrypted_content"]).
OPENAI_REASONING_MODELS: frozenset[str] = frozenset(
    {"o1", "o1-mini", "o3", "o3-mini", "o4-mini", "gpt-5"}
)

_OPENAI_MODEL_VALUES: frozenset[str] = frozenset(get_args(OpenAIModelName))


class GenerationConfig(BaseModel):
    provider: Literal["openai", "local"] = Field(
        "openai",
        description=(
            "LLM provider used for answer generation. "
            "'openai' calls the OpenAI Responses API (requires OPENAI_API_KEY env var). "
            "'local' routes to an on-premise inference endpoint (vLLM, llama.cpp, or Ollama)."
        ),
    )
    model_name: str = Field(
        "gpt-4o",
        description=(
            "Model identifier passed to the provider. "
            f"OpenAI accepted values: {sorted(_OPENAI_MODEL_VALUES)}. "
            "Local: any HuggingFace repo ID or GGUF filename served by the inference endpoint."
        ),
    )
    temperature: float = Field(
        0.7,
        ge=0.0,
        le=2.0,
        description=(
            "Sampling temperature controlling response randomness. "
            "0.0 → fully deterministic (greedy decoding). "
            "1.0 → standard sampling. "
            "Values above 1.2 produce creative but less reliable outputs. "
            "Use 0.0–0.3 for factual Q&A; 0.6–1.0 for open-ended generation."
        ),
    )
    max_tokens: int = Field(
        2048,
        gt=0,
        description=(
            "Maximum number of tokens in the generated response. "
            "The actual output may be shorter if the model generates an end-of-sequence token earlier. "
            "Set lower (e.g. 512) for concise answers; higher for detailed explanations."
        ),
    )
    top_p: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description=(
            "Nucleus sampling probability mass. "
            "Only the top tokens whose cumulative probability ≤ top_p are considered. "
            "None disables nucleus sampling (the model uses temperature alone). "
            "Typical values: 0.9–0.95. Avoid setting both temperature and top_p to non-default simultaneously."
        ),
    )
    system_prompt_language: Literal["EN", "FR"] = Field(
        "EN",
        description=(
            "Language of the adaptive system prompt template loaded from the database. "
            "The template is selected per reasoning type (FACTUAL, ANALYTICAL, CREATIVE, etc.) "
            "and injected before the user query."
        ),
    )

    @model_validator(mode="after")
    def _validate_openai_model_name(self) -> "GenerationConfig":
        if self.provider == "openai" and self.model_name not in _OPENAI_MODEL_VALUES:
            raise ValueError(
                f"Unknown OpenAI model '{self.model_name}'. "
                f"Accepted values: {sorted(_OPENAI_MODEL_VALUES)}"
            )
        return self
