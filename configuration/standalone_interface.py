from pydantic_settings import BaseSettings, SettingsConfigDict

from src.globalvariables import IMG_PATH, GPUModels


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

    hide_rag_params_config: bool = False
    """If True, the section where the user parametrize the RAG steps will be hidden."""

    forced_vdb: str = "None"
    """Force the RAG to use the provided Vector DataBase as context (the section where 
    the user parametrize the RAG steps per consequent).
    If `"None"`, the user will be asked to create/select the desired Vector DataBase.
    """

    default_gpu_model: GPUModels = GPUModels.LLAMA31_8B
    """Default GPU model."""

    context_length_size: int = -1
    """Force the value of the context length size to the provided value. 
    If you encounter issues in the RAG answers like too long answers with
    repetition, consider tuning this parameter down (8 for example).
    If `-1`, the context length size will be infered using heuristics.
    """
