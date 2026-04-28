from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_image_path = Path(__file__).parent.parent.parent / "image"


class UIConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UI_")

    page_title: str = "OmniRAG"
    page_icon: str = "🦙"
    header_title: str = "OmniRAG"
    ai_chat_logo: str = str((_image_path / "datategy_logo.png").resolve())
    human_chat_logo: str = str((_image_path / "aitubo.jpg").resolve())
    hide_rag_params: bool = False
    forced_collection: str = "None"
    default_gpu_model: str = "neuralmagic/Meta-Llama-3.1-8B-Instruct-quantized.w4a16"
