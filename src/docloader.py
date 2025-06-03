import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

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


def loadSingleDocument(file_path: str) -> str:
    """Loading single document

    Parameters
    ----------
    file_path (str): Temporary file path

    Raises
    ------
    ValueError

    Returns
    -------
    str: Document string
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
                return ""

            page_content = [
                doc.page_content
                for doc in result
                if hasattr(doc, "page_content") and doc.page_content
            ]

            if not page_content:
                logging.warning(
                    f"Warning: No valid page content in {file_path}"
                )
                return ""

            document = " \n".join(page_content)
            logging.info(f"Document extracted: {document}")
            return document

        except Exception as e:
            logging.error(f"🚩 Error loading document {file_path}: {str(e)}")
            return ""
    raise ValueError(f"Unsupported file extension '{ext}'")


def ThreadMultiDocLoader(
    file_paths: List[str], ignored_files: List[str] = []
) -> str:
    """Threaded multi-document loader

    Parameters
    ----------
    file_paths : List[str], List containing file path
    ignored_files : List[str], optional. DESCRIPTION. The default is [].

    Returns
    -------
    str: Document string.
    """
    filtered_files = [
        file_path for file_path in file_paths if file_path not in ignored_files
    ]

    results = []
    with ThreadPoolExecutor() as executor:
        future_to_file = {
            executor.submit(loadSingleDocument, file): file
            for file in filtered_files
        }
        with tqdm(
            total=len(filtered_files), desc="Loading new documents", ncols=80
        ) as pbar:
            for future in as_completed(future_to_file):
                file = future_to_file[future]
                try:
                    docs = future.result()
                    if docs:  # Only extend if docs is not empty
                        results.extend(docs)
                except Exception as e:
                    logging.error(f"🚩 Error loading document {file}: {e}")
                pbar.update()

    document = "".join(results)
    return document
