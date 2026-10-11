import asyncio
import hashlib
import io
import os
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import fitz
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTFigure, LTImage
from PIL import Image

from src.globalvariables import PDFProcessingConfig


@dataclass
class ImageExtractionResult:
    success: bool
    image_path: str = ""
    original_format: str = ""
    file_size: int = 0
    dimensions: tuple[int, int] = (0, 0)
    error_message: str = ""
    checksum: str = ""
    extraction_method: str = ""


@dataclass
class ImageExtractionConfig:
    """Configuration for image extraction."""

    min_image_size: int = 20
    max_image_size: int = 10000
    supported_formats: list[str] = field(
        default_factory=lambda: ["PNG", "JPEG", "TIFF", "BMP", "GIF", "WEBP"]
    )

    preserve_original_format: bool = True
    compress_for_inference: bool = False
    inference_quality: int = 85
    inference_max_size: int = 2048

    skip_corrupted_images: bool = True
    retry_failed_extractions: bool = True
    max_retry_attempts: int = 3

    output_directory: str = "images"
    filename_pattern: str = "image_{page}_{index}"
    add_checksum_to_filename: bool = False
    disable_file_saving: bool = PDFProcessingConfig.DISABLE_FILE_SAVING.value


class ImageFormatDetector:
    """Detects image formats from binary data."""

    FORMAT_SIGNATURES = {
        b"\xff\xd8\xff": "JPEG",
        b"\x89PNG\r\n\x1a\n": "PNG",
        b"GIF87a": "GIF",
        b"GIF89a": "GIF",
        b"BM": "BMP",
        b"II*\x00": "TIFF",
        b"MM\x00*": "TIFF",
        b"RIFF": "WEBP",
    }

    @classmethod
    def detect_format(cls, image_data: bytes) -> str:
        """Detect image format from binary data.

        Parameters
        ----------
        image_data : bytes
            Raw image data.

        Returns
        -------
        str
            Detected format (e.g., "JPEG", "PNG", etc.) or "UNKNOWN".
        """
        if not image_data:
            return "UNKNOWN"

        for signature, format_name in cls.FORMAT_SIGNATURES.items():
            if image_data.startswith(signature):
                return format_name

        try:
            with io.BytesIO(image_data) as buffer:
                with Image.open(buffer) as img:
                    return img.format.upper() if img.format else "UNKNOWN"
        except Exception:
            pass

        return "UNKNOWN"

    @classmethod
    def get_extension(cls, format_name: str) -> str:
        """File extension for a given format.

        Parameters
        ----------
        format_name : str
            Image format name.

        Returns
        -------
        str
            File extension with leading dot.
        """
        format_to_extension = {
            "JPEG": ".jpg",
            "PNG": ".png",
            "TIFF": ".tiff",
            "BMP": ".bmp",
            "GIF": ".gif",
            "WEBP": ".webp",
        }
        return format_to_extension.get(format_name.upper(), ".bin")


class ImageValidator:
    """Validates image integrity and quality."""

    @classmethod
    def validate_image_data(cls, image_data: bytes) -> tuple[bool, str]:
        """
        Validate image data integrity.

        Parameters
        ----------
        image_data : bytes
            Raw image data to validate.

        Returns
        -------
        tuple[bool, str]
            (is_valid, error_message)
        """
        if not image_data:
            return False, "Empty image data"

        if len(image_data) < 100:
            return False, "Image data too small"

        try:
            with io.BytesIO(image_data) as buffer:
                with Image.open(buffer) as img:
                    img.verify()
            return True, ""
        except Exception as e:
            return False, f"Image validation failed: {str(e)}"

    @classmethod
    def validate_image_file(cls, image_path: str) -> tuple[bool, str]:
        """Validate image file.

        Parameters
        ----------
        image_path : str
            Path to image file.

        Returns
        -------
        tuple[bool, str]
            (is_valid, error_message)
        """
        if not os.path.exists(image_path):
            return False, "Image file does not exist"

        try:
            with Image.open(image_path) as img:
                img.load()
                return True, ""
        except Exception as e:
            return False, f"Image file validation failed: {str(e)}"

    @classmethod
    def get_image_info(cls, image_path: str) -> dict[str, object]:
        """Comprehensive image information.

        Parameters
        ----------
        image_path : str
            Path to image file.

        Returns
        -------
        dict[str, object]
            Image information including dimensions, format, size, etc.
        """
        try:
            with Image.open(image_path) as img:
                return {
                    "format": img.format,
                    "mode": img.mode,
                    "size": img.size,
                    "width": img.width,
                    "height": img.height,
                    "file_size": os.path.getsize(image_path),
                }
        except Exception as e:
            return {"error": str(e)}


class ImageCompressor:
    @classmethod
    def compress_for_inference(
        cls,
        image_path: str,
        output_path: str,
        max_size: int = 2048,
        quality: int = 85,
        format: str = "JPEG",
    ) -> bool:
        """Compress image for VLM inference.

        Parameters
        ----------
        image_path : str
            Path to original image.
        output_path : str
            Path for compressed image.
        max_size : int
            Maximum dimension size.
        quality : int
            JPEG quality (1-100).
        format : str
            Output format.

        Returns
        -------
        bool
            True if compression successful.
        """
        try:
            with Image.open(image_path) as img:
                if img.mode in ("RGBA", "LA", "P"):
                    img = img.convert("RGB")

                if max(img.size) > max_size:
                    ratio = max_size / max(img.size)
                    new_size = tuple(int(dim * ratio) for dim in img.size)
                    img = img.resize(new_size, Image.Resampling.LANCZOS)

                img.save(output_path, format=format, quality=quality, optimize=True)
                return True
        except Exception:
            return False

    @classmethod
    def prepare_for_vlm(
        cls, image_path: str, temp_dir: str, max_size: int = 2048, quality: int = 85
    ) -> str | None:
        """Prepare image for VLM inference with compression.

        Parameters
        ----------
        image_path : str
            Path to original image.
        temp_dir : str
            Temporary directory for compressed image.
        max_size : int
            Maximum dimension size.
        quality : int
            JPEG quality.

        Returns
        -------
        str | None
            Path to compressed image or None if failed.
        """
        try:
            original_name = Path(image_path).stem
            compressed_path = os.path.join(temp_dir, f"{original_name}_compressed.jpg")

            if cls.compress_for_inference(
                image_path, compressed_path, max_size, quality
            ):
                return compressed_path
            return None
        except Exception:
            return None


class PDFImageExtractor:
    """PDF image extraction with format preservation."""

    def __init__(self, config: ImageExtractionConfig | None = None):
        """
        Initialize PDF image extractor.

        Parameters
        ----------
        config : ImageExtractionConfig | None
            Configuration for image extraction.
        """
        self.config = config or ImageExtractionConfig()
        self.extraction_stats = {
            "total_attempts": 0,
            "successful_extractions": 0,
            "failed_extractions": 0,
            "corrupted_images": 0,
            "format_preserved": 0,
            "compressed_for_inference": 0,
        }

    def extract_images_from_pdf(
        self, pdf_path: str, output_dir: str
    ) -> list[ImageExtractionResult]:
        """
        Extract all images from PDF using multiple methods.

        Parameters
        ----------
        pdf_path : str
            Path to PDF file.
        output_dir : str
            Output directory for extracted images.

        Returns
        -------
        list[ImageExtractionResult]
            List of extraction results.
        """
        results = []

        results.extend(self._extract_with_pymupdf(pdf_path, output_dir))

        if not results:
            results.extend(self._extract_with_pdfminer(pdf_path, output_dir))

        return results

    def _extract_with_pymupdf(
        self, pdf_path: str, output_dir: str
    ) -> list[ImageExtractionResult]:
        """
        Extract images using PyMuPDF (fitz).

        Parameters
        ----------
        pdf_path : str
            Path to PDF file.
        output_dir : str
            Output directory.

        Returns
        -------
        list[ImageExtractionResult]
            List of extraction results.
        """
        results = []

        try:
            doc = fitz.open(pdf_path)

            for page_num in range(len(doc)):
                page = doc[page_num]
                image_list = page.get_images()

                for img_index, img in enumerate(image_list):
                    self.extraction_stats["total_attempts"] += 1

                    try:
                        xref = img[0]
                        pix = fitz.Pixmap(doc, xref)

                        if pix.n - pix.alpha < 4:
                            img_data = pix.tobytes("png")
                            format_name = "PNG"
                        else:
                            pix1 = fitz.Pixmap(fitz.csRGB, pix)
                            img_data = pix1.tobytes("png")
                            format_name = "PNG"
                            pix1 = None

                        pix = None

                        is_valid, error_msg = ImageValidator.validate_image_data(
                            img_data
                        )
                        if not is_valid:
                            self.extraction_stats["corrupted_images"] += 1
                            results.append(
                                ImageExtractionResult(
                                    success=False,
                                    error_message=error_msg,
                                    extraction_method="pymupdf",
                                )
                            )
                            continue

                        result = self._save_image(
                            img_data,
                            format_name,
                            page_num + 1,
                            img_index + 1,
                            output_dir,
                        )
                        result.extraction_method = "pymupdf"
                        results.append(result)

                        if result.success:
                            self.extraction_stats["successful_extractions"] += 1
                            self.extraction_stats["format_preserved"] += 1
                        else:
                            self.extraction_stats["failed_extractions"] += 1

                    except Exception as e:
                        self.extraction_stats["failed_extractions"] += 1
                        results.append(
                            ImageExtractionResult(
                                success=False,
                                error_message=str(e),
                                extraction_method="pymupdf",
                            )
                        )

            doc.close()

        except Exception:
            pass

        return results

    def _extract_with_pdfminer(
        self, pdf_path: str, output_dir: str
    ) -> list[ImageExtractionResult]:
        """
        Extract images using PDFMiner (fallback method).

        Parameters
        ----------
        pdf_path : str
            Path to PDF file.
        output_dir : str
            Output directory.

        Returns
        -------
        list[ImageExtractionResult]
            List of extraction results.
        """
        results = []

        try:
            for page_num, page_layout in enumerate(extract_pages(pdf_path)):
                page_num += 1

                for obj in page_layout:
                    if isinstance(obj, (LTFigure, LTImage)):
                        self.extraction_stats["total_attempts"] += 1

                        try:
                            if hasattr(obj, "stream"):
                                img_data = obj.stream.get_data()
                            elif hasattr(obj, "_objs"):
                                for sub_obj in obj._objs:
                                    if hasattr(sub_obj, "stream"):
                                        img_data = sub_obj.stream.get_data()
                                        break
                                else:
                                    continue
                            else:
                                continue

                            format_name = ImageFormatDetector.detect_format(img_data)

                            is_valid, error_msg = ImageValidator.validate_image_data(
                                img_data
                            )
                            if not is_valid:
                                self.extraction_stats["corrupted_images"] += 1
                                results.append(
                                    ImageExtractionResult(
                                        success=False,
                                        error_message=error_msg,
                                        extraction_method="pdfminer",
                                    )
                                )
                                continue

                            result = self._save_image(
                                img_data,
                                format_name,
                                page_num,
                                len(results) + 1,
                                output_dir,
                            )
                            result.extraction_method = "pdfminer"
                            results.append(result)

                            if result.success:
                                self.extraction_stats["successful_extractions"] += 1
                                self.extraction_stats["format_preserved"] += 1
                            else:
                                self.extraction_stats["failed_extractions"] += 1

                        except Exception as e:
                            self.extraction_stats["failed_extractions"] += 1
                            results.append(
                                ImageExtractionResult(
                                    success=False,
                                    error_message=str(e),
                                    extraction_method="pdfminer",
                                )
                            )

        except Exception:
            pass

        return results

    def _save_image(
        self,
        img_data: bytes,
        format_name: str,
        page_num: int,
        img_index: int,
        output_dir: str,
    ) -> ImageExtractionResult:
        """
        Save extracted image data to file.

        Parameters
        ----------
        img_data : bytes
            Raw image data.
        format_name : str
            Detected image format.
        page_num : int
            Page number.
        img_index : int
            Image index on page.
        output_dir : str
            Output directory.

        Returns
        -------
        ImageExtractionResult
            Result of save operation.
        """
        try:
            # If file saving is disabled, return success without saving
            if self.config.disable_file_saving:
                return ImageExtractionResult(
                    success=True,
                    image_path="",  # Empty path since no file was saved
                    original_format=format_name,
                    file_size=len(img_data),
                    dimensions=(0, 0),  # Would need to decode image to get dimensions
                    checksum=hashlib.md5(img_data).hexdigest(),
                    extraction_method="skip_save",
                )

            os.makedirs(output_dir, exist_ok=True)

            base_name = self.config.filename_pattern.format(
                page=page_num, index=img_index
            )
            safe_name = re.sub(r"[^\w\-_.]", "_", base_name)

            if self.config.add_checksum_to_filename:
                checksum = hashlib.md5(img_data).hexdigest()[:8]
                safe_name = f"{safe_name}_{checksum}"

            extension = ImageFormatDetector.get_extension(format_name)
            filename = f"{safe_name}{extension}"
            image_path = os.path.join(output_dir, filename)

            with open(image_path, "wb") as f:
                f.write(img_data)

            is_valid, error_msg = ImageValidator.validate_image_file(image_path)
            if not is_valid:
                return ImageExtractionResult(
                    success=False, error_message=error_msg, extraction_method="save"
                )

            img_info = ImageValidator.get_image_info(image_path)

            return ImageExtractionResult(
                success=True,
                image_path=image_path,
                original_format=format_name,
                file_size=img_info.get("file_size", 0),
                dimensions=img_info.get("size", (0, 0)),
                checksum=hashlib.md5(img_data).hexdigest(),
                extraction_method="save",
            )

        except Exception as e:
            return ImageExtractionResult(
                success=False, error_message=str(e), extraction_method="save"
            )

    def get_extraction_stats(self) -> dict[str, object]:
        """
        Get extraction statistics.

        Returns
        -------
        dict[str, object]
            Statistics dictionary.
        """
        stats = self.extraction_stats.copy()
        if stats["total_attempts"] > 0:
            stats["success_rate"] = (
                stats["successful_extractions"] / stats["total_attempts"] * 100
            )
        else:
            stats["success_rate"] = 0.0

        return stats


class VLMImageProcessor:
    """Processes images for VLM inference with optional compression."""

    def __init__(self, config: ImageExtractionConfig | None = None):
        """
        Initialize VLM image processor.

        Parameters
        ----------
        config : ImageExtractionConfig | None
            Configuration for image processing.
        """
        self.config = config or ImageExtractionConfig()
        self.temp_dir = None

    async def prepare_images_for_vlm(self, image_paths: list[str]) -> dict[str, str]:
        """
        Prepare images for VLM inference.

        Parameters
        ----------
        image_paths : list[str]
            List of original image paths.

        Returns
        -------
        dict[str, str]
            Mapping of original paths to processed paths.
        """
        if not self.config.compress_for_inference:
            return {path: path for path in image_paths}

        self.temp_dir = tempfile.mkdtemp(prefix="vlm_images_")

        results = {}
        loop = asyncio.get_event_loop()

        async def process_single_image(image_path: str) -> tuple[str, str]:
            """Process a single image for VLM inference."""
            with ThreadPoolExecutor() as executor:
                compressed_path = await loop.run_in_executor(
                    executor,
                    ImageCompressor.prepare_for_vlm,
                    image_path,
                    self.temp_dir,
                    self.config.inference_max_size,
                    self.config.inference_quality,
                )
                return image_path, compressed_path or image_path

        tasks = [process_single_image(path) for path in image_paths]
        processed_results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in processed_results:
            if isinstance(result, Exception):
                continue
            original_path, processed_path = result
            results[original_path] = processed_path

        return results

    def cleanup_temp_files(self) -> None:
        """Clean up temporary compressed image files."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception:
                pass
            self.temp_dir = None


def extract_images_from_pdf(
    pdf_path: str, output_dir: str, config: ImageExtractionConfig | None = None
) -> list[ImageExtractionResult]:
    """Extract images from PDF.

    Parameters
    ----------
    pdf_path : str
        Path to PDF file.
    output_dir : str
        Output directory for extracted images.
    config : ImageExtractionConfig | None
        Configuration for extraction.

    Returns
    -------
    list[ImageExtractionResult]
        List of extraction results.
    """
    extractor = PDFImageExtractor(config)
    return extractor.extract_images_from_pdf(pdf_path, output_dir)


async def prepare_images_for_vlm_inference(
    image_paths: list[str], config: ImageExtractionConfig | None = None
) -> dict[str, str]:
    """Prepare images for VLM inference with optional compression.

    Parameters
    ----------
    image_paths : list[str]
        List of image paths to process.
    config : ImageExtractionConfig | None
        Configuration for processing.

    Returns
    -------
    dict[str, str]
        Mapping of original paths to processed paths.
    """
    processor = VLMImageProcessor(config)
    return await processor.prepare_images_for_vlm(image_paths)
