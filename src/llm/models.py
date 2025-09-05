"""
Pydantic models for LLM request/response validation.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import (
    Any,
    Literal,
    Optional,
    Union,
)
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator
from typing_extensions import Required, TypedDict


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
# Message Types (using TypedDict for input validation)
# ============================================================================

class SystemMessageParam(TypedDict, total=False):
    """System message parameters."""
    content: Required[str]
    role: Required[Literal["system"]]
    name: str  # Optional participant name


class UserMessageParam(TypedDict, total=False):
    """User message parameters."""
    content: Required[str]
    role: Required[Literal["user"]]
    name: str  # Optional participant name


class AssistantMessageParam(TypedDict, total=False):
    """Assistant message parameters."""
    content: Required[str]
    role: Required[Literal["assistant"]]
    name: str  # Optional participant name


MessageParam = Union[
    SystemMessageParam,
    UserMessageParam,
    AssistantMessageParam,
]


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
    messages: list[MessageParam]
    
    # Common optional parameters
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=1.0, ge=0.0, le=1.0)
    n: Optional[int] = Field(default=1, ge=1)
    stream: Optional[bool] = False
    stop: Optional[Union[str, list[str]]] = None
    max_tokens: Optional[int] = Field(default=None, gt=0)
    max_completion_tokens: Optional[int] = Field(default=None, gt=0)
    presence_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0)
    frequency_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0)
    logit_bias: Optional[dict[str, float]] = None
    user: Optional[str] = None
    
    # Advanced parameters
    response_format: Optional[dict[str, Any]] = None  # JSON mode, schemas
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
    _provider_specific_params: dict[str, Any] = PrivateAttr(default_factory=dict)
    
    model_config = ConfigDict(
        protected_namespaces=(),  # Allow 'model' field
        extra="allow",  # Allow additional fields for forward compatibility
        str_strip_whitespace=True,
    )
    
    @field_validator("messages")
    def validate_messages(cls, v):
        """Ensure at least one message is provided."""
        if not v:
            raise ValueError("At least one message is required")
        return v


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
    
    # Advanced features
    reasoning_content: Optional[str] = None  # For thinking models
    annotations: Optional[list[dict[str, Any]]] = None
    
    # Provider-specific fields (hidden from default serialization)
    provider_specific_fields: Optional[dict[str, Any]] = Field(
        default=None, exclude=True
    )
    
    model_config = ConfigDict(extra="allow")
    
    def dict(self, **kwargs):
        """Override dict to handle None fields."""
        d = super().model_dump(**kwargs)
        # Remove None values for cleaner responses
        return {k: v for k, v in d.items() if v is not None}


class Choice(BaseModel):
    """Completion choice."""
    index: int = 0
    message: Message
    finish_reason: Optional[str] = None
    logprobs: Optional[dict[str, Any]] = None
    
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
    choices: list[Choice]
    usage: Optional[TokenUsage] = None
    
    # Optional fields
    system_fingerprint: Optional[str] = None
    
    # Metadata
    response_ms: Optional[float] = None  # Response time in milliseconds
    
    # Hidden parameters
    _response_headers: Optional[dict[str, str]] = PrivateAttr(default=None)
    _provider_response: Optional[dict[str, Any]] = PrivateAttr(default=None)
    
    model_config = ConfigDict(
        protected_namespaces=(),
        extra="allow",
    )


class StreamChoice(BaseModel):
    """Streaming choice delta."""
    index: int = 0
    delta: dict[str, Any]  # Content delta
    finish_reason: Optional[str] = None
    logprobs: Optional[dict[str, Any]] = None
    
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
    choices: list[StreamChoice]
    usage: Optional[TokenUsage] = None  # Only on final chunk
    
    system_fingerprint: Optional[str] = None
    
    model_config = ConfigDict(
        protected_namespaces=(),
        extra="allow",
    )
