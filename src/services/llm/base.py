from abc import ABC, abstractmethod


class LLMService(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str) -> str:
        """Generate a response given a user prompt and a system prompt."""
