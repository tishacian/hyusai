import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

image_path = Path(__file__).parent.parent / "image"


class StandaloneInterfaceConfig(BaseSettings):
    model_config = SettingsConfigDict(protected_namespaces=("standalone_interface_",))

    page_icon: str = "🦙"
    """The page favicon."""

    page_title: str = "OmniRAG"
    """The page title."""

    header_title: str = "OmniRAG"
    """The header title."""

    ai_chat_logo: str = str((image_path / "datategy_logo.png").resolve())
    """Path of the AI chatbot logo in the chat."""

    human_chat_logo: str = str((image_path / "aitubo.jpg").resolve())
    """Path of the human user logo in the chat."""

    hide_rag_params_config: bool = False
    """If True, the section where the user parametrize the RAG steps will be hidden."""

    forced_vdb: str = "None"
    """Force the RAG to use the provided Vector DataBase as context (the section where 
    the user parametrize the RAG steps per consequent).
    If `"None"`, the user will be asked to create/select the desired Vector DataBase.
    """

    default_gpu_model: str = "neuralmagic/Meta-Llama-3.1-8B-Instruct-quantized.w4a16"
    """Default GPU model."""

    cookie_name: str = "omnirag_auth"
    """Name of the authentification cookie."""

    cookie_key: str = secrets.token_hex(32)
    """Secret key for the authentification cookie.
    Consider setting this to a set value using a private .env file to fully benefit from
    the authentification cookie after restart.
    """

    cookie_expiry_days: int = 1
    """Number of days the authentification cookie will be valid."""
