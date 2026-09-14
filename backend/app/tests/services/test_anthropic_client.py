from types import SimpleNamespace

from app.services.model_clients.anthropic_client import AnthropicClient


def test_generation_options_omit_temperature_for_opus_5():
    assert AnthropicClient._generation_options(
        "claude-opus-5",
        {"temperature": 0.3, "max_tokens": 128, "top_p": 0.9},
    ) == {"top_p": 0.9}


def test_generation_options_keep_temperature_for_older_claude_models():
    assert AnthropicClient._generation_options(
        "claude-3-5-sonnet",
        {"temperature": 0.3, "max_tokens": 128},
    ) == {"temperature": 0.3}


def test_workspace_base_url_can_be_pinned_to_official_anthropic():
    client = AnthropicClient(
        api_key="sk-ant-test",
        base_url=AnthropicClient.DEFAULT_BASE_URL,
    )

    assert client.base_url == "https://api.anthropic.com"


def test_text_content_ignores_adaptive_thinking_blocks():
    blocks = [
        SimpleNamespace(type="thinking", thinking="internal reasoning"),
        SimpleNamespace(type="text", text="READY"),
    ]

    assert AnthropicClient._text_content(blocks) == "READY"


def test_supported_options_filters_fields_missing_from_sdk_signature():
    def create(*, model, messages, max_tokens):
        return model, messages, max_tokens

    assert (
        AnthropicClient._supported_options(
            create,
            {"temperature": 0.3, "top_p": 0.9},
        )
        == {}
    )
