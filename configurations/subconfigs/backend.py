from pydantic import BaseModel


class BackendConfig(BaseModel):
    disable_ocr_for_pdf: bool = False
    """If True, OCR won't be available when processing PDF documents."""

    force_ocr_on_all_pdf: bool = False
    """If True, OCR will be applied to all PDF documents, even text-based documents, 
    ignoring the digital text content.
    `disable_ocr_for_pdf` is expected to be `False` when using this variable.
    """

    disable_file_saving: bool = False
    """If True, disables saving of all output files (images, markdown, xlsx, etc.).
    This is useful for processing documents without creating output files.
    """
