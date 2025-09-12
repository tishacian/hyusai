"""
vLLM provider implementation.
"""
import os
import time
import logging
from collections.abc import AsyncGenerator

from openai import AsyncOpenAI

from ..base import LLMProvider
from ..models import (
    CompletionRequest,
    CompletionResponse,
    Choice,
    Message,
    MessageRole,
    StreamingResponse,
    StreamChoice,
    TokenUsage,
)


class VLLMProvider(LLMProvider):
    """vLLM LLM provider implementation."""
    
    def __init__(
        self, 
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs
    ):
        """Initialize the vLLM provider."""
        self.api_key = api_key or os.getenv("VLLM_API_KEY") or "vllm-api-key"
        self.base_url = base_url or os.getenv("VLLM_BASE_URL")
        
        if not self.base_url:
            raise ValueError("vLLM base URL is required")

        # Normalize base_url to include protocol and /v1 suffix per vLLM docs
        if not (self.base_url.startswith("http://") or self.base_url.startswith("https://")):
            self.base_url = f"http://{self.base_url}"
        if not self.base_url.rstrip("/").endswith("/v1"):
            self.base_url = self.base_url.rstrip("/") + "/v1"

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            **kwargs
        )
    
    def _prepare_api_params(self, request: CompletionRequest, streaming: bool = False) -> dict:
        """
        Prepare parameters for vLLM API call.
        
        Args:
            request: Validated CompletionRequest
            streaming: Whether this is for streaming
            
        Returns:
            Dictionary of parameters for vLLM API
        """
        # Use default model if not specified
        model = request.model or "Qwen/Qwen2.5-0.6B-Instruct"
        
        params = {
            "model": model,
            "messages": request.messages_as_dicts(),
        }
        
        if streaming:
            params["stream"] = True
        
        # Add optional parameters
        if request.temperature is not None:
            params["temperature"] = request.temperature
        if request.max_tokens is not None:
            params["max_tokens"] = request.max_tokens
        if request.top_p is not None:
            params["top_p"] = request.top_p
        if request.n is not None:
            params["n"] = request.n
        if request.presence_penalty is not None:
            params["presence_penalty"] = request.presence_penalty
        if request.frequency_penalty is not None:
            params["frequency_penalty"] = request.frequency_penalty
        if request.stop:
            params["stop"] = request.stop
        if request.seed is not None:
            params["seed"] = request.seed
        if request.user:
            params["user"] = request.user
        if request.logit_bias is not None:
            params["logit_bias"] = request.logit_bias

        # Build vLLM extras for extra_body
        # Note: CompletionRequest allows extra fields but does not define them.
        # Access all provider-specific fields via getattr to avoid AttributeError
        # when they are not present on the model instance.
        extra_body: dict[str, object] = {}

        # Sampling/decoding extras
        best_of = getattr(request, "best_of", None)
        if best_of is not None:
            extra_body["best_of"] = best_of

        use_beam_search = getattr(request, "use_beam_search", None)
        if use_beam_search is not None:
            extra_body["use_beam_search"] = use_beam_search

        top_k = getattr(request, "top_k", None)
        if top_k is not None:
            extra_body["top_k"] = top_k

        min_p = getattr(request, "min_p", None)
        if min_p is not None:
            extra_body["min_p"] = min_p

        repetition_penalty = getattr(request, "repetition_penalty", None)
        if repetition_penalty is not None:
            extra_body["repetition_penalty"] = repetition_penalty

        length_penalty = getattr(request, "length_penalty", None)
        if length_penalty is not None:
            extra_body["length_penalty"] = length_penalty

        early_stopping = getattr(request, "early_stopping", None)
        if early_stopping is not None:
            extra_body["early_stopping"] = early_stopping

        ignore_eos = getattr(request, "ignore_eos", None)
        if ignore_eos is not None:
            extra_body["ignore_eos"] = ignore_eos

        min_tokens = getattr(request, "min_tokens", None)
        if min_tokens is not None:
            extra_body["min_tokens"] = min_tokens

        stop_token_ids = getattr(request, "stop_token_ids", None)
        if stop_token_ids is not None:
            extra_body["stop_token_ids"] = stop_token_ids

        skip_special_tokens = getattr(request, "skip_special_tokens", None)
        if skip_special_tokens is not None:
            extra_body["skip_special_tokens"] = skip_special_tokens

        spaces_between_special_tokens = getattr(request, "spaces_between_special_tokens", None)
        if spaces_between_special_tokens is not None:
            extra_body["spaces_between_special_tokens"] = spaces_between_special_tokens

        # Behavior extras
        echo = getattr(request, "echo", None)
        if echo is not None:
            extra_body["echo"] = echo

        add_generation_prompt = getattr(request, "add_generation_prompt", None)
        if add_generation_prompt is not None:
            extra_body["add_generation_prompt"] = add_generation_prompt

        include_stop_str_in_output = getattr(request, "include_stop_str_in_output", None)
        if include_stop_str_in_output is not None:
            extra_body["include_stop_str_in_output"] = include_stop_str_in_output

        guided_json = getattr(request, "guided_json", None)
        if guided_json is not None:
            extra_body["guided_json"] = guided_json

        guided_regex = getattr(request, "guided_regex", None)
        if guided_regex is not None:
            extra_body["guided_regex"] = guided_regex

        guided_choice = getattr(request, "guided_choice", None)
        if guided_choice is not None:
            extra_body["guided_choice"] = guided_choice

        guided_grammar = getattr(request, "guided_grammar", None)
        if guided_grammar is not None:
            extra_body["guided_grammar"] = guided_grammar

        guided_decoding_backend = getattr(request, "guided_decoding_backend", None)
        if guided_decoding_backend is not None:
            extra_body["guided_decoding_backend"] = guided_decoding_backend

        # Completions-only (safe to include)
        truncate_prompt_tokens = getattr(request, "truncate_prompt_tokens", None)
        if truncate_prompt_tokens is not None:
            extra_body["truncate_prompt_tokens"] = truncate_prompt_tokens

        # Merge user-provided extra_body last, allowing explicit fields to win
        request_extra_body = getattr(request, "extra_body", None)
        if request_extra_body:
            extra_body = {**request_extra_body, **extra_body}

        if extra_body:
            params["extra_body"] = extra_body

        return params
    
    def _calculate_costs(self, usage: TokenUsage, model: str) -> TokenUsage:
        """
        Calculate costs for vLLM - costs are set to 0 since it's typically self-hosted.
        
        Args:
            usage: Token usage object
            model: Model name
            
        Returns:
            Updated usage with costs set to 0
        """
        # vLLM is typically self-hosted so no costs
        usage.prompt_cost = 0.0
        usage.completion_cost = 0.0
        usage.total_cost = 0.0
        
        return usage
    
    async def generate(
        self,
        request: CompletionRequest
    ) -> CompletionResponse:
        """
        Generate a response using vLLM.

        Args:
            request: Validated CompletionRequest with all parameters

        Returns:
            CompletionResponse with choices, usage, and metadata
        """
        # Prepare API parameters
        params = self._prepare_api_params(request)
        
        # Track timing
        start_time = time.time()
        
        # Make the API call
        response = await self.client.chat.completions.create(**params)
        
        # Calculate response time
        response_ms = (time.time() - start_time) * 1000
        
        # Convert vLLM response to our typed response
        choices = []
        for choice in response.choices:
            message = Message(
                role=MessageRole.ASSISTANT,
                content=choice.message.content,
            )
            
            choices.append(
                Choice(
                    index=choice.index,
                    message=message,
                    finish_reason=choice.finish_reason,
                )
            )
        
        # Build usage info
        usage = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens
            )
            
            # Calculate costs (set to 0 for vLLM)
            usage = self._calculate_costs(usage, response.model)
        
        return CompletionResponse(
            id=response.id,
            model=response.model,
            created=response.created,
            choices=choices,
            usage=usage,
            response_ms=response_ms
        )
    
    async def stream_generate(
        self,
        request: CompletionRequest
    ) -> AsyncGenerator[StreamingResponse, None]:
        """
        Stream a response using vLLM.

        Args:
            request: Validated CompletionRequest with all parameters

        Returns:
            AsyncGenerator yielding StreamingResponse chunks
        """
        # Prepare API parameters
        params = self._prepare_api_params(request, streaming=True)
        
        # Make the streaming API call
        stream = await self.client.chat.completions.create(**params)
        
        chunk_count = 0
        
        # Process each chunk
        async for chunk in stream:
            chunk_count += 1
            
            # Convert vLLM chunk to our typed streaming response
            choices = []
            for choice in chunk.choices:
                delta_dict = {}
                
                if choice.delta.content is not None:
                    delta_dict["content"] = choice.delta.content
                
                if hasattr(choice.delta, 'role') and choice.delta.role:
                    delta_dict["role"] = choice.delta.role
                
                choices.append(
                    StreamChoice(
                        index=choice.index,
                        delta=delta_dict,
                        finish_reason=choice.finish_reason
                    )
                )
            
            # Build usage info if present (usually in the last chunk)
            usage = None
            if hasattr(chunk, 'usage') and chunk.usage:
                usage = TokenUsage(
                    prompt_tokens=chunk.usage.prompt_tokens,
                    completion_tokens=chunk.usage.completion_tokens,
                    total_tokens=chunk.usage.total_tokens
                )
                
                # Calculate costs (set to 0 for vLLM)
                usage = self._calculate_costs(usage, chunk.model)
            
            yield StreamingResponse(
                id=chunk.id,
                model=chunk.model,
                created=chunk.created,
                choices=choices,
                usage=usage,
            )
        
        logging.debug(f"Streaming complete: {chunk_count} chunks")
