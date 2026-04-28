from connections.models.flow_operations.query_llm_pipeline.generation_config import (
    GenerationConfig,
)

from .base import LLMService
from .openai_service import OpenAIService


def create_llm_service(config: GenerationConfig) -> LLMService:
    if config.provider == "openai":
        return OpenAIService(
            model_name=config.model_name,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            top_p=config.top_p,
        )
    raise NotImplementedError(f"Provider '{config.provider}' is not yet supported.")
