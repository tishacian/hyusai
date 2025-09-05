"""
AWS Bedrock provider implementation.
"""
import json
import time
import logging
import os
import re
from collections.abc import AsyncGenerator

import boto3

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

logger = logging.getLogger(__name__)

PROVIDERS = [
    "ai21", "amazon", "anthropic", "cohere", "meta", "mistral", "stability", "writer", 
    "deepseek", "gpt-oss", "perplexity", "snowflake", "titan", "command", "j2", "llama"
]


def extract_provider(model: str) -> str:
    """Extract provider from model identifier."""
    for provider in PROVIDERS:
        if re.search(rf"\b{re.escape(provider)}\b", model):
            return provider
    raise ValueError(f"Unknown provider in model: {model}")


class AWSBedrockProvider(LLMProvider):
    """AWS Bedrock LLM provider implementation."""
    
    # Default model
    DEFAULT_MODEL = "anthropic.claude-3-sonnet-20240229"
    
    def __init__(
        self, 
        api_key: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_region: str = "us-east-1",
        **kwargs
    ):
        """Initialize the AWS Bedrock provider."""
        self.aws_access_key_id = aws_access_key_id or os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = aws_secret_access_key or os.getenv("AWS_SECRET_ACCESS_KEY")
        self.aws_region = aws_region or os.getenv("AWS_REGION", "us-east-1")
        
        if not self.aws_access_key_id or not self.aws_secret_access_key:
            raise ValueError("AWS credentials are required")
        
        self.client = boto3.client(
            "bedrock-runtime",
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            region_name=self.aws_region
        )
    
    def _calculate_costs(self, usage: TokenUsage, model: str) -> TokenUsage:
        """Calculate costs based on model pricing."""
        PRICING = {
            "anthropic": {"input": 0.008, "output": 0.024},
            "amazon": {"input": 0.0008, "output": 0.0016},
            "meta": {"input": 0.00075, "output": 0.00325},
            "mistral": {"input": 0.00015, "output": 0.00055},
        }
        
        provider = extract_provider(model)
        prices = PRICING.get(provider, {"input": 0.001, "output": 0.002})
        
        usage.prompt_cost = (usage.prompt_tokens / 1000) * prices["input"]
        usage.completion_cost = (usage.completion_tokens / 1000) * prices["output"]
        usage.total_cost = usage.prompt_cost + usage.completion_cost
        
        return usage
    
    async def generate(
        self,
        request: CompletionRequest
    ) -> CompletionResponse:
        """Generate a response using AWS Bedrock."""
        model = request.model or os.getenv("AWS_BEDROCK_DEFAULT_MODEL", self.DEFAULT_MODEL)
        provider = extract_provider(model)
        start_time = time.time()
        if provider == "anthropic":
            input_body = self._prepare_anthropic_input(request.messages, request.temperature, request.max_tokens)
        elif provider == "amazon":
            input_body = self._prepare_amazon_input(request.messages, request.temperature, request.max_tokens)
        elif provider == "meta":
            input_body = self._prepare_meta_input(request.messages, request.temperature, request.max_tokens)
        elif provider == "mistral":
            input_body = self._prepare_mistral_input(request.messages, request.temperature, request.max_tokens)
        else:
            input_body = self._prepare_generic_input(request.messages, request.temperature, request.max_tokens)
        
        response = self.client.invoke_model(
            body=json.dumps(input_body),
            modelId=model,
            accept="application/json",
            contentType="application/json"
        )
        
        response_ms = (time.time() - start_time) * 1000
        content = self._parse_response(response, provider)
        
        message = Message(
            role=MessageRole.ASSISTANT,
            content=content
        )
        
        choice = Choice(
            index=0,
            message=message,
            finish_reason="stop"
        )
        
        prompt_text = " ".join([msg.get("content", "") for msg in request.messages])
        prompt_tokens = max(len(prompt_text.split()) * 1.3, 1)
        completion_tokens = max(len(content.split()) * 1.3, 1) if content else 0
        
        usage = TokenUsage(
            prompt_tokens=int(prompt_tokens),
            completion_tokens=int(completion_tokens),
            total_tokens=int(prompt_tokens + completion_tokens)
        )
        
        usage = self._calculate_costs(usage, model)
        
        return CompletionResponse(
            id=f"bedrock-{int(time.time())}",
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
        """Stream a response using AWS Bedrock."""
        model = request.model
        provider = extract_provider(model)
        
        # Prepare input based on provider
        if provider == "anthropic":
            input_body = self._prepare_anthropic_input(request.messages, request.temperature, request.max_tokens)
        elif provider == "amazon":
            input_body = self._prepare_amazon_input(request.messages, request.temperature, request.max_tokens)
        elif provider == "meta":
            input_body = self._prepare_meta_input(request.messages, request.temperature, request.max_tokens)
        elif provider == "mistral":
            input_body = self._prepare_mistral_input(request.messages, request.temperature, request.max_tokens)
        else:
            input_body = self._prepare_generic_input(request.messages, request.temperature, request.max_tokens)
        
        response = self.client.invoke_model_with_response_stream(
            body=json.dumps(input_body),
            modelId=model,
            accept="application/json",
            contentType="application/json"
        )
        
        chunk_count = 0
        accumulated_content = ""
        
        for event in response["body"]:
            chunk_count += 1
            chunk = json.loads(event["chunk"]["bytes"])
            text = self._extract_chunk_text(chunk, provider)
            
            if text:
                accumulated_content += text
                
                choice = StreamChoice(
                    index=0,
                    delta={"content": text},
                    finish_reason=None
                )
                
                yield StreamingResponse(
                    id=f"bedrock-{int(time.time())}-{chunk_count}",
                    model=model,
                    created=int(time.time()),
                    choices=[choice]
                )
        
        if accumulated_content:
            prompt_text = " ".join([msg.get("content", "") for msg in request.messages])
            prompt_tokens = max(len(prompt_text.split()) * 1.3, 1)
            completion_tokens = max(len(accumulated_content.split()) * 1.3, 1)
            
            usage = TokenUsage(
                prompt_tokens=int(prompt_tokens),
                completion_tokens=int(completion_tokens),
                total_tokens=int(prompt_tokens + completion_tokens)
            )
            
            usage = self._calculate_costs(usage, model)
            
            choice = StreamChoice(
                index=0,
                delta={},
                finish_reason="stop"
            )
            
            yield StreamingResponse(
                id=f"bedrock-{int(time.time())}-final",
                model=model,
                created=int(time.time()),
                choices=[choice],
                usage=usage
            )
    
    def _prepare_anthropic_input(self, messages: list[dict[str, str]], temperature: float | None, max_tokens: int | None) -> dict:
        """Prepare input for Anthropic models."""
        formatted_messages = []
        for msg in messages:
            if msg["role"] != "system":
                formatted_messages.append({
                    "role": msg["role"],
                    "content": [{"type": "text", "text": msg["content"]}]
                })
        
        return {
            "messages": formatted_messages,
            "max_tokens": max_tokens or 2000,
            "temperature": temperature or 0.1,
            "anthropic_version": "bedrock-2023-05-31"
        }
    
    def _prepare_amazon_input(self, messages: list[dict[str, str]], temperature: float | None, max_tokens: int | None) -> dict:
        """Prepare input for Amazon models."""
        if any("nova" in msg.get("model", "").lower() for msg in [{}]):  # Check if Nova model
            return {
                "messages": [{"role": msg["role"], "content": msg["content"]} for msg in messages],
                "max_tokens": max_tokens or 5000,
                "temperature": temperature or 0.1
            }
        else:
            prompt = self._format_messages_generic(messages)
            return {
                "inputText": prompt,
                "textGenerationConfig": {
                    "maxTokenCount": max_tokens or 5000,
                    "temperature": temperature or 0.1
                }
            }
    
    def _prepare_meta_input(self, messages: list[dict[str, str]], temperature: float | None, max_tokens: int | None) -> dict:
        """Prepare input for Meta models."""
        prompt = self._format_messages_generic(messages)
        return {
            "prompt": prompt,
            "max_gen_len": max_tokens or 5000,
            "temperature": temperature or 0.1
        }
    
    def _prepare_mistral_input(self, messages: list[dict[str, str]], temperature: float | None, max_tokens: int | None) -> dict:
        """Prepare input for Mistral models."""
        prompt = self._format_messages_generic(messages)
        return {
            "prompt": prompt,
            "max_tokens": max_tokens or 5000,
            "temperature": temperature or 0.1
        }
    
    def _prepare_generic_input(self, messages: list[dict[str, str]], temperature: float | None, max_tokens: int | None) -> dict:
        """Prepare generic input for other models."""
        prompt = self._format_messages_generic(messages)
        return {
            "prompt": prompt,
            "max_tokens": max_tokens or 2000,
            "temperature": temperature or 0.1
        }
    
    def _format_messages_generic(self, messages: list[dict[str, str]]) -> str:
        """Format messages for generic models."""
        formatted = []
        for msg in messages:
            role = msg["role"].capitalize()
            content = msg["content"]
            formatted.append(f"{role}: {content}")
        return "\n".join(formatted)
    
    def _parse_response(self, response: dict, provider: str) -> str:
        """Parse response from Bedrock API."""
        response_body = response.get("body").read().decode()
        response_json = json.loads(response_body)
        
        if provider == "anthropic":
            return response_json.get("content", [{"text": ""}])[0].get("text", "")
        elif provider == "amazon":
            return response_json.get("completion", "") or response_json.get("outputText", "")
        elif provider == "meta":
            return response_json.get("generation", "")
        elif provider == "mistral":
            return response_json.get("outputs", [{"text": ""}])[0].get("text", "")
        else:
            return response_json.get("completions", [{"data": {"text": ""}}])[0].get("data", {}).get("text", "")
    
    def _extract_chunk_text(self, chunk: dict, provider: str) -> str:
        """Extract text from streaming chunk."""
        if provider == "anthropic":
            return chunk.get("delta", {}).get("text", "")
        elif provider == "amazon":
            return chunk.get("outputText", "")
        elif provider == "meta":
            return chunk.get("generation", "")
        elif provider == "mistral":
            return chunk.get("outputs", [{"text": ""}])[0].get("text", "")
        else:
            return chunk.get("completion", "")