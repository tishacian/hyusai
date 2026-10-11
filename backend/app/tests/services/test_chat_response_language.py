from app.api.v1.endpoints.chat import (
    ChatRequest,
    _apply_response_language_contract,
    _resolve_response_language,
    _response_language_instruction,
    _trivial_bypass_for_language,
)
from app.services.chat_trivial_bypass import TrivialBypass


def test_english_query_overrides_french_ui_locale():
    request = ChatRequest(query="What documents do you have?", ui_locale="fr")

    assert _resolve_response_language(request, request.query) == "en"


def test_french_query_overrides_english_ui_locale():
    request = ChatRequest(query="Quels documents as-tu ?", ui_locale="en")

    assert _resolve_response_language(request, request.query) == "fr"


def test_ambiguous_query_falls_back_to_ui_locale():
    request = ChatRequest(query="ACO150", ui_locale="en")

    assert _resolve_response_language(request, request.query) == "en"


def test_language_contract_keeps_retrieved_content_original():
    payload = {"query": "What documents do you have?", "system_prompt": "Use grounded sources."}

    _apply_response_language_contract(payload, "en")

    assert payload["response_language"] == "en"
    assert "Answer in English" in payload["system_prompt"]
    assert "original language" in payload["system_prompt"]
    assert "Use grounded sources." in payload["system_prompt"]


def test_trivial_bypass_can_follow_response_language():
    bypass = TrivialBypass(content="Bonjour, je vous ecoute.", reason="trivial_greeting")

    assert _trivial_bypass_for_language(bypass, "en").content == "Hello, I'm listening."
    assert _trivial_bypass_for_language(bypass, "fr").content == bypass.content


def test_french_instruction_is_explicit_about_sources():
    instruction = _response_language_instruction("fr")

    assert "Réponds en français" in instruction
    assert "langue d’origine" in instruction
