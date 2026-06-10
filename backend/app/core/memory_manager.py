"""
Memory Management System for Long-term and Short-term Context
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from app.core.logging import get_logger

logger = get_logger(__name__)

_tiktoken_encoder = None
_tiktoken_failed = False


def _encoder():
    """Cached tiktoken encoder; falls back to chars/4 when unavailable."""
    global _tiktoken_encoder, _tiktoken_failed
    if _tiktoken_encoder is not None or _tiktoken_failed:
        return _tiktoken_encoder
    try:
        import tiktoken

        _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
    except Exception:  # noqa: BLE001 - estimation must never break chat.
        _tiktoken_failed = True
        logger.warning("tiktoken unavailable, falling back to chars/4 token estimate")
    return _tiktoken_encoder


def count_tokens(text: str) -> int:
    """Real token count when tiktoken is available, chars/4 otherwise."""
    content = str(text or "")
    if not content:
        return 0
    encoder = _encoder()
    if encoder is not None:
        try:
            return len(encoder.encode(content, disallowed_special=()))
        except Exception:  # noqa: BLE001
            pass
    return max(1, len(content) // 4)


def message_tokens(message: Dict[str, str]) -> int:
    # ~4 tokens of per-message chat scaffolding (role, separators).
    return count_tokens(message.get("content", "")) + 4


class MemoryManager:
    """Manages conversation memory (long-term and short-term)"""

    def __init__(self):
        self.short_term_threshold = 10  # Messages to keep in short-term
        self.long_term_threshold = 100  # Messages to keep in long-term

    def get_context(
        self,
        conversation_history: List[Dict[str, str]],
        memory_type: str = "long_term",
        max_tokens: Optional[int] = None
    ) -> List[Dict[str, str]]:
        """
        Get conversation context based on memory type

        Args:
            conversation_history: List of conversation messages
            memory_type: "long_term" or "short_term"
            max_tokens: Optional token limit for context

        Returns:
            Filtered conversation history
        """
        if memory_type == "short_term":
            # Short-term: Only last N messages
            context = list(conversation_history[-self.short_term_threshold:])
        else:
            # Long-term: All messages (up to threshold)
            context = list(
                conversation_history[-self.long_term_threshold:]
                if len(conversation_history) > self.long_term_threshold
                else conversation_history
            )

        # If token limit is specified, truncate from beginning
        if max_tokens and context:
            estimated_tokens = sum(message_tokens(msg) for msg in context)
            while len(context) > 1 and estimated_tokens > max_tokens:
                removed = context.pop(0)
                estimated_tokens -= message_tokens(removed)

        return context

    def build_chat_context(
        self,
        conversation_history: List[Dict[str, str]],
        *,
        max_tokens: int,
    ) -> List[Dict[str, str]]:
        """Token-budgeted history for the chat prompt.

        Keeps the most recent turns within ``max_tokens``; when older turns are
        dropped, a compact system summary of them is prepended so long-running
        sessions keep their early decisions without paying their full length.
        The newest message is always kept whole.
        """
        if not conversation_history:
            return []
        kept: List[Dict[str, str]] = []
        budget = max(1, int(max_tokens))
        used = 0
        for message in reversed(conversation_history):
            cost = message_tokens(message)
            if kept and used + cost > budget:
                break
            kept.append(message)
            used += cost
        kept.reverse()
        dropped = conversation_history[: len(conversation_history) - len(kept)]
        if not dropped:
            return kept
        summary = self.summarize_conversation(dropped)
        if not summary:
            return kept
        return [
            {
                "role": "system",
                "content": f"Résumé des échanges précédents (tronqués): {summary}",
            },
            *kept,
        ]

    def summarize_conversation(
        self,
        conversation_history: List[Dict[str, str]],
        summary_points: int = 5
    ) -> str:
        """
        Generate a summary of conversation for long-term memory compression

        Args:
            conversation_history: List of conversation messages
            summary_points: Number of key points to extract

        Returns:
            Summary string
        """
        if not conversation_history:
            return ""

        # Simple extraction: Get first and last user queries + key topics
        user_messages = [msg["content"] for msg in conversation_history if msg["role"] == "user"]

        if len(user_messages) <= summary_points:
            summary = " | ".join(user_messages)
        else:
            # Take first, middle, and last queries
            summary_parts = [
                user_messages[0],
                user_messages[len(user_messages) // 2] if len(user_messages) > 2 else "",
                user_messages[-1]
            ]
            summary = " | ".join([part for part in summary_parts if part])

        return summary


# Global memory manager instance
memory_manager = MemoryManager()
