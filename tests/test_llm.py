"""
Tests for the LLM module.
"""
import os
import sys
import asyncio
import logging
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
        logging.warning("OPENAI_API_KEY not found in environment. Skipping OpenAI test.")
        return
    
    if not openrouter_key:
        logging.warning("OPENROUTER_API_KEY not found in environment. Skipping OpenRouter test.")
        return
    
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


async def test_llm_conversation():
    """Test a conversation between two LLMs."""
    openai_key = os.getenv("OPENAI_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    
    if not openai_key or not anthropic_key:
        logging.warning("API keys not found. Skipping conversation test.")
        return
    
    llm1 = LLM("openai", api_key=openai_key)
    llm2 = LLM("anthropic", api_key=anthropic_key)
    
    # First LLM asks a question
    response1 = await llm1.generate(
        messages=[
            {"role": "user", "content": "You are about to get connected with another AI. Ask them to share an interesting fact about space."}
        ],
        model="gpt-4o-mini"
    )
    print("OpenAI says:", response1)
    
    # Second LLM responds
    response2 = await llm2.generate(
        messages=[
            {"role": "user", "content": response1}
        ],
        model="claude-3-haiku-20240307"
    )
    print("Claude responds:", response2)


async def test_multiple_providers():
    """Test initialization of multiple providers."""
    providers_to_test = [
        ("openai", "OPENAI_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("gemini", "GEMINI_API_KEY"),
        ("groq", "GROQ_API_KEY"),
    ]
    
    for provider_name, env_key in providers_to_test:
        api_key = os.getenv(env_key)
        if api_key:
            try:
                llm = LLM(provider_name, api_key=api_key)
                print(f"✓ Successfully initialized {provider_name} provider")
            except Exception as e:
                print(f"✗ Failed to initialize {provider_name}: {e}")
        else:
            print(f"- Skipping {provider_name} (no API key)")


async def main():
    """Run all tests."""
    print("="*50)
    print("Testing LLM Module")
    print("="*50)
    
    print("\n1. Testing basic functionality...")
    await test_llm_basic()
    
    print("\n2. Testing multi-provider initialization...")
    await test_multiple_providers()
    
    print("\n3. Testing LLM conversation...")
    await test_llm_conversation()
    
    print("\n" + "="*50)
    print("All tests completed!")
    print("="*50)


if __name__ == "__main__":
    asyncio.run(main())