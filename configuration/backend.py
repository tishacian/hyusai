from pydantic_settings import BaseSettings, SettingsConfigDict


class Backend(BaseSettings):
    model_config = SettingsConfigDict(protected_namespaces=("settings_",))

    context_length_size: int = -1
    """Force the value of the context length size to the provided value. 
    If you encounter issues in the RAG answers like too long answers with
    repetition, consider tuning this parameter down (8 for example).
    If `-1`, the context length size will be infered using heuristics.
    """

    disable_ocr_for_pdf: bool = False
    """If True, OCR won't be available when processing PDF documents."""

    force_ocr_on_all_pdf: bool = False
    """If True, OCR will be applied to all PDF documents, even text-based documents, 
    ignoring the digital text content.
    `disable_ocr_for_pdf` is expected to be `False` when using this variable.
    """
