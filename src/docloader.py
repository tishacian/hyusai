import os
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from src.customdocloader import MyEmlLoader
from src.globalvariables import OCRConfig, VLMConfig
from src.markdownconverter import markdown_converter
from src.utils import configure_tesseract

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
    """PDF loader that converts PDF to Markdown using the unified converter."""

    def __init__(
        self,
        file_path: str,
        enable_vlm: bool = False,
        vlm_model: str = "vllm-smolvlm-256m",
        target_dir: str | None = None,
        **kwargs,
    ) -> None:
        """Initialize PDF Markdown loader.

        Parameters
        ----------
        file_path : str
            Path to the PDF file.
        enable_vlm : bool, optional
            Whether to enable VLM image analysis, by default False.
        vlm_model : str, optional
            VLM model to use for image analysis, by default
            "vllm-smolvlm-256m".
        target_dir : str, optional
            Target directory for output files. If None, uses current
            working directory.
        **kwargs
            Additional arguments passed to markdown_converter.
        """
        self.file_path = file_path
        self.enable_vlm = enable_vlm
        self.vlm_model = vlm_model
        self.target_dir = target_dir
        self.kwargs = kwargs

    def load(self) -> list[Document]:
        """Load PDF and return document as markdown content.

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
                enable_vlm=self.enable_vlm,
                vlm_model=self.vlm_model,
                **self.kwargs,
            )

            markdown_content = self.read_markdown_file(result["markdown"])

            if not markdown_content:
                return self.create_document(result)

            return self.convert_to_document(markdown_content, result)

        except Exception as e:
            return self._create_error_document(str(e))

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

    def read_markdown_file(self, markdown_path: str) -> str:
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
        with open(markdown_path, "r", encoding="utf-8") as f:
            return f.read()

    def create_document(self, result: dict) -> list[Document]:
        """Create a document for empty content.

        Parameters
        ----------
        result : dict
            Converter output result.

        Returns
        -------
        list[Document]
            List containing a single Document with empty content message.
        """
        return [
            Document(
                content="No content could be extracted from this document.",
                metadata={
                    "source": self.file_path,
                    "extraction_error": "empty_content",
                    "converter_output": result,
                },
            )
        ]

    def convert_to_document(
        self, markdown_content: str, result: dict
    ) -> list[Document]:
        """Create a document for successful conversion.

        Parameters
        ----------
        markdown_content : str
            The markdown content.
        result : dict
            Converter output result.

        Returns
        -------
        list[Document]
            List containing a single Document with markdown content.
        """
        return [
            Document(
                content=markdown_content,
                metadata={
                    "source": self.file_path,
                    "converter_output": result,
                    "vlm_enabled": self.enable_vlm,
                    "vlm_model": self.vlm_model if self.enable_vlm else None,
                },
            )
        ]

    def _create_error_document(self, error_message: str) -> list[Document]:
        """Create a document for conversion errors.

        Parameters
        ----------
        error_message : str
            Error message to include in the document.

        Returns
        -------
        list[Document]
            List containing a single Document with error message.
        """
        return [
            Document(
                content=f"Error processing document: {error_message}",
                metadata={
                    "source": self.file_path,
                    "extraction_error": error_message,
                },
            )
        ]


class PDFLoader:
    """Factory class for creating PDF loaders based on OCR preferences."""

    @staticmethod
    def pdf_loader(
        use_ocr: bool = True, ocr_dpi: int = 150, force_ocr: bool = True
    ) -> tuple[type, dict]:
        """Get the appropriate PDF loader based on OCR preference.

        Parameters
        ----------
        use_ocr : bool, optional
            Whether to use OCR for PDF files, by default True.
        ocr_dpi : int, optional
            DPI setting for OCR, by default 150.
        force_ocr : bool, optional
            Whether to force OCR even if text is available, by default True.

        Returns
        -------
        tuple[type, dict]
            A tuple containing the loader class and its arguments.
        """
        return (
            PDFMarkdownLoader,
            {
                "enable_vlm": VLMConfig.ENABLE_VLM.value,
                "vlm_model": VLMConfig.VLM_MODEL.value,
                "max_workers": VLMConfig.MAX_WORKERS.value,
            },
        )


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
    ".pdf": PDFLoader.pdf_loader(
        # -- not been used but leaving them for now..to remove later
        use_ocr=OCRConfig.USE_OCR.value,
        ocr_dpi=OCRConfig.OCR_DPI.value,
        force_ocr=OCRConfig.FORCE_OCR.value,
    ),
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
    file_extension = "." + file_path.rsplit(".", 1)[-1]

    if file_extension not in LOADER_MAPPING:
        raise ValueError(f"Unsupported file extension '{file_extension}'")

    loader_class, loader_args = LOADER_MAPPING[file_extension]

    if file_extension == ".pdf" and target_dir:
        loader_args["target_dir"] = target_dir

    try:
        loader = loader_class(file_path, **loader_args)
        result = loader.load()

        if not result:
            return ""

        page_content = [
            doc.page_content
            for doc in result
            if hasattr(doc, "page_content") and doc.page_content
        ]

        if not page_content:
            return ""

        return " \n".join(page_content)

    except Exception:
        return ""


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
                    docs = future.result()
                    if docs:
                        results.extend(docs)
                except Exception:
                    pass
                pbar.update()

    return "".join(results)
