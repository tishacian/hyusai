"""Azure OpenAI uses its own endpoint, deployment and authentication scheme."""
from app.services.model_clients.openai_client import OpenAIClient


class AzureOpenAIClient(OpenAIClient):
    def __init__(self, *, api_key: str, endpoint: str, api_version: str, max_retries: int | None = None):
        super().__init__(api_key=api_key, base_url=endpoint, max_retries=max_retries)
        self.api_version = api_version

    def _sdk_client(self):
        from openai import AsyncAzureOpenAI

        return AsyncAzureOpenAI(
            api_key=self.api_key,
            azure_endpoint=self.base_url,
            api_version=self.api_version,
            **({"max_retries": self.max_retries} if self.max_retries is not None else {}),
        )
