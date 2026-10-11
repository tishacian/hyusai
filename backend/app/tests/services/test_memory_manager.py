from app.core.memory_manager import MemoryManager, count_tokens, message_tokens


def _turn(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def test_count_tokens_never_zero_for_content():
    assert count_tokens("") == 0
    assert count_tokens("bonjour le monde") >= 3
    assert message_tokens(_turn("user", "hi")) > count_tokens("hi")


def test_short_history_passes_through_unchanged():
    manager = MemoryManager()
    history = [_turn("user", "question"), _turn("assistant", "réponse")]
    assert manager.build_chat_context(history, max_tokens=4000) == history


def test_long_history_is_budgeted_with_summary_prefix():
    manager = MemoryManager()
    history = []
    for index in range(40):
        history.append(_turn("user", f"Question {index} " + "détail " * 60))
        history.append(_turn("assistant", f"Réponse {index} " + "contenu " * 60))

    context = manager.build_chat_context(history, max_tokens=1000)

    # Budget respected (modulo the always-kept newest message).
    body = [turn for turn in context if turn["role"] != "system"]
    assert sum(message_tokens(turn) for turn in body) <= 1000 + message_tokens(body[-1])
    # The newest turn is always present and whole.
    assert context[-1]["content"] == history[-1]["content"]
    # Dropped turns are condensed into a leading system summary.
    assert context[0]["role"] == "system"
    assert "Question 0" in context[0]["content"]


def test_newest_message_kept_even_when_oversized():
    manager = MemoryManager()
    history = [
        _turn("user", "ancienne question"),
        _turn("assistant", "très longue réponse " * 500),
    ]
    context = manager.build_chat_context(history, max_tokens=50)
    assert context[-1]["content"] == history[-1]["content"]


def test_get_context_token_budget_uses_real_counter():
    manager = MemoryManager()
    history = [_turn("user", "mot " * 100) for _ in range(10)]
    context = manager.get_context(history, max_tokens=120)
    assert 1 <= len(context) < 10
