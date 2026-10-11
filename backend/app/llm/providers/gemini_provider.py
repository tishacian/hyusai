"""
Google Gemini LLM provider implementation.
"""
import os
import time
import logging
import asyncio
import google.generativeai as genai
from collections.abc import AsyncGenerator

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


class GeminiProvider(LLMProvider):
    """
    Google Gemini API provider implementation.

    Handles communication with Google's Gemini API for text generation.
    Uses Pydantic models for type-safe request/response handling.
    """

    # Default base URL for Gemini API
    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
    
    # Default models for Gemini
    DEFAULT_MODEL = "gemini-2.0-flash-exp"
    
    # Model pricing per 1000 tokens (approximate)
    MODEL_PRICING = {
        "gemini-2.0-flash": {"input": 0.00015, "output": 0.0006},
        "gemini-2.0-flash-exp": {"input": 0.00015, "output": 0.0006},
        "gemini-1.5-pro": {"input": 0.00125, "output": 0.005},
        "gemini-1.5-flash": {"input": 0.000075, "output": 0.0003},
        "gemini-1.0-pro": {"input": 0.0005, "output": 0.0015},
    }

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        """
        Initialize the Gemini provider.

        Args:
            api_key: Gemini API key (defaults to GEMINI_API_KEY environment variable)
            base_url: Gemini API base URL (defaults to GEMINI_BASE_URL environment variable or hardcoded default)
        """
        # Setup API key
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("Gemini API key is required")
            
        self.base_url = base_url or os.getenv("GEMINI_BASE_URL", self.DEFAULT_BASE_URL)

        # Configure the Google GenAI client
        genai.configure(api_key=self.api_key)

    def _get_model(self, model_name: str):
        """
        Get the Gemini model instance based on model name.

        Args:
            model_name: Name of the Gemini model to use

        Returns:
            Gemini model instance
        """
        return genai.GenerativeModel(model_name)
    
    def _prepare_api_params(self, request: CompletionRequest) -> tuple[str, list, dict]:
        """
        Prepare parameters for Gemini API call.
        
        Args:
            request: Validated CompletionRequest
            
        Returns:
            Tuple of (model, messages, generation_config)
        """
        # Use default model if not specified
        model = request.model or os.getenv("GEMINI_DEFAULT_MODEL", self.DEFAULT_MODEL)
        
        # Convert messages to Gemini format
        gemini_messages = self._convert_messages_to_gemini_format(request.messages_as_dicts())
        
        # Prepare generation config
        generation_config = {}
        
        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        
        if request.max_tokens is not None:
            generation_config["max_output_tokens"] = request.max_tokens
        
        if request.top_p is not None:
            generation_config["top_p"] = request.top_p
        
        if request.stop:
            generation_config["stop_sequences"] = request.stop
        
        return model, gemini_messages, generation_config
    
    def _calculate_costs(self, usage: TokenUsage, model: str) -> TokenUsage:
        """
        Calculate costs based on model pricing.
        
        Args:
            usage: Token usage object
            model: Model name
            
        Returns:
            Updated usage with costs
        """
        # Find matching pricing
        for model_key, pricing in self.MODEL_PRICING.items():
            if model_key in model.lower():
                usage.prompt_cost = usage.prompt_tokens * pricing["input"] / 1000
                usage.completion_cost = usage.completion_tokens * pricing["output"] / 1000
                usage.total_cost = usage.prompt_cost + usage.completion_cost
                break
        
        return usage

    async def generate(
        self,
        request: CompletionRequest
    ) -> CompletionResponse:
        """
        Generate a response using Gemini's API.

        Args:
            request: Validated CompletionRequest with all parameters

        Returns:
            CompletionResponse with choices, usage, and metadata
        """
        # Prepare API parameters
        model, gemini_messages, generation_config = self._prepare_api_params(request)
        
        # Initialize the model
        gemini_model = self._get_model(model)
        
        # Track timing
        start_time = time.time()
        
        # Create a wrapper around the synchronous API call to make it async
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: gemini_model.generate_content(
                gemini_messages,
                generation_config=generation_config,
            )
        )
        
        # Calculate response time
        response_ms = (time.time() - start_time) * 1000
        
        # Check for a successful response
        if hasattr(response, "text") and response.text:
            content = response.text
        else:
            logging.error(f"Unexpected response format from Gemini: {response}")
            content = ""
        
        # Create message
        message = Message(
            role=MessageRole.ASSISTANT,
            content=content
        )
        
        # Create choice
        choice = Choice(
            index=0,
            message=message,
            finish_reason="stop"
        )
        
        # Estimate token usage (Gemini doesn't provide exact counts)
        # This is a rough approximation
        prompt_text = " ".join([msg.get("content", "") for msg in request.messages_as_dicts()])
        prompt_tokens = max(len(prompt_text.split()) * 1.3, 1)  # Rough approximation
        completion_tokens = max(len(content.split()) * 1.3, 1) if content else 0
        
        usage = TokenUsage(
            prompt_tokens=int(prompt_tokens),
            completion_tokens=int(completion_tokens),
            total_tokens=int(prompt_tokens + completion_tokens)
        )
        
        # Calculate costs
        usage = self._calculate_costs(usage, model)
        
        return CompletionResponse(
            id=f"gemini-{int(time.time())}",
            model=model,
            created=int(time.time()),
            choices=[choice],
            usage=usage,
            response_ms=response_ms
        )

    async def stream_generate(
        self,
        request: CompletionRequest
    ) -> AsyncGenerator[StreamingResponse, None]:
        """
        Stream a response using Gemini's API.

        Args:
            request: Validated CompletionRequest with all parameters

        Returns:
            AsyncGenerator yielding StreamingResponse chunks
        """
        # Prepare API parameters
        model, gemini_messages, generation_config = self._prepare_api_params(request)
        
        logging.debug(f"Starting Gemini streaming with model: {model}")
        
        # Initialize the model
        gemini_model = self._get_model(model)
        
        # Create a wrapper around the synchronous API call to make it stream
        loop = asyncio.get_event_loop()
        stream_response = await loop.run_in_executor(
            None,
            lambda: gemini_model.generate_content(
                gemini_messages,
                generation_config=generation_config,
                stream=True
            )
        )
        
        chunk_count = 0
        accumulated_content = ""
        total_completion_tokens = 0
        
        # Stream the content
        async for chunk in self._stream_async_generator(stream_response):
            if hasattr(chunk, "text") and chunk.text:
                chunk_count += 1
                accumulated_content += chunk.text
                
                # Estimate tokens for this chunk
                chunk_tokens = max(len(chunk.text.split()) * 1.3, 1)
                total_completion_tokens += chunk_tokens
                
                # Create streaming choice
                choice = StreamChoice(
                    index=0,
                    delta={"content": chunk.text},
                    finish_reason=None
                )
                
                yield StreamingResponse(
                    id=f"gemini-{int(time.time())}-{chunk_count}",
                    model=model,
                    created=int(time.time()),
                    choices=[choice]
                )
                
                if chunk_count % 10 == 0:
                    logging.debug(f"Gemini streaming: received {chunk_count} chunks so far")
        
        # Send final chunk with usage info
        if chunk_count > 0:
            # Estimate final usage
            prompt_text = " ".join([msg.get("content", "") for msg in request.messages_as_dicts()])
            prompt_tokens = max(len(prompt_text.split()) * 1.3, 1)
            
            usage = TokenUsage(
                prompt_tokens=int(prompt_tokens),
                completion_tokens=int(total_completion_tokens),
                total_tokens=int(prompt_tokens + total_completion_tokens)
            )
            
            # Calculate costs
            usage = self._calculate_costs(usage, model)
            
            # Final chunk with finish reason and usage
            choice = StreamChoice(
                index=0,
                delta={},
                finish_reason="stop"
            )
            
            yield StreamingResponse(
                id=f"gemini-{int(time.time())}-final",
                model=model,
                created=int(time.time()),
                choices=[choice],
                usage=usage
            )
        
        logging.debug(f"Gemini streaming complete: {chunk_count} chunks total")

    def _convert_messages_to_gemini_format(self, messages: list[dict]) -> list[dict[str, object]] | str:
        """
        Convert OpenAI-style messages to Gemini format.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys

        Returns:
            List of messages in Gemini format or a string for single message
        """
        # For simple use cases, we can just extract the content
        # This is a simplified version, as Gemini's API accepts various formats
        if len(messages) == 1:
            return messages[0].get("content", "")

        # For chat format, we can use "contents" with role mapping
        # This is a simplified approach and may need refinement for specific use cases
        role_mapping = {
            "system": "user",  # Gemini doesn't have a distinct system role
            "user": "user",
            "assistant": "model"
        }

        # Create a proper chat history
        gemini_messages: list[dict[str, object]] = []
        for msg in messages:
            role = role_mapping.get(msg.get("role", "user"), "user")
            content = msg.get("content", "")
            if content:  # Only add non-empty messages
                gemini_messages.append({"role": role, "parts": [{"text": content}]})

        return gemini_messages

    async def _stream_async_generator(self, sync_generator):
        """
        Convert a synchronous generator to an async generator.

        Args:
            sync_generator: A synchronous generator to convert

        Returns:
            An async generator that yields the same items
        """
        loop = asyncio.get_event_loop()
        for item in sync_generator:
            # Yield control to the event loop briefly to avoid blocking
            await asyncio.sleep(0)
            yield item
