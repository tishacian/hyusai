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

    skip_large_images: bool = True
    """
    If True, skip VLM analysis for images that are too large.
    """

    max_model_len: int = 8192
    """
    Maximum model length for vLLM models.
    """

    gpu_memory_utilization: float = 0.9
    """
    GPU memory utilization for vLLM models (0.0 to 1.0).
    """

    temperature: float = 0.1
    """
    Temperature for VLM text generation (0.0 to 2.0).
    """

    max_tokens: int = 512
    """
    Maximum tokens to generate for VLM responses.
    """

    top_p: float = 0.9
    """
    Top-p sampling parameter for VLM generation (0.0 to 1.0).
    """

    frequency_penalty: float = 1.0
    """
    Frequency penalty for VLM generation.
    """

    presence_penalty: float = 0.5
    """
    Presence penalty for VLM generation.
    """

    repetition_penalty: float = 1.2
    """
    Repetition penalty for VLM generation.
    """

    max_image_size: int = 128
    """
    Maximum image size for VLM processing (pixels).
    """

    min_image_size: int = 64
    """
    Minimum image size for VLM processing (pixels).
    """

    max_tokens_limit: int = 3000
    """
    Maximum tokens limit for image processing.
    """

    jpeg_quality_levels: list = [30, 20, 15, 10, 5]
    """
    JPEG quality levels to try for image compression.
    """

    device: str = "auto"
    """
    Device to use for VLM processing (auto, cuda, cpu, mps).
    """

    use_flash_attention: bool = True
    """
    Whether to use flash attention for transformers models.
    """

    torch_dtype: str = "auto"
    """
    Torch data type for model loading (auto, float16, bfloat16, float32).
    """ 