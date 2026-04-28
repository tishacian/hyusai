from openai import AsyncOpenAI

from .base import LLMService


class OpenAIService(LLMService):
    def __init__(
        self,
        model_name: str,
        temperature: float,
        max_tokens: int,
        top_p: float | None,
    ):
        self.client = AsyncOpenAI()  # reads OPENAI_API_KEY from environment
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p

    async def generate(self, prompt: str, system_prompt: str) -> str:
        kwargs = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.top_p is not None:
            kwargs["top_p"] = self.top_p
        response = await self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content
