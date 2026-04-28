from typing import Literal

from pydantic import BaseModel, Field


class PDFIngestOptions(BaseModel):
    processing_method: Literal["markdown_converter", "ocr"] = Field(
        "markdown_converter",
        description=(
            "Primary text extraction strategy. "
            "'markdown_converter' preserves document structure (headings, tables, lists) as Markdown — "
            "best for digitally-created PDFs. "
            "'ocr' uses pixel-level text extraction via Tesseract or equivalent — "
            "required for scanned documents or images embedded in PDFs."
        ),
    )
    enable_fallback: bool = Field(
        True,
        description=(
            "Automatically fall back to the alternative method when the primary method fails "
            "(e.g. markdown_converter produces empty output on a scanned page). "
            "Disable to surface extraction failures explicitly."
        ),
    )
    fallback_method: Literal["markdown_converter", "ocr"] = Field(
        "ocr",
        description="Extraction strategy used when the primary method fails and enable_fallback=True.",
    )
    force_ocr: bool = Field(
        False,
        description=(
            "Force OCR on every page even when the PDF contains extractable text. "
            "Useful when the embedded text is garbled or misencoded."
        ),
    )
    ocr_dpi: int = Field(
        150,
        ge=72,
        le=600,
        description=(
            "Rendering resolution (dots per inch) used when rasterising PDF pages for OCR. "
            "Higher values improve accuracy on small or dense text at the cost of processing time. "
            "72 is screen resolution; 300 is print quality."
        ),
    )
    extract_images: bool = Field(
        False,
        description=(
            "Include extracted images from the PDF in the output. "
            "Images are saved alongside the text and referenced by path."
        ),
    )
    extract_tables: bool = Field(
        True,
        description=(
            "Detect and preserve table structure in the output. "
            "Tables are serialised as Markdown tables when possible."
        ),
    )
    enable_vlm: bool = Field(
        False,
        description=(
            "Use a Vision Language Model (VLM) to semantically describe page content "
            "beyond raw text extraction — useful for pages that are mostly visual "
            "(diagrams, charts, infographics)."
        ),
    )
    vlm_model: str = Field(
        "vllm-smolvlm-256m",
        description=(
            "VLM model identifier used when enable_vlm=True. "
            "Must be available in the local model registry or reachable via the inference endpoint."
        ),
    )
