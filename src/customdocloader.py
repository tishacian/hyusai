#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Mar  2 06:21:51 2025

@author: kennethezukwoke
"""

import os
import asyncio
import platform
import pymupdf
from PIL import Image
import time
from typing import List
from langchain.docstore.document import Document
from langchain.document_loaders import UnstructuredEmailLoader
import tracemalloc

tracemalloc.start()

try:
    import pytesseract

    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    print("Pytesseract not available. Will use only PyMuPDF extraction.")


# %% custom loaders


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


class PDFExtractor:
    """Extract text from PDF files"""

    def __init__(self, tesseract_path=None, max_workers=None):
        """
        Initialize the extractor with optional tesseract path.

        Args:
            tesseract_path (str): Path to Tesseract executable
            max_workers (int): Maximum number of worker processes/threads
        """
        self.max_cpu = os.cpu_count()
        self.use_ocr = TESSERACT_AVAILABLE
        if self.use_ocr and tesseract_path is None:
            tesseract_path = self._get_tesseract_path()

        if self.use_ocr and tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

        if max_workers is None:
            self.max_workers = max(1, min(self.max_cpu - 1, self.max_cpu))
        else:
            self.max_workers = max_workers

        if self.use_ocr:
            try:
                pytesseract.get_tesseract_version()
                print(
                    f"Tesseract OCR available - version: {pytesseract.get_tesseract_version()}"
                )
                print(f"Using path: {pytesseract.pytesseract.tesseract_cmd}")
            except Exception as e:
                print(f"Tesseract not properly configured: {e}")
                self.use_ocr = False

    def _get_tesseract_path(self):
        """Detect the system and set Tesseract path."""
        try:
            import pytesseract

            current_cmd = pytesseract.pytesseract.tesseract_cmd
            if current_cmd != "tesseract" and os.path.exists(current_cmd):
                return current_cmd

            if current_cmd == "tesseract":
                conda_paths = [
                    "/workspace/.miniconda3/bin/tesseract",
                    os.path.expanduser("~/miniconda3/bin/tesseract"),
                    os.path.expanduser("~/.miniconda3/bin/tesseract"),
                ]
                for path in conda_paths:
                    if os.path.exists(path):
                        return path
        except (ImportError, AttributeError):
            pass

        system = platform.system()
        if system == "Windows":
            possible_paths = [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    return path
        elif system == "Darwin":
            possible_paths = [
                "/usr/local/bin/tesseract",
                "/opt/homebrew/bin/tesseract",
                "/usr/bin/tesseract",
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    return path
        elif system == "Linux":
            possible_paths = [
                "/usr/bin/tesseract",
                "/usr/local/bin/tesseract",
                "/workspace/bin/tesseract",
                "/workspace/.local/bin/tesseract",
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    return path
        return None

    async def _process_page(self, args):
        """
        Process a single page

        Parameters:
            args (tuple): (page_pixmap, page_num, doc_len, force_ocr)
                page_pixmap (bytes): Serialized page pixmap data
                page_num (int): Page number
                doc_len (int): Total number of pages
                force_ocr (bool): Whether to force OCR even if text is present

        Returns:
            tuple: (page_num, extracted_text)
        """
        page_pixmap, page_num, doc_len, force_ocr = args
        page_idx = page_num + 1

        try:
            # -- first extraction w/ no-OCR
            pix = pymupdf.Pixmap(page_pixmap)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            if not self.use_ocr:
                return page_idx, ""

            async def run_ocr(image, config=None):
                loop = asyncio.get_running_loop()
                if config:
                    return await loop.run_in_executor(
                        None,
                        lambda: pytesseract.image_to_string(
                            image, config=config
                        ),
                    )
                else:
                    return await loop.run_in_executor(
                        None, lambda: pytesseract.image_to_string(image)
                    )

            try:
                # -- comparing different extraction methods
                ocr_task1 = run_ocr(img)
                ocr_task2 = run_ocr(img, "--psm 4")
                text1, text2 = await asyncio.gather(ocr_task1, ocr_task2)
                if len(text1) > len(text2):
                    return page_idx, text1
                else:
                    return page_idx, text2

            except Exception as e:
                print(f"OCR error on page {page_idx}: {str(e)}")
                return page_idx, ""

        except Exception as e:
            print(f"Error processing page {page_idx}: {str(e)}")
            return page_idx, ""

    async def extract_from_pdf(self, pdf_path, dpi=300, force_ocr=False):
        """
        Extract text from a PDF file asynchronously using multiple processes.

        Parameters:
            pdf_path (str): Path to the PDF file
            dpi (int): DPI for rendering images for OCR
            force_ocr (bool): Force OCR even if text is present

        Returns:
            dict: Dictionary with page numbers as keys and extracted text as values
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        start_time = time.time()
        doc = pymupdf.open(pdf_path)
        total_pages = len(doc)
        result = {}
        pages_needing_ocr = []

        if not force_ocr:
            for page_num, page in enumerate(doc):
                page_idx = page_num + 1
                try:
                    text = page.get_text()
                    if text.strip():
                        result[page_idx] = text
                    else:
                        pages_needing_ocr.append(page_num)
                except Exception:
                    pages_needing_ocr.append(page_num)

            print(
                f"Extracted native text from {total_pages - len(pages_needing_ocr)} pages"
            )
            print(f"Need OCR for {len(pages_needing_ocr)} pages")
        else:
            pages_needing_ocr = list(range(total_pages))
            print(f"Forcing OCR for all {total_pages} pages")

        if pages_needing_ocr and self.use_ocr:
            pixmaps = []
            for page_num in pages_needing_ocr:
                page = doc[page_num]
                zoom = dpi / 72
                matrix = pymupdf.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                pixmap_data = pix.tobytes(output="png")
                pixmaps.append((pixmap_data, page_num, total_pages, force_ocr))

            semaphore = asyncio.Semaphore(self.max_workers)

            async def process_with_semaphore(pixmap_data):
                async with semaphore:
                    return await self._process_page(pixmap_data)

            tasks = [
                process_with_semaphore(pixmap_data) for pixmap_data in pixmaps
            ]
            completed = 0
            # batch processing across workers
            while tasks:
                batch = tasks[: self.max_workers]
                tasks = tasks[self.max_workers :]
                batch_results = await asyncio.gather(*batch)
                for page_idx, text in batch_results:
                    result[page_idx] = text

                completed += len(batch)
                print(f"OCR progress: {completed}/{len(pixmaps)} pages")

        doc.close()
        elapsed_time = time.time() - start_time
        print(f"PDF processing completed in {elapsed_time:.2f} seconds")
        return result

    async def extract_text_from_pdf(
        self, pdf_path, output_format="text", **kwargs
    ):
        """
        Extract text from a PDF w/ specified format.

        Parameters:
            pdf_path (str): Path to the PDF file
            output_format (str): Format to return the results in:
                - "text": Single string with all text
                - "pages": Dictionary with page numbers as keys
                - "json": JSON-formatted string
            **kwargs: Additional arguments to pass to extract_from_pdf

        Returns:
            Union[str, dict]: Extracted text in the specified format
        """
        pages_dict = await self.extract_from_pdf(pdf_path, **kwargs)
        if output_format == "pages":
            return pages_dict

        elif output_format == "json":
            import json

            return json.dumps(pages_dict, ensure_ascii=False, indent=2)

        else:
            all_text = "\n\n".join(
                [
                    f"--- Page {page_num} ---\n{text}"
                    for page_num, text in sorted(pages_dict.items())
                ]
            )
            return all_text


def extract_text_from_pdf(
    pdf_path, output_format="text", dpi=300, force_ocr=False, **kwargs
):
    """
    Wrapper for PDFExtractor.

    Parameters:
        pdf_path (str): Path to the PDF file
        output_format (str): Format to return the results in
        dpi (int): DPI for rendering images for OCR
        force_ocr (bool): Force OCR even if text is present
        **kwargs: Additional arguments to pass to extract_text_from_pdf

    Returns:
        Union[str, dict]: Extracted text in the specified format
    """

    async def _extract():
        max_workers = kwargs.pop("max_workers", None)
        extractor = PDFExtractor(max_workers=max_workers)
        return await extractor.extract_text_from_pdf(
            pdf_path,
            output_format=output_format,
            dpi=dpi,
            force_ocr=force_ocr,
            **kwargs,
        )

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_extract())
        return result
    finally:
        loop.close()


class PDFLoader:
    """Custom PDF Loader using PDFExtractor w/ OCR"""

    def __init__(self, file_path, dpi=300, force_ocr=False, **kwargs):
        self.file_path = file_path
        self.dpi = dpi
        self.force_ocr = force_ocr
        self.kwargs = kwargs

    def load(self):
        """Load PDF and return document with page content"""
        try:
            text = extract_text_from_pdf(
                self.file_path,
                output_format="text",
                dpi=self.dpi,
                force_ocr=self.force_ocr,
                **self.kwargs,
            )
            return [
                Document(
                    page_content=text, metadata={"source": self.file_path}
                )
            ]
        except Exception as e:
            print(f"Error loading PDF document {self.file_path}: {str(e)}")
            return [
                Document(page_content="", metadata={"source": self.file_path})
            ]
