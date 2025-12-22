"""
Memory Management System for Long-term and Short-term Context
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from app.core.logging import get_logger

logger = get_logger(__name__)


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
            context = conversation_history[-self.short_term_threshold:]
        else:
            # Long-term: All messages (up to threshold)
            context = conversation_history[-self.long_term_threshold:] if len(conversation_history) > self.long_term_threshold else conversation_history
        
        # If token limit is specified, truncate from beginning
        if max_tokens and context:
            # Rough estimate: 1 token ≈ 4 characters
            total_chars = sum(len(msg.get("content", "")) for msg in context)
            estimated_tokens = total_chars / 4
            
            if estimated_tokens > max_tokens:
                # Remove oldest messages until under token limit
                while context and estimated_tokens > max_tokens:
                    removed = context.pop(0)
                    estimated_tokens -= len(removed.get("content", "")) / 4
        
        return context
    
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

