from tqdm import tqdm
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed
from langchain.docstore.document import Document
from langchain.document_loaders import (
    CSVLoader,
    EverNoteLoader,
    PyMuPDFLoader,
    TextLoader,
    Docx2txtLoader,
    UnstructuredEmailLoader,
    UnstructuredEPubLoader,
    UnstructuredHTMLLoader,
    UnstructuredMarkdownLoader,
    UnstructuredODTLoader,
    UnstructuredPowerPointLoader,
)


# %%


class MyEmlLoader(UnstructuredEmailLoader):
    """Wrapper to fallback to text/plain when default does not work"""

    def load(self) -> List[Document]:
        try:
            try:
                doc = UnstructuredEmailLoader.load(self)
            except ValueError as e:
                if "text/html content not found in email" in str(e):
                    self.unstructured_kwargs["content_source"] = "text/plain"
                    doc = UnstructuredEmailLoader.load(self)
                else:
                    raise
        except Exception as e:
            raise type(e)(f"{self.file_path}: {e}") from e
        return doc


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
    ".pdf": (PyMuPDFLoader, {}),
    ".ppt": (UnstructuredPowerPointLoader, {}),
    ".pptx": (UnstructuredPowerPointLoader, {}),
    ".txt": (TextLoader, {"encoding": "utf8"}),
}

# %%


class Document:
    def __init__(self, content: str):
        self.page_content = content


class Preprocess:
    def __init__(self, document: str):
        self.document = document

    def prep(self):
        return self.document.replace("\n", "").replace("\r", "")


def loadSingleDocument(file_path: str) -> List[Document]:
    """Loading single document

    Parameters
    ----------
    file_path (str): Temporary file path

    Raises
    ------
    ValueError

    Returns
    -------
    List[Document]: Document string
    """
    ext = "." + file_path.rsplit(".", 1)[-1]
    if ext in LOADER_MAPPING:
        loader_class, loader_args = LOADER_MAPPING[ext]
        try:
            loader = loader_class(file_path, **loader_args)
            result = loader.load()
            page_content = [doc.page_content for doc in result]
            page_content = "".join(page_content)
            document = Preprocess(page_content).prep()
            return document
        except Exception as e:
            print(f"Error loading document {file_path}: {str(e)}")
            return ""
    raise ValueError(f"Unsupported file extension '{ext}'")


def ThreadMultiDocLoader(
    file_paths: List[str], ignored_files: List[str] = []
) -> List[Document]:
    """Threaded multi-document loader

    Parameters
    ----------
    file_paths : List[str], List containing file path
    ignored_files : List[str], optional. DESCRIPTION. The default is [].

    Returns
    -------
    List[Document]: Document string.
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
                    print(f"Error loading document {file}: {e}")
                pbar.update()

    document = Preprocess("".join(results)).prep()
    return document
