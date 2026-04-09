"""
Pydantic models for LLM request/response validation.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator


def generate_request_id() -> str:
    """Generate a unique request ID."""
    return f"llmass-{uuid4()}"


class MessageRole(str, Enum):
    """Valid message roles."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class CallType(str, Enum):
    """Types of LLM calls."""
    COMPLETION = "completion"
    STREAMING = "streaming"


# ============================================================================
# Request Message Models (strict Pydantic)
# ============================================================================

class BaseMessage(BaseModel):
    """Base request message model."""
    content: str
    name: Optional[str] = None

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SystemMessage(BaseMessage):
    role: Literal["system"]


class UserMessage(BaseMessage):
    role: Literal["user"]


class AssistantMessage(BaseMessage):
    role: Literal["assistant"]


MessageParam = Union[SystemMessage, UserMessage, AssistantMessage]


# ============================================================================
# Request Models
# ============================================================================

class CompletionRequest(BaseModel):
    """
    Unified completion request model.
    Compatible with OpenAI API format while supporting provider extensions.
    """
    # Required fields
    model: str
    messages: List[MessageParam]
    
    # Common optional parameters
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=1.0, ge=0.0, le=1.0)
    n: Optional[int] = Field(default=1, ge=1)
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    max_tokens: Optional[int] = Field(default=None, gt=0)
    max_completion_tokens: Optional[int] = Field(default=None, gt=0)
    presence_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0)
    frequency_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0)
    logit_bias: Optional[Dict[str, float]] = None
    user: Optional[str] = None
    
    # Advanced parameters
    response_format: Optional[Dict[str, Any]] = None
    seed: Optional[int] = None
    logprobs: Optional[bool] = None
    top_logprobs: Optional[int] = Field(default=None, ge=0, le=20)
    
    # Provider-specific parameters
    reasoning_effort: Optional[Literal["low", "medium", "high"]] = None  # For thinking models
    
    # Routing and configuration
    timeout: Optional[float] = Field(default=None, gt=0)
    api_key: Optional[str] = Field(default=None, exclude=True)
    base_url: Optional[str] = None
    api_version: Optional[str] = None
    
    # Metadata
    request_id: str = Field(default_factory=generate_request_id)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Hidden parameters (not serialized)
    _provider_specific_params: Dict[str, Any] = PrivateAttr(default_factory=dict)
    
    model_config = ConfigDict(
        protected_namespaces=(),
        extra="allow",  # Strict payload: allow unknown fields
        str_strip_whitespace=True,
    )
    
    @field_validator("messages")
    def validate_messages(cls, v):
        """Ensure at least one message is provided."""
        if not v:
            raise ValueError("At least one message is required")
        return v

    def messages_as_dicts(self) -> list[dict[str, Any]]:
        """Return messages as list of plain dicts (exclude None fields)."""
        dicts: List[Dict[str, Any]] = []
        for m in self.messages:
            if isinstance(m, BaseModel):
                # Pydantic v2 serialization
                dicts.append(m.model_dump(exclude_none=True))
            else:
                # Already a dict-like (should not happen post-validation, but safe)
                dicts.append(dict(m))  # type: ignore[arg-type]
        return dicts


# ============================================================================
# Usage and Cost Tracking
# ============================================================================

class TokenUsage(BaseModel):
    """Token usage statistics."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    
    # Advanced token tracking
    reasoning_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None
    
    # Cost tracking
    prompt_cost: Optional[float] = None
    completion_cost: Optional[float] = None
    total_cost: Optional[float] = None
    
    model_config = ConfigDict(extra="allow")
    
    def calculate_total(self) -> None:
        """Calculate total tokens."""
        self.total_tokens = self.prompt_tokens + self.completion_tokens
        
        if self.prompt_cost is not None and self.completion_cost is not None:
            self.total_cost = self.prompt_cost + self.completion_cost


class ModelInfo(BaseModel):
    """Information about a model including pricing."""
    key: str  # Model identifier
    provider: str
    
    # Context limits
    max_tokens: Optional[int] = None
    max_input_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    
    # Pricing (per token)
    input_cost_per_token: float = 0.0
    output_cost_per_token: float = 0.0
    
    # Cache pricing
    cache_creation_cost_per_token: Optional[float] = None
    cache_read_cost_per_token: Optional[float] = None
    
    # Capabilities
    supports_streaming: bool = True
    supports_functions: bool = False
    supports_vision: bool = False
    supports_audio: bool = False
    supports_web_search: bool = False
    
    # Rate limits
    tpm: Optional[int] = None  # Tokens per minute
    rpm: Optional[int] = None  # Requests per minute
    
    model_config = ConfigDict(
        protected_namespaces=(),
        extra="allow",
    )


# ============================================================================
# Response Models
# ============================================================================

class Message(BaseModel):
    """Response message object."""
    role: MessageRole
    content: Optional[str] = None

    reasoning_content: Optional[str] = None
    annotations: Optional[List[Dict[str, Any]]] = None

    provider_specific_fields: Optional[Dict[str, Any]] = Field(
        default=None, exclude=True
    )

    model_config = ConfigDict(extra="allow")

    def to_dict(self, **kwargs):
        d = super().model_dump(**kwargs)
        return {k: v for k, v in d.items() if v is not None}


class Choice(BaseModel):
    """Completion choice."""
    index: int = 0
    message: Message
    finish_reason: Optional[str] = None
    logprobs: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="allow")


class CompletionResponse(BaseModel):
    """
    Unified completion response model.
    Compatible with OpenAI API format.
    """
    id: str = Field(default_factory=generate_request_id)
    object: Literal["chat.completion", "chat.completion.chunk"] = "chat.completion"
    created: int = Field(default_factory=lambda: int(datetime.now(timezone.utc).timestamp()))
    model: str
    choices: List[Choice]
    usage: Optional[TokenUsage] = None
    
    # Optional fields
    system_fingerprint: Optional[str] = None
    
    # Metadata
    response_ms: Optional[float] = None  # Response time in milliseconds
    
    # Hidden parameters
    _response_headers: Optional[Dict[str, str]] = PrivateAttr(default=None)
    _provider_response: Optional[Dict[str, Any]] = PrivateAttr(default=None)
    
    model_config = ConfigDict(
        protected_namespaces=(),
        extra="allow",
    )


class StreamChoice(BaseModel):
    """Streaming choice delta."""
    index: int = 0
    delta: Dict[str, Any]
    finish_reason: Optional[str] = None
    logprobs: Optional[Dict[str, Any]] = None
    
    model_config = ConfigDict(extra="allow")


class StreamingResponse(BaseModel):
    """
    Streaming completion response chunk.
    Compatible with Server-Sent Events (SSE) format.
    """
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: List[StreamChoice]
    usage: Optional[TokenUsage] = None
    
    system_fingerprint: Optional[str] = None
    
    model_config = ConfigDict(
        protected_namespaces=(),
        extra="allow",
    )
