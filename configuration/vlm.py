from pydantic_settings import BaseSettings, SettingsConfigDict


class VLM(BaseSettings):
    model_config = SettingsConfigDict(protected_namespaces=("settings_",))

    enable_vlm: bool = False
    """
    Whether to enable VLM image analysis for PDF processing.
    """

    vlm_model: str = "vllm-smolvlm-256m"
    """
    VLM model to use for image analysis.
    """

    vlm_workers: int = 2
    """
    Number of VLM workers for concurrent image processing.
    """

    max_workers: int = 16
    """
    Maximum number of workers for PDF processing.
    """ 