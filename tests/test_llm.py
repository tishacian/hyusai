"""
Tests for the LLM module.
"""
import os
import sys
import asyncio
import logging
import pytest
from pathlib import Path
from dotenv import load_dotenv

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm import LLM


# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)


async def test_llm_basic():
    """Test basic LLM functionality with different providers."""
    # Get API keys from environment
    openai_key = os.getenv("OPENAI_API_KEY")
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    
    if not openai_key:
        pytest.skip("OPENAI_API_KEY not found in environment. Skipping OpenAI test.")
    
    if not openrouter_key:
        pytest.skip("OPENROUTER_API_KEY not found in environment. Skipping OpenRouter test.")
    
    # Initialize providers
    llm1 = LLM("openai", api_key=openai_key)
    llm2 = LLM("openrouter", api_key=openrouter_key)

    # Test OpenAI
    response1 = await llm1.generate(
        messages=[
            {"role": "user", "content": "Say 'Hello, I'm working!' in exactly 4 words."}
        ],
        model="gpt-4o-mini"
    )
    print("OpenAI Response:", response1)
    assert response1, "OpenAI should return a response"
    
    print()
    print('-------------------------')
    print('-------------------------')
    
    # Test OpenRouter streaming
    print("OpenRouter Streaming Response: ", end="")
    chunks = []
    async for chunk in llm2.stream_generate(
        messages=[
            {"role": "user", "content": "Count from 1 to 5."},
        ],
        model="openai/gpt-4o-mini"
    ):
        print(chunk, end="")
        chunks.append(chunk)
    
    print()
    assert chunks, "OpenRouter should return streamed chunks"
    print("\n✓ All tests passed!")


# Removed tests for providers other than OpenAI, OpenRouter, and vLLM


async def test_vllm_streaming():
    """Non-streaming completion using provider/model/url from environment (.env)."""
    provider = os.getenv("LLM_PROVIDER", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    url = os.getenv("VLLM_BASE_URL", "").strip()

    if not provider or not model:
        pytest.skip("LLM_PROVIDER or LLM_MODEL not set. Skipping streaming test.")

    prompt = "generate 24 random words"

    # vLLM requires an explicit base_url; others may not
    if provider.lower() == "vllm":
        if not url:
            pytest.skip("VLLM_BASE_URL not set. Skipping vLLM streaming test.")
        llm = LLM(provider=provider, base_url=url)
    else:
        llm = LLM(provider=provider)

    text = await llm.complete(
        prompt=prompt,
        model=model,
        temperature=0.7,
    )

    assert text and text.strip(), "Expected non-empty completion output"


