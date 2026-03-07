from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class QueryLLMPipelinePayload(BaseModel):
    retrieval_strategy: Literal["HAH", "HAHCOMPOSITE", "NAIVE"]
    llm_full_name: str
    knowledge_base_uuid: UUID
    user_prompt: str
    system_prompt_language: Literal["EN", "FR"] = "EN"
