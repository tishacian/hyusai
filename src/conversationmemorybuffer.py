#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 14 16:45:10 2025

@author: kennethezukwoke
"""
import sys
import logging
import warnings

warnings.simplefilter(action="ignore", category=FutureWarning)

# --
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from reasoningmetrics import ReasoningType

# --
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


@dataclass
class Message:
    """Represents a single message in the conversation"""

    role: str  # 'user' or 'assistant'
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict = field(default_factory=dict)


@dataclass
class ConversationMemoryBuffer:
    """Manages conversation history with a fixed-size buffer of recent messages"""

    max_turns: int = 2  # Store last 2 conversation turns
    messages: List[Message] = field(default_factory=list)

    def add_message(
        self, role: str, content: str, metadata: Optional[Dict] = None
    ) -> None:
        """
        Add a new message to the conversation history

        Args:
            role (str): The role of the message sender ('user' or 'assistant')
            content (str): The content of the message
            metadata (Dict, optional): Additional metadata for the message
        """
        try:
            message = Message(
                role=role, content=content, metadata=metadata or {}
            )
            self.messages.append(message)

            # Maintain buffer size by removing older messages if needed
            if (
                len(self.messages) > self.max_turns * 2
            ):  # *2 because each turn has user + assistant
                self.messages = self.messages[-(self.max_turns * 2) :]

            logging.info(
                f"Added message from {role}. Buffer size: {len(self.messages)}"
            )
        except Exception as e:
            logging.error(f"Error adding message to buffer: {e}")

    def get_recent_context(self, num_turns: Optional[int] = None) -> str:
        """
        Get recent conversation context formatted for the LLM

        Args:
            num_turns (int, optional): Number of turns to include. Defaults to max_turns

        Returns:
            str: Formatted conversation context
        """
        try:
            turns = num_turns or self.max_turns
            recent_messages = self.messages[-(turns * 2) :]

            context = []
            for msg in recent_messages:
                prefix = "User" if msg.role == "user" else "Assistant"
                context.append(f"{prefix}: {msg.content}")

            return "\n".join(context)
        except Exception as e:
            logging.error(f"Error getting conversation context: {e}")
            return ""

    def get_last_exchange(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Get the most recent user-assistant exchange

        Returns:
            Tuple[Optional[str], Optional[str]]: (last user message, last assistant response)
        """
        try:
            if len(self.messages) >= 2:
                last_messages = self.messages[-2:]
                if (
                    last_messages[0].role == "user"
                    and last_messages[1].role == "assistant"
                ):
                    return last_messages[0].content, last_messages[1].content
            return None, None
        except Exception as e:
            logging.error(f"Error retrieving last exchange: {e}")
            return None, None

    def clear(self) -> None:
        """Clear the conversation history"""
        self.messages.clear()
        logging.info("Conversation buffer cleared")

    def get_context_with_reasoning(
        self, reasoning_type: "ReasoningType"
    ) -> str:
        """
        Get conversation context with appropriate reasoning template

        Args:
            reasoning_type (ReasoningType): The type of reasoning to apply

        Returns:
            str: Formatted context with reasoning template
        """
        try:
            recent_context = self.get_recent_context()
            if not recent_context:
                return ""

            # Map reasoning types to context prefixes
            reasoning_prefixes = {
                "ReasoningType.FACTUAL": "Previous factual discussion:\n",
                "ReasoningType.ANALYTICAL": "Prior analysis context:\n",
                "ReasoningType.COMPARATIVE": "Previous comparison points:\n",
                "ReasoningType.CAUSAL": "Earlier cause-effect discussion:\n",
                "ReasoningType.HYPOTHETICAL": "Previous hypothetical scenarios:\n",
            }

            prefix = reasoning_prefixes.get(
                str(reasoning_type), "Previous context:\n"
            )
            return f"{prefix}{recent_context}"

        except Exception as e:
            logging.error(f"Error getting reasoning context: {e}")
            return ""

    def __len__(self) -> int:
        """Get the current number of messages in the buffer"""
        return len(self.messages)
