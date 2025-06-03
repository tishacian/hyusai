#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Mar  2 06:21:51 2025

@author: kennethezukwoke
"""

import asyncio
import hashlib
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import List

import numpy as np
import pymupdf
import pytesseract
from langchain_community.docstore.document import Document
from langchain_community.document_loaders import UnstructuredEmailLoader
from PIL import Image, ImageEnhance

from src.globalvariables import OCRConfig
from src.utils import get_tesseract_path

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
from src.utils import configure_tesseract

tesseract_path, TESSERACT_AVAILABLE = configure_tesseract()

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
    """Extract text from PDF files with ultra-fast performance"""

    def __init__(
        self, tesseract_path=None, max_workers=None, resource_percentage=None
    ):
        """Initialize the extractor with optimal settings

        Parameters
        ----------
            tesseract_path : str, optional
                tesseract path. The default is None.
            max_workers : int, optional
                maximum number of workers. The default is None.
            resource_percentage : float, optional
                percentage of resource to use. The default is None.

        Returns
        -------
            None.
        """
        self.max_cpu = os.cpu_count()
        self.use_ocr = TESSERACT_AVAILABLE
        self.resource_percentage = (
            0.95 if not resource_percentage else resource_percentage
        )

        if self.use_ocr and tesseract_path is None:
            tesseract_path = get_tesseract_path()
            if tesseract_path:
                logging.info(f"Found Tesseract at: {tesseract_path}")
            else:
                logging.info(
                    "Tesseract not found in any standard locations. OCR will be disabled."
                )

        if self.use_ocr and tesseract_path:
            logging.info("Tesseract path already set in 'configure_tesseract'")
        else:
            logging.error("Error setting Tesseract path")
            self.use_ocr = False

        self.max_workers = (
            int(self.max_cpu * self.resource_percentage)
            if not max_workers
            else max_workers
        )
        self.dpi_scale = 150 / 72
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self._ocr_cache = {}
        self.lang = "+".join(OCRConfig.LANGS.value)

        if self.use_ocr:
            try:
                version = pytesseract.get_tesseract_version()
                logging.info(f"Tesseract OCR available - version: {version}")
            except Exception as e:
                logging.error(f"Tesseract not properly configured: {e}")
                logging.error("OCR will be disabled")
                self.use_ocr = False

    def _image_hash(self, img):
        """Fast image fingerprinting for caching

        Parameters
        ----------
        img : PIL.Image
            Image.

        Returns
        -------
        hash
            image hash.

        """
        img_small = img.resize((32, 32)).convert("L")
        pixels = np.array(img_small).tobytes()
        return hashlib.md5(pixels).hexdigest()

    def _enhance_image(self, img):
        """Image for OCR with PIL

        Parameters
        ----------
        img : PIL.Image
            Image.

        Returns
        -------
        sharpened : float
            image sharpness.
        """
        img_gray = img.convert("L")
        enhancer = ImageEnhance.Contrast(img_gray)
        enhanced = enhancer.enhance(2.0)
        sharpener = ImageEnhance.Sharpness(enhanced)
        sharpened = sharpener.enhance(1.5)
        return sharpened

    def _process_page(self, img, page_num):
        """Process a single page with optimized settings

        Parameters
        ----------
        img : PIL.IMAGE
            Image.
        page_num : int
            page number.

        Returns
        -------
        page_num : int
            page number.
        text : str
            extrfacted text.

        """
        try:
            img_hash = self._image_hash(img)
            if img_hash in self._ocr_cache:
                return page_num, self._ocr_cache[img_hash]

            enhanced_img = self._enhance_image(img)
            # psm (page segmentation --> 4 single column): 3 -- preserving; engine mode 1 --> LSTM engine
            config = f"--psm 3 --oem 1 {self.lang}"
            text = pytesseract.image_to_string(enhanced_img, config=config)
            self._ocr_cache[img_hash] = text
            return page_num, text

        except Exception as e:
            logging.info(f"OCR error on page {page_num}: {str(e)}")
            return page_num, ""

    async def _process_pages_batch(self, batch: int):
        """Process a batch of pages concurrently

        Parameters
        ----------
        batch : int
            batch processing size.

        Returns
        -------
        TYPE
            DESCRIPTION.

        """
        loop = asyncio.get_running_loop()
        tasks = []

        for img, page_num in batch:
            task = loop.run_in_executor(
                self.executor, self._process_page, img, page_num
            )
            tasks.append(task)

        return await asyncio.gather(*tasks)

    async def extract_from_pdf(self, pdf_path, dpi=150, force_ocr=False):
        """Extract text from PDF with ultra-fast performance

        Parameters
        ----------
        pdf_path : str
            PDF path.
        dpi : int, optional
            dpi (dots per inch) value. The default is 150.
        force_ocr : str, optional
            True if force OCR else False. The default is False.

        Raises
        ------
        FileNotFoundError
            DESCRIPTION.

        Returns
        -------
        result : str
            Extracted text/string.

        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        result = {}
        # -- pass and multi-extract from image hash
        try:
            doc = pymupdf.open(pdf_path)
            total_pages = doc.page_count
            pages_needing_ocr = None
            if not force_ocr:
                pages_needing_ocr = []
                for page_num, page in enumerate(doc):
                    page_idx = page_num + 1
                    try:
                        text = page.get_text("text")
                        if text.strip():
                            result[page_idx] = text
                        else:
                            pages_needing_ocr.append(page_num)
                    except Exception:
                        pages_needing_ocr.append(page_num)
            else:
                pages_needing_ocr = list(range(total_pages))

            if pages_needing_ocr and self.use_ocr:
                self.dpi_scale = dpi / 72
                batch_size = min(6, self.max_workers * 2)
                try:
                    for i in range(0, len(pages_needing_ocr), batch_size):
                        batch_nums = pages_needing_ocr[i : i + batch_size]
                        batch = []
                        for page_num in batch_nums:
                            page = doc[page_num]
                            matrix = pymupdf.Matrix(
                                self.dpi_scale, self.dpi_scale
                            )
                            pix = page.get_pixmap(matrix=matrix, alpha=False)
                            img = Image.frombytes(
                                "RGB", [pix.width, pix.height], pix.samples
                            )
                            batch.append((img, page_num + 1))
                            pix = None  # Explicitly release pixmap memory
                        batch_results = await self._process_pages_batch(batch)
                        for page_idx, text in batch_results:
                            result[page_idx] = text
                        batch.clear()  # Clear batch after processing
                except Exception as e:
                    logging.error(f"🚩 Error processing PDF batch: {e}")
                    raise

        finally:
            if "doc" in locals():
                doc.close()
        return result

    async def extract_text_from_pdf(
        self, pdf_path, output_format="text", **kwargs
    ):
        """Extract text with specified format"""
        pages_dict = await self.extract_from_pdf(pdf_path, **kwargs)

        if output_format == "pages":
            return pages_dict

        elif output_format == "json":
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
    pdf_path, output_format="text", dpi=150, force_ocr=True, **kwargs
):
    """High-performance PDF text extraction"""

    async def _extract():
        max_workers = kwargs.pop("max_workers", None)
        extractor = None
        try:
            extractor = PDFExtractor(max_workers=max_workers)
            return await extractor.extract_text_from_pdf(
                pdf_path,
                output_format=output_format,
                dpi=dpi,
                force_ocr=force_ocr,
                **kwargs,
            )
        finally:
            if extractor and extractor.executor:
                extractor.executor.shutdown(wait=True)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _extract())
                return future.result()
        else:
            return loop.run_until_complete(_extract())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_extract())
        finally:
            loop.close()


class OCRPDFLoader:
    def __init__(self, file_path, dpi=150, force_ocr=True, **kwargs):
        """PDF/OCR Loader

        Parameters
        ----------
        file_path : str
            File path.
        dpi : int, optional
            DPI (dots per inch) value. The default is 150.
        force_ocr : TYPE, optional
            DESCRIPTION. The default is True.
        **kwargs : TYPE
            DESCRIPTION.

        Returns
        -------
        None.

        """
        self.file_path = file_path
        self.dpi = dpi
        self.force_ocr = force_ocr
        self.kwargs = kwargs

    def load(self):
        """Load PDF and return document"""
        try:
            text = extract_text_from_pdf(
                self.file_path,
                output_format="text",
                dpi=self.dpi,
                force_ocr=self.force_ocr,
                **self.kwargs,
            )

            if not text or not text.strip():
                logging.warning(
                    f"Warning: No text extracted from {self.file_path}"
                )
                return [
                    Document(
                        page_content="No text could be extracted from this document.",
                        metadata={
                            "source": self.file_path,
                            "extraction_error": "empty_content",
                        },
                    )
                ]

            return [
                Document(
                    page_content=text, metadata={"source": self.file_path}
                )
            ]
        except Exception as e:
            logging.error(
                f"🚩 Error extracting text from PDF {self.file_path}: {str(e)}"
            )
            return [
                Document(
                    page_content=f"Error processing document: {e}",
                    metadata={
                        "source": self.file_path,
                        "extraction_error": str(e),
                    },
                )
            ]
