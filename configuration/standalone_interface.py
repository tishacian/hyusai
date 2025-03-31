from pydantic_settings import BaseSettings, SettingsConfigDict

from src.globalvariables import IMG_PATH


class StandaloneInterface(BaseSettings):
    model_config = SettingsConfigDict(protected_namespaces=("standalone_interface_",))

    page_icon: str = "🦙"
    """The page favicon."""

    page_title: str = "RAGGER"
    """The page title."""

    header_title: str = "RAGGER"
    """The header title."""

    ai_chat_logo: str = str(IMG_PATH / "datategy_logo.png")
    """Path of the AI chatbot logo in the chat."""

    human_chat_logo: str = str(IMG_PATH / "aitubo.jpg")
    """Path of the human user logo in the chat."""
