import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Union, Tuple

from langchain_community.document_loaders import (
    CSVLoader,
    Docx2txtLoader,
    EverNoteLoader,
    PyMuPDFLoader,
    TextLoader,
    UnstructuredEPubLoader,
    UnstructuredHTMLLoader,
    UnstructuredMarkdownLoader,
    UnstructuredODTLoader,
    UnstructuredPowerPointLoader,
)
from tqdm import tqdm

from src.customdocloader import MyEmlLoader, OCRPDFLoader
from src.globalvariables import OCRConfig

from metadata_extraction.docmeta.core.factory import extract_metadata

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
from src.utils import configure_tesseract

tesseract_path, tesseract_available = configure_tesseract()


class PDFLoader:
    """Factory class for creating PDF loaders based on OCR preferences"""

    @staticmethod
    def get_pdf_loader(use_ocr=True, ocr_dpi=150, force_ocr=True):
        """Get the appropriate PDF loader based on OCR preference

        Parameters
        ----------
        use_ocr : bool, optional
            Whether to use OCR for PDF files. Default is False.
        ocr_dpi : int, optional
            DPI setting for OCR. Default is 150.
        force_ocr : bool, optional
            Whether to force OCR even if text is available. Default is True.

        Returns
        -------
        tuple
            A tuple containing the loader class and its arguments
        """
        global tesseract_available

        if use_ocr and tesseract_available:
            return (OCRPDFLoader, {"dpi": ocr_dpi, "force_ocr": force_ocr})
        else:
            print("Using PyMuPDFLoader (Tesseract OCR not available)")
            return (PyMuPDFLoader, {})


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
    ".pdf": PDFLoader.get_pdf_loader(
        use_ocr=OCRConfig.USE_OCR.value,
        ocr_dpi=OCRConfig.OCR_DPI.value,
        force_ocr=OCRConfig.FORCE_OCR.value,
    ),
    ".ppt": (UnstructuredPowerPointLoader, {}),
    ".pptx": (UnstructuredPowerPointLoader, {}),
    ".txt": (TextLoader, {"encoding": "utf8"}),
}


# %%


class Document:
    def __init__(self, content: str):
        self.page_content = content


def loadSingleDocument(file_path: str, return_metadata: bool = True):
    """Loading single document with metadata extraction

    Parameters
    ----------
    file_path (str): Temporary file path
    return_metadata (bool): If True returns (text, metadata) tuple else returns just text.

    Returns
    -------
    Union[str, Tuple[str, dict]]
        Extracted document text (and metadata when requested)
    """
    ext = "." + file_path.rsplit(".", 1)[-1]
    if ext in LOADER_MAPPING:
        loader_class, loader_args = LOADER_MAPPING[ext]
        try:
            loader = loader_class(file_path, **loader_args)
            result = loader.load()

            if not result:
                logging.warning(
                    f"Warning: No content extracted from {file_path}"
                )
                return ("", {}) if return_metadata else ""

            page_content = [
                doc.page_content
                for doc in result
                if hasattr(doc, "page_content") and doc.page_content
            ]

            if not page_content:
                logging.warning(
                    f"Warning: No valid page content in {file_path}"
                )
                return ("", {}) if return_metadata else ""

            document = " \n".join(page_content)

            # ----- metadata extraction -----
            if return_metadata:
                try:
                    metadata = extract_metadata(file_path)
                except Exception as meta_err:  # pragma: no cover
                    logging.error(f"Metadata extraction failed for {file_path}: {meta_err}")
                    metadata = {}

            return (document, metadata) if return_metadata else document
        except Exception as e:
            logging.error(f"🚩 Error loading document {file_path}: {str(e)}")
            return ("", {}) if return_metadata else ""
    raise ValueError(f"Unsupported file extension '{ext}'")


def ThreadMultiDocLoader(file_paths: List[str], ignored_files: List[str] = [], return_metadata: bool = True):
    """Threaded multi-document loader that aggregates texts and metadata.

    Returns
    -------
    Union[str, Tuple[str, List[dict]]]
        Concatenated document text (and list of metadata dicts when requested)
    """
    filtered_files = [
        file_path for file_path in file_paths if file_path not in ignored_files
    ]

    texts: List[str] = []
    metadatas: List[dict] = []

    with ThreadPoolExecutor() as executor:
        future_to_file = {
            executor.submit(loadSingleDocument, file, return_metadata): file
            for file in filtered_files
        }
        with tqdm(
            total=len(filtered_files), desc="Loading new documents", ncols=80
        ) as pbar:
            for future in as_completed(future_to_file):
                file = future_to_file[future]
                try:
                    result = future.result()
                    if return_metadata:
                        doc_text, meta = result
                        if doc_text:
                            texts.append(doc_text)
                            metadatas.append(meta)
                    else:
                        doc_text = result
                        if doc_text:
                            texts.append(doc_text)
                except Exception as e:
                    logging.error(f"🚩 Error loading document {file}: {e}")
                pbar.update()

    document = "".join(texts)
    return (document, metadatas) if return_metadata else document
