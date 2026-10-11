"""Provider modules for different LLM services.
Only OpenAI is eagerly imported. Others are lazy-loaded on demand.
"""

from .openai_provider import OpenAIProvider

_LAZY_PROVIDERS = {
    "GeminiProvider": ".gemini_provider",
    "OpenRouterProvider": ".openrouter_provider",
    "AnthropicProvider": ".anthropic_provider",
    "DeepSeekProvider": ".deepseek_provider",
    "GroqProvider": ".groq_provider",
    "TogetherProvider": ".together_provider",
    "XAIProvider": ".xai_provider",
    "OllamaProvider": ".ollama_provider",
    "LMStudioProvider": ".lmstudio_provider",
    "AWSBedrockProvider": ".aws_bedrock_provider",
    "AzureOpenAIProvider": ".azure_openai_provider",
    "AzureOpenAIStructuredProvider": ".azure_openai_structured_provider",
    "LangChainProvider": ".langchain_provider",
    "LiteLLMProvider": ".litellm_provider",
    "OpenAIStructuredProvider": ".openai_structured_provider",
    "SarvamProvider": ".sarvam_provider",
    "VLLMProvider": ".vllm_provider",
    "LlamaCppProvider": ".llamacpp_provider",
    "LMDeployProvider": ".lmdeploy_provider",
}


def __getattr__(name):
    if name in _LAZY_PROVIDERS:
        import importlib
        module = importlib.import_module(_LAZY_PROVIDERS[name], package=__name__)
        cls = getattr(module, name)
        globals()[name] = cls
        return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["OpenAIProvider"] + list(_LAZY_PROVIDERS.keys())
