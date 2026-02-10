import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from tempfile import NamedTemporaryFile

from langchain_community.document_loaders import (
    CSVLoader,
    Docx2txtLoader,
    EverNoteLoader,
    TextLoader,
    UnstructuredEPubLoader,
    UnstructuredHTMLLoader,
    UnstructuredMarkdownLoader,
    UnstructuredODTLoader,
    UnstructuredPowerPointLoader,
)
from tqdm import tqdm

from connections.storage import fs
from src.customdocloader import MyEmlLoader, OCRPDFLoader
from src.globalvariables import PDFProcessingConfig, VLMConfig
from src.markdownconverter import markdown_converter
from src.utils import configure_tesseract

logger = logging.getLogger(__name__)

# Configure tesseract for OCR functionality
tesseract_path, tesseract_available = configure_tesseract()


class Document:
    def __init__(self, content: str, metadata: dict | None = None) -> None:
        """Initialize a Document instance.

        Parameters
        ----------
        content : str
            The document content.
        metadata : dict, optional
            Document metadata dictionary.
        """
        self.page_content = content
        self.metadata = metadata or {}


class PDFMarkdownLoader:
    """Generalized PDF loader supporting multiple processing backends."""

    def __init__(
        self,
        file_path: str,
        target_dir: str | None = None,
        **kwargs,
    ) -> None:
        """Initialize PDF Markdown loader with configuration-based processing.

        Parameters
        ----------
        file_path : str
            Path to the PDF file.
        target_dir : str, optional
            Target directory for output files. If None, uses current
            working directory.
        **kwargs
            Additional arguments that override configuration settings.
        """
        self.file_path = file_path
        self.target_dir = target_dir
        self.config = self._load_configuration(**kwargs)

        self.stats = {
            "processing_time": 0.0,
            "method_used": None,
            "fallback_used": False,
            "errors": [],
        }

        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"PDF file not found: {self.file_path}")

    def _load_configuration(self, **kwargs) -> dict:
        """Load configuration from globalvariables with runtime overrides.

        Parameters
        ----------
        **kwargs
            Runtime configuration overrides.

        Returns
        -------
        dict
            Configuration dictionary.
        """
        config = {
            "pdf_processing_method": PDFProcessingConfig.PDF_PROCESSING_METHOD.value,
            "enable_fallback": PDFProcessingConfig.ENABLE_FALLBACK.value,
            "fallback_method": PDFProcessingConfig.FALLBACK_METHOD.value,
            "ocr_dpi": PDFProcessingConfig.OCR_DPI.value,
            "ocr_force_ocr": PDFProcessingConfig.OCR_FORCE_OCR.value,
            "enable_vlm": PDFProcessingConfig.ENABLE_VLM.value,
            "vlm_model": PDFProcessingConfig.VLM_MODEL.value,
            "extract_images": PDFProcessingConfig.EXTRACT_IMAGES.value,
            "extract_tables": PDFProcessingConfig.EXTRACT_TABLES.value,
            "max_workers": PDFProcessingConfig.MAX_WORKERS.value,
            "timeout_seconds": PDFProcessingConfig.TIMEOUT_SECONDS.value,
        }

        config.update(kwargs)  # runtime overrides

        return config

    def load(self) -> list[Document]:
        """Load PDF using configured processing method with fallback support.

        Returns
        -------
        list[Document]
            List containing a single Document with extracted content.
        """
        start_time = time.time()

        try:
            primary_method = self.config["pdf_processing_method"]
            logger.info(f"Processing PDF with primary method: {primary_method}")

            try:
                if primary_method == "markdown_converter":
                    result = self._load_with_markdown_converter()
                elif primary_method == "ocr":
                    result = self._load_with_ocr()
                else:
                    raise ValueError(f"Unsupported processing method: {primary_method}")

                self.stats["method_used"] = primary_method
                self.stats["processing_time"] = time.time() - start_time

                return result

            except Exception as primary_error:
                logger.warning(
                    f"Primary method '{primary_method}' failed: {primary_error}"
                )
                self.stats["errors"].append(f"Primary method failed: {primary_error}")

                if self.config["enable_fallback"]:
                    result = self._apply_fallback(primary_error)
                else:
                    result = self._create_error_document(
                        f"Primary method '{primary_method}' failed and fallback disabled: {primary_error}",
                        primary_method,
                    )
                self.stats["processing_time"] = time.time() - start_time
                return result
        except Exception as e:
            self.stats["processing_time"] = time.time() - start_time
            self.stats["errors"].append(f"General processing error: {e}")
            return self._create_error_document(str(e), "unknown")

    def _load_with_markdown_converter(self) -> list[Document]:
        """Load PDF using markdown converter backend.

        Returns
        -------
        list[Document]
            List containing a single Document with markdown content.
        """
        try:
            output_dir = self._output_directory()

            result = markdown_converter(
                pdf_path=self.file_path,
                output_dir=output_dir,
                enable_vlm=self.config["enable_vlm"],
                vlm_model=self.config["vlm_model"],
                extract_images=self.config["extract_images"],
                extract_tables=self.config["extract_tables"],
                max_workers=self.config["max_workers"],
            )

            markdown_content = self._read_markdown_file(result["markdown"])

            if not markdown_content:
                return self._create_empty_document(result, "markdown_converter")

            return self._create_success_document(
                markdown_content, result, "markdown_converter"
            )

        except Exception as e:
            raise RuntimeError(f"Markdown converter failed: {e}")

    def _load_with_ocr(self) -> list[Document]:
        """Load PDF using OCR backend.

        Returns
        -------
        list[Document]
            List containing a single Document with OCR-extracted text.
        """
        try:
            ocr_loader = OCRPDFLoader(
                file_path=self.file_path,
                dpi=self.config["ocr_dpi"],
                force_ocr=self.config["ocr_force_ocr"],
                max_workers=self.config["max_workers"],
            )

            return ocr_loader.load()

        except Exception as e:
            raise RuntimeError(f"OCR processing failed: {e}")

    def _apply_fallback(self, primary_error: Exception) -> list[Document]:
        """Apply fallback method when primary method fails.

        Parameters
        ----------
        primary_error : Exception
            Error from primary method.

        Returns
        -------
        list[Document]
            List containing a single Document from fallback method.
        """
        fallback_method = self.config["fallback_method"]
        logger.info(f"Applying fallback method: {fallback_method}")

        try:
            if fallback_method == "markdown_converter":
                result = self._load_with_markdown_converter()
            elif fallback_method == "ocr":
                result = self._load_with_ocr()
            else:
                raise ValueError(f"Unsupported fallback method: {fallback_method}")

            self.stats["fallback_used"] = True
            self.stats["method_used"] = fallback_method

            # Update metadata to indicate fallback was used
            if result and len(result) > 0:
                result[0].metadata.update(
                    {
                        "fallback_used": True,
                        "fallback_method": fallback_method,
                        "primary_method_error": str(primary_error),
                    }
                )

            return result

        except Exception as fallback_error:
            logger.error(
                f"Fallback method '{fallback_method}' also failed: {fallback_error}"
            )
            self.stats["errors"].append(f"Fallback method failed: {fallback_error}")
            return self._create_error_document(
                f"Both primary and fallback methods failed. "
                f"Primary error: {primary_error}. "
                f"Fallback error: {fallback_error}",
                fallback_method,
            )

    def _output_directory(self) -> str:
        """Get the output directory for the conversion.

        Returns
        -------
        str
            Path to the output directory.
        """
        if self.target_dir:
            os.makedirs(self.target_dir, exist_ok=True)
            return self.target_dir
        return os.getcwd()

    def _read_markdown_file(self, markdown_path: str) -> str:
        """Read the generated markdown content from file.

        Parameters
        ----------
        markdown_path : str
            Path to the markdown file.

        Returns
        -------
        str
            Content of the markdown file.
        """
        try:
            with open(markdown_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            raise RuntimeError(f"Failed to read markdown file: {e}")

    def _create_success_document(
        self, content: str, result: dict, method_used: str
    ) -> list[Document]:
        """Create a document for successful processing.

        Parameters
        ----------
        content : str
            The extracted content.
        result : dict
            Processing result metadata.
        method_used : str
            The processing method used.

        Returns
        -------
        list[Document]
            List containing a single Document with content.
        """
        metadata = {
            "source": self.file_path,
            "processing_method": method_used,
            "fallback_used": self.stats["fallback_used"],
            "fallback_method": self.config["fallback_method"]
            if self.stats["fallback_used"]
            else None,
            "processing_time": self.stats["processing_time"],
            "vlm_enabled": self.config["enable_vlm"]
            if method_used == "markdown_converter"
            else None,
            "vlm_model": self.config["vlm_model"]
            if method_used == "markdown_converter" and self.config["enable_vlm"]
            else None,
            "ocr_settings": {
                "dpi": self.config["ocr_dpi"],
                "force_ocr": self.config["ocr_force_ocr"],
            }
            if method_used == "ocr"
            else None,
            "extraction_stats": result if method_used == "markdown_converter" else None,
            "errors": self.stats["errors"] if self.stats["errors"] else None,
        }

        return [Document(content=content, metadata=metadata)]

    def _create_empty_document(self, result: dict, method_used: str) -> list[Document]:
        """Create a document for empty content.

        Parameters
        ----------
        result : dict
            Processing result metadata.
        method_used : str
            The processing method used.

        Returns
        -------
        list[Document]
            List containing a single Document with empty content message.
        """
        metadata = {
            "source": self.file_path,
            "processing_method": method_used,
            "fallback_used": self.stats["fallback_used"],
            "fallback_method": self.config["fallback_method"]
            if self.stats["fallback_used"]
            else None,
            "processing_time": self.stats["processing_time"],
            "extraction_error": "empty_content",
            "extraction_stats": result if method_used == "markdown_converter" else None,
            "errors": self.stats["errors"] if self.stats["errors"] else None,
        }

        return [
            Document(
                content="No content could be extracted from this document.",
                metadata=metadata,
            )
        ]

    def _create_error_document(
        self, error_message: str, method_used: str
    ) -> list[Document]:
        """Create a document for processing errors.

        Parameters
        ----------
        error_message : str
            Error message to include in the document.
        method_used : str
            The processing method that failed.

        Returns
        -------
        list[Document]
            List containing a single Document with error message.
        """
        metadata = {
            "source": self.file_path,
            "processing_method": method_used,
            "fallback_used": self.stats["fallback_used"],
            "fallback_method": self.config["fallback_method"]
            if self.stats["fallback_used"]
            else None,
            "processing_time": self.stats["processing_time"],
            "extraction_error": error_message,
            "errors": self.stats["errors"] if self.stats["errors"] else None,
        }

        return [
            Document(
                content=f"Error processing document: {error_message}",
                metadata=metadata,
            )
        ]


class PDFLoader:
    """Creating PDF loaders based on configuration preferences."""

    @staticmethod
    def pdf_loader(
        use_ocr: bool = None, ocr_dpi: int = None, force_ocr: bool = None
    ) -> tuple[type, dict]:
        """Get the appropriate PDF loader based on configuration.

        Parameters
        ----------
        use_ocr : bool, optional
            Whether to use OCR for PDF files. If None, uses configuration default.
        ocr_dpi : int, optional
            DPI setting for OCR. If None, uses configuration default.
        force_ocr : bool, optional
            Whether to force OCR even if text is available. If None, uses configuration default.

        Returns
        -------
        tuple[type, dict]
            A tuple containing the loader class and its arguments.
        """
        config_overrides = {}

        if use_ocr is not None:
            config_overrides["pdf_processing_method"] = (
                "ocr" if use_ocr else "markdown_converter"
            )

        if ocr_dpi is not None:
            config_overrides["ocr_dpi"] = ocr_dpi

        if force_ocr is not None:
            config_overrides["ocr_force_ocr"] = force_ocr

        # Add VLM configuration
        config_overrides.update(
            {
                "enable_vlm": VLMConfig.ENABLE_VLM.value,
                "vlm_model": VLMConfig.VLM_MODEL.value,
                "max_workers": VLMConfig.MAX_WORKERS.value,
            }
        )

        return (PDFMarkdownLoader, config_overrides)


# File extension to loader mapping
LOADER_MAPPING = {
    ".csv": (CSVLoader, {}),
    ".doc": (Docx2txtLoader, {}),
    ".docx": (Docx2txtLoader, {}),
    ".enex": (EverNoteLoader, {}),
    ".eml": (MyEmlLoader, {}),
    ".epub": (UnstructuredEPubLoader, {}),
    ".html": (UnstructuredHTMLLoader, {}),
    ".md": (UnstructuredMarkdownLoader, {}),
    ".odt": (UnstructuredODTLoader, {}),
    ".pdf": PDFLoader.pdf_loader(),
    ".ppt": (UnstructuredPowerPointLoader, {}),
    ".pptx": (UnstructuredPowerPointLoader, {}),
    ".txt": (TextLoader, {"encoding": "utf8"}),
}


def loadSingleDocument(file_path: str, target_dir: str | None = None) -> str:
    """Load a single document from file.

    Parameters
    ----------
    file_path : str
        Path to the file to load.
    target_dir : str, optional
        Target directory for output files.

    Raises
    ------
    ValueError
        If the file extension is not supported.

    Returns
    -------
    str
        Document content as string.
    """
    # Handle files in remote storage by downloading to a temp file
    file_extension = os.path.splitext(file_path)[1].lower()
    if file_extension not in LOADER_MAPPING:
        raise ValueError(f"Unsupported file extension '{file_extension}'")

    loader_class, loader_args = LOADER_MAPPING[file_extension]

    if file_extension == ".pdf" and target_dir:
        loader_args["target_dir"] = target_dir

    with NamedTemporaryFile(suffix=file_extension) as tmp_file:
        with fs.open_for_reading(file_path) as f:
            tmp_file.write(f.read())
            tmp_file.flush()
            local_file_path = tmp_file.name
        try:
            loader = loader_class(local_file_path, **loader_args)
            result = loader.load()
        except FileNotFoundError:
            logger.error(f"File not found: {file_path}", exc_info=True)
            result = []
        except Exception:
            logger.error(f"Error loading file: {file_path}", exc_info=True)
            result = []

    page_content = [
        doc.page_content
        for doc in result
        if hasattr(doc, "page_content") and doc.page_content
    ]
    result_str = "\n".join(page_content) if page_content else ""

    basename, extension = os.path.splitext(os.path.basename(file_path))
    ingested_filename = f"{basename}_{extension.lstrip('.')}.txt"
    folder_path = os.path.dirname(file_path).replace("/uploaded", "/ingested")
    ingested_path = os.path.join(folder_path, ingested_filename)
    fs.write_to_file(ingested_path, result_str)

    return result_str


def ThreadMultiDocLoader(
    file_paths: list[str],
    ignored_files: list[str] | None = None,
    target_dir: str | None = None,
) -> str:
    """Load multiple documents using threaded execution.

    Parameters
    ----------
    file_paths : list[str]
        List of file paths to load.
    ignored_files : list[str], optional
        List of files to ignore, by default None.
    target_dir : str, optional
        Target directory for output files, by default None.

    Returns
    -------
    str
        Combined document content from all files.
    """
    if ignored_files is None:
        ignored_files = []

    filtered_files = [
        file_path for file_path in file_paths if file_path not in ignored_files
    ]

    results = []
    with ThreadPoolExecutor() as executor:
        future_to_file = {
            executor.submit(loadSingleDocument, file, target_dir): file
            for file in filtered_files
        }

        with tqdm(
            total=len(filtered_files), desc="Loading new documents", ncols=80
        ) as pbar:
            for future in as_completed(future_to_file):
                try:
                    doc_content = future.result()
                    if doc_content:
                        results.append(doc_content)
                except Exception:
                    logger.error(
                        f"Error processing file: {future_to_file[future]}",
                        exc_info=True,
                    )
                finally:
                    pbar.update()

    return "\n".join(results)
