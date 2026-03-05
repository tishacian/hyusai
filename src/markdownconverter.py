import asyncio
import multiprocessing as mp
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTChar, LTCurve, LTLine, LTTextBox

try:
    from src.vlmprocessor import VLMProcessor, VLMResult, get_supported_models

    VLM_AVAILABLE = True
except ImportError:
    VLM_AVAILABLE = False

    class VLMProcessor:
        def __init__(self, *args, **kwargs):
            pass

    class VLMResult:
        def __init__(self, *args, **kwargs):
            pass

    def get_supported_models():
        return []


from src.globalvariables import PDFProcessingConfig
from src.imageextractor import (
    ImageExtractionConfig,
    PDFImageExtractor,
    prepare_images_for_vlm_inference,
)


@dataclass
class ImagePosition:
    page_num: int
    y_position: float
    image_index: int
    image_path: str
    image_name: str


@dataclass
class ConverterConfig:
    max_workers: int = field(default_factory=lambda: min(32, (mp.cpu_count() or 1) + 4))
    extract_images: bool = True
    extract_tables: bool = True
    preserve_original_format: bool = True
    compress_for_inference: bool = False
    inference_quality: int = 85
    inference_max_size: int = 2048
    skip_corrupted_images: bool = True
    retry_failed_extractions: bool = True
    enable_vlm: bool = False
    vlm_model: str = "smolvlm-256m"
    vlm_workers: int = 2
    vlm_kwargs: dict[str, object] = field(default_factory=dict)
    include_summary: bool = True
    export_excel: bool = True
    filter_nonexistent_images: bool = True
    disable_file_saving: bool = PDFProcessingConfig.DISABLE_FILE_SAVING.value

    def __post_init__(self) -> None:
        """
        Validate configuration after initialization.

        Raises
        ------
        ValueError
            If VLM model is not supported or worker counts are invalid.
        """
        if self.max_workers < 1:
            self.max_workers = 1
        if self.vlm_workers < 1:
            self.vlm_workers = 1
        if self.enable_vlm and self.vlm_model not in get_supported_models():
            raise ValueError(f"Unsupported VLM model: {self.vlm_model}")


class SummaryTable:
    def __init__(self, title: str):
        self.title = title
        self.rows = []

    def add_row(self, metric: str, value, description: str) -> None:
        """Add ign row to summary table

        Parameters
        ----------
        metric : str
            metric name.
        value : TYPE
            metric value.
        description : str
            metric description.

        Returns
        -------
        None
            None.

        """
        self.rows.append((metric, value, description))

    def add_section(self, section_name: str) -> None:
        """Adding section to summary table

        Parameters
        ----------
        section_name : str
            section name.

        Returns
        -------
        None
            None.

        """
        self.add_row("", "", "")  # Empty row
        self.add_row(f"**{section_name}**", "", "")  # Section header

    def to_markdown(self) -> str:
        """Markdown output

        Returns
        -------
        str
            markdown output.

        """
        lines = [
            f"# {self.title}\n",
            "| Metric | Value | Description |",
            "|--------|-------|-------------|",
        ]

        lines.extend(
            [
                f"| {metric} | {value} | {description} |"
                for metric, value, description in self.rows
            ]
        )

        return "\n".join(lines) + "\n\n"


class PDFToMarkdownConverter:
    """PDF-to-Markdown converter w/ image extraction and VLM analysis.

    Provides a clean interface for converting PDF documents to
    Markdown format while preserving document structure and
    optionally analyzing images using Vision Language Models.

    Attributes
    ----------
    config : ConverterConfig
        Converter configuration settings.
    stats : dict[str, int | float | dict[str, int]]
        Dictionary to store document analysis statistics.
    document_structure : list[dict]
        List to store document structure information.
    vlm_processor : VLMProcessor | None
        VLM processor instance (if enabled).
    vlm_results : dict[str, VLMResult]
        Dictionary of VLM analysis results.
    images_dir : str | None
        Directory path for extracted images.
    image_positions : List[ImagePosition]
        List of image positions for proper placement in markdown.
    """

    def __init__(self, config: ConverterConfig | None = None) -> None:
        """Initialize the PDF-to-Markdown converter.

        Parameters
        ----------
        config : ConverterConfig, optional
            Configuration object. If None, uses default settings.

        Raises
        ------
        ValueError
            If VLM model is not supported.
        """
        self.config = config or ConverterConfig()
        self.stats = self._initialize_stats()
        self.document_structure: list[dict[str, object]] = []
        self.vlm_processor: VLMProcessor | None = None
        self.vlm_results: dict[str, VLMResult] = {}
        self.images_dir: str | None = None
        self.image_positions: list[ImagePosition] = []
        self._hierarchy_counter = {"main": 0, "sub": 0, "subsub": 0}

        if self.config.enable_vlm and VLM_AVAILABLE:
            self._initialize_vlm()
        elif self.config.enable_vlm and not VLM_AVAILABLE:
            print("Warning: VLM requested but not available. Disabling VLM.")
            self.config.enable_vlm = False

    def _initialize_stats(self) -> dict[str, int | float | dict[str, int]]:
        """Initialize statistics dictionary.

        Returns
        -------
        dict[str, int | float | dict[str, int]]
            Statistics dictionary with default values.
        """
        return {
            "pages": 0,
            "images": {
                "total": 0,
                "named": 0,
                "generic": 0,
                "extracted": 0,
                "successful": 0,
                "failed": 0,
                "corrupted": 0,
            },
            "tables": {"total": 0, "named": 0, "generic": 0},
            "headers": {"h1": 0, "h2": 0, "h3": 0, "h4": 0, "h5": 0, "h6": 0},
            "paragraphs": 0,
            "word_count": 0,
            "file_size": 0,
            "processing_time": 0,
            "vlm_processed_images": 0,
            "vlm_successful_analyses": 0,
            "vlm_failed_analyses": 0,
            "vlm_processing_time": 0.0,
            "text_stats": {
                "total_characters": 0,
                "total_sentences": 0,
                "total_lines": 0,
                "unique_words": 0,
                "average_sentence_length": 0.0,
                "average_word_length": 0.0,
                "reading_time_minutes": 0.0,
            },
        }

    def _initialize_vlm(self) -> None:
        try:
            self.vlm_processor = VLMProcessor(
                model_type=self.config.vlm_model,
                max_workers=self.config.vlm_workers,
                **self.config.vlm_kwargs,
            )
        except Exception:
            self.config.enable_vlm = False

    async def convert(
        self, pdf_path: str, output_dir: str | None = None
    ) -> dict[str, str]:
        """Convert PDF to Markdown with enhanced image extraction and VLM analysis.

        Parameters
        ----------
        pdf_path : str
            Path to the input PDF file.
        output_dir : str, optional
            Output directory. If None, uses PDF directory.

        Returns
        -------
        dict[str, str]
            Dictionary containing paths to generated files:
            - 'markdown': Path to markdown file
            - 'excel': Path to Excel structure file (if enabled)
            - 'images_dir': Path to images directory

        Raises
        ------
        FileNotFoundError
            If PDF file doesn't exist.
        ValueError
            If PDF processing fails.
        """
        start_time = time.time()

        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        output_paths = self._setup_output_dirs(pdf_path, output_dir)
        self.images_dir = output_paths["images_dir"]

        try:
            if self.config.extract_images and not self.config.disable_file_saving:
                self._extract_images_with_positions(
                    pdf_path, output_paths["images_dir"]
                )

            markdown_content = await self._extract_pdf_content(pdf_path)

            if self.config.enable_vlm and self.config.extract_images:
                await self._process_images_with_vlm(output_paths["images_dir"])
                markdown_content = self.markdown_with_vlm(markdown_content)

            if not self.config.disable_file_saving:
                self._write_markdown_file(output_paths["markdown"], markdown_content)

                if self.config.export_excel:
                    self._export_structure_to_excel(output_paths["excel"])

            self.stats["processing_time"] = time.time() - start_time
            self.stats["file_size"] = os.path.getsize(pdf_path)

            # Return empty paths if file saving is disabled
            if self.config.disable_file_saving:
                return {
                    "markdown": "",
                    "excel": "",
                    "images_dir": "",
                    "output_dir": "",
                }

            return output_paths

        except Exception as e:
            raise ValueError(f"PDF conversion failed: {e}")

    def _setup_output_dirs(
        self, pdf_path: str, output_dir: str | None
    ) -> dict[str, str]:
        """Setup output directories and return file paths.

        Parameters
        ----------
        pdf_path : str
            Path to input PDF file.
        output_dir : str, optional
            Optional output directory.

        Returns
        -------
        dict[str, str]
            Dictionary with output file paths.
        """
        pdf_path_obj = Path(pdf_path)
        pdf_base = pdf_path_obj.stem

        if output_dir is None:
            output_dir = pdf_path_obj.parent / pdf_base
        else:
            output_dir = Path(output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)
        images_dir = output_dir / "images"
        images_dir.mkdir(exist_ok=True)

        return {
            "markdown": str(output_dir / f"{pdf_base}.md"),
            "excel": str(output_dir / f"{pdf_base}_structure.xlsx"),
            "images_dir": str(images_dir),
            "output_dir": str(output_dir),
        }

    def _extract_images_with_positions(self, pdf_path: str, images_dir: str) -> None:
        """Extract images and record their positions for proper markdown placement.

        Parameters
        ----------
        pdf_path : str
            Path to PDF file.
        images_dir : str
            Directory to save extracted images.
        """
        # -- image extraction config from converter config
        image_config = ImageExtractionConfig(
            preserve_original_format=(self.config.preserve_original_format),
            compress_for_inference=self.config.compress_for_inference,
            inference_quality=self.config.inference_quality,
            inference_max_size=self.config.inference_max_size,
            skip_corrupted_images=self.config.skip_corrupted_images,
            retry_failed_extractions=self.config.retry_failed_extractions,
            output_directory=images_dir,
        )

        extractor = PDFImageExtractor(image_config)
        extraction_results = extractor.extract_images_from_pdf(pdf_path, images_dir)

        # log extraction success/failure
        for result in extraction_results:
            if result.success:
                filename = os.path.basename(result.image_path)
                match = re.search(r"image_(\d+)_(\d+)", filename)
                if match:
                    page_num = int(match.group(1))
                    image_index = int(match.group(2))

                    image_pos = ImagePosition(
                        page_num=page_num,
                        y_position=0.0,
                        image_index=image_index,
                        image_path=result.image_path,
                        image_name=filename,
                    )
                    self.image_positions.append(image_pos)

                    self.stats["images"]["extracted"] += 1
                    self.stats["images"]["successful"] += 1
                else:
                    self.stats["images"]["failed"] += 1
            else:
                self.stats["images"]["failed"] += 1

    def _get_images_for_page(self, page_num: int) -> list[ImagePosition]:
        """Get images that belong to a specific page.

        Parameters
        ----------
        page_num : int
            Page number.

        Returns
        -------
        List[ImagePosition]
            List of image positions for the page.
        """
        return [img for img in self.image_positions if img.page_num == page_num]

    def _insert_image_tag(self, image_pos: ImagePosition, output_dir: str) -> str:
        """Create markdown image tag for an image.

        Parameters
        ----------
        image_pos : ImagePosition
            Image position information.
        output_dir : str
            Output directory for markdown file.

        Returns
        -------
        str
            Markdown image tag.
        """
        relative_path = f"images/{image_pos.image_name}"

        return f"\n![{image_pos.image_name}]({relative_path})\n\n"

    async def _extract_pdf_content(self, pdf_path: str) -> str:
        """Extract content from PDF and convert to markdown.

        Parameters
        ----------
        pdf_path : str
            Path to PDF file.

        Returns
        -------
        str
            Markdown content as string.
        """
        self.document_structure = []
        if not hasattr(self, "stats") or "text_stats" not in self.stats:
            self.stats = self._initialize_stats()
        else:
            self.stats.update(
                {
                    "pages": 0,
                    "tables": {"total": 0, "named": 0, "generic": 0},
                    "headers": {
                        "h1": 0,
                        "h2": 0,
                        "h3": 0,
                        "h4": 0,
                        "h5": 0,
                        "h6": 0,
                    },
                    "paragraphs": 0,
                    "word_count": 0,
                    "text_stats": {
                        "total_characters": 0,
                        "total_sentences": 0,
                        "total_lines": 0,
                        "unique_words": 0,
                        "average_sentence_length": 0.0,
                        "average_word_length": 0.0,
                        "reading_time_minutes": 0.0,
                    },
                }
            )

        pages = list(extract_pages(pdf_path))

        markdown_parts = []
        semaphore = asyncio.Semaphore(self.config.max_workers)

        async def process_page_with_semaphore(page_num_and_layout):
            async with semaphore:
                page_num, page_layout = page_num_and_layout
                loop = asyncio.get_event_loop()
                with ThreadPoolExecutor(max_workers=1) as executor:
                    result = await loop.run_in_executor(
                        executor,
                        self._process_page_sync,
                        page_num,
                        page_layout,
                    )
                return page_num, result, page_layout

        page_tasks = [
            process_page_with_semaphore((i + 1, page_layout))
            for i, page_layout in enumerate(pages)
        ]

        results = await asyncio.gather(*page_tasks, return_exceptions=True)

        successful_results = []
        for result in results:
            if isinstance(result, Exception):
                continue
            successful_results.append(result)

        successful_results.sort(key=lambda x: x[0])

        for page_num, page_content, page_layout in successful_results:
            self.stats["pages"] += 1
            self._update_stats(page_content, list(page_layout))
            markdown_parts.append(page_content)

        markdown_content = "".join(markdown_parts)

        if self.config.include_summary:
            summary = self._format_document_summary()
            markdown_content = summary + "\n\n" + markdown_content

        return markdown_content

    def _process_page_sync(self, page_num: int, page_layout: object) -> str:
        """Process a single page synchronously.

        Parameters
        ----------
        page_num : int
            Page number.
        page_layout : object
            PDF page layout object.

        Returns
        -------
        str
            Markdown content for the page.
        """
        try:
            page_content = []
            page_separator = f"{'─' * 35} page {page_num} {'─' * 35}\n\n"
            page_content.append(page_separator)

            page_elements = list(page_layout)
            page_images = self._get_images_for_page(page_num)
            # -- sort images by index for consistent ordering
            page_images.sort(key=lambda x: x.image_index)

            if self.config.extract_tables:
                table_box = self._detect_table(page_elements)
                if table_box:
                    table_markdown = self._format_table(
                        table_box, page_elements, page_elements, page_num
                    )
                    if table_markdown:
                        page_content.append(table_markdown)
                        self._add_to_structure(
                            page_num,
                            "table",
                            table_markdown.strip(),
                            table_markdown.strip(),
                        )

            # -- process text content and insert images at appropriate positions
            self._process_text_content_with_images(
                page_elements, page_content, page_num, page_images
            )

            return "".join(page_content)

        except Exception as e:
            return f"{'─' * 35} page {page_num} {'─' * 35}\n\nError: {str(e)}\n\n"

    def _process_text_content_with_images(
        self,
        page_elements: list,
        page_content: list[str],
        page_num: int,
        page_images: list[ImagePosition],
    ) -> None:
        """Process text content and insert images at appropriate positions.

        Parameters
        ----------
        page_elements : list
            Page layout elements.
        page_content : list[str]
            List to append markdown content.
        page_num : int
            Page number.
        page_images : List[ImagePosition]
            Images found on this page.
        """
        text_boxes = [elem for elem in page_elements if isinstance(elem, LTTextBox)]
        text_boxes.sort(key=lambda x: x.y0, reverse=True)
        page_images.sort(key=lambda x: x.image_index)
        merged_text_boxes = self._merge_split_headers(text_boxes)

        # -- insert images at appropriate positions
        for i, text_box in enumerate(merged_text_boxes):
            text = text_box.get_text().strip()
            if text:
                header_level = self._get_header_level(text_box)

                if header_level > 0:
                    hashes = "#" * header_level
                    formatted_text = f"{hashes} {text}\n\n"
                    if 1 <= header_level <= 6:
                        self.stats["headers"][f"h{header_level}"] += 1
                    else:
                        self.stats["headers"]["h1"] += 1  # fallback to h1

                    page_content.append(formatted_text)
                    self._add_to_structure(page_num, "text", text, text, header_level)
                else:
                    # Check if it's a bullet point
                    if self._is_bullet_point(text):
                        formatted_text = f"{text}\n\n"
                        page_content.append(formatted_text)
                        self._add_to_structure(page_num, "text", text, text, 0)
                        self.stats["paragraphs"] += 1  # Count as paragraph for stats
                    else:
                        formatted_text = f"{text}\n\n"
                        page_content.append(formatted_text)
                        self._add_to_structure(page_num, "text", text, text, 0)
                        self.stats["paragraphs"] += 1

                if page_images:
                    image_pos = page_images.pop(0)
                    image_tag = self._insert_image_tag(
                        image_pos,
                        (os.path.dirname(self.images_dir) if self.images_dir else "."),
                    )
                    page_content.append(image_tag)
                    self._add_to_structure(
                        page_num,
                        "image",
                        image_pos.image_name,
                        image_pos.image_name,
                    )

        for image_pos in page_images:
            image_tag = self._insert_image_tag(
                image_pos,
                os.path.dirname(self.images_dir) if self.images_dir else ".",
            )
            page_content.append(image_tag)
            self._add_to_structure(
                page_num, "image", image_pos.image_name, image_pos.image_name
            )

    def _merge_split_headers(self, text_boxes: list) -> list:
        """Heuristics to merge text boxes that are likely split headers.

        Parameters
        ----------
        text_boxes : list
            List of text boxes to analyze.

        Returns
        -------
        list
            List of merged text boxes.
        """
        if not text_boxes:
            return text_boxes

        merged_boxes = []
        i = 0

        while i < len(text_boxes):
            current_box = text_boxes[i]
            current_text = current_box.get_text().strip()

            if self._is_header_start(current_text):
                merged_text = current_text
                j = i + 1

                while j < len(text_boxes):
                    next_box = text_boxes[j]
                    next_text = next_box.get_text().strip()

                    if self._boxes_are_close(
                        current_box, next_box
                    ) and self._is_header_continuation(next_text):
                        merged_text += " " + next_text
                        j += 1
                    else:
                        break

                merged_box = self._create_merged_text_box(current_box, merged_text)
                merged_boxes.append(merged_box)
                i = j  # Skip the merged boxes
            else:
                merged_boxes.append(current_box)
                i += 1

        return merged_boxes

    def _is_header_start(self, text: str) -> bool:
        """Check if text looks like the start of a header.

        Parameters
        ----------
        text : str
            Text to analyze.

        Returns
        -------
        bool
            True if text looks like header start.
        """
        if not text:
            return False

        # Check for header patterns
        header_patterns = [
            r"^\.+\d+",  # Periods followed by numbers
            r"^\d+\.+",  # Numbers followed by periods
            r"^[A-Z]+$",  # All caps short text
            r"^[A-Z][a-z]+",  # Title case
        ]

        for pattern in header_patterns:
            if re.match(pattern, text):
                return True

        return False

    def _is_header_continuation(self, text: str) -> bool:
        """Check if text looks like a header continuation.

        Parameters
        ----------
        text : str
            Text to analyze.

        Returns
        -------
        bool
            True if text looks like header continuation.
        """
        if not text:
            return False

        #  -- short text without periods or special characters is likely a continuation
        if len(text) < 20 and not re.search(r"[.!?]", text):
            return True

        return False

    def _boxes_are_close(self, box1: LTTextBox, box2: LTTextBox) -> bool:
        """Check if two text boxes are close enough to be part of the same header.

        Parameters
        ----------
        box1 : LTTextBox
            First text box.
        box2 : LTTextBox
            Second text box.

        Returns
        -------
        bool
            True if boxes are close enough.
        """
        # -- vertical proximity
        vertical_distance = abs(box1.y0 - box2.y0)
        if vertical_distance > 20:
            return False

        # -- horizontal proximity (within 100 points)
        horizontal_distance = abs(box1.x0 - box2.x0)
        if horizontal_distance > 100:
            return False

        return True

    def _create_merged_text_box(
        self, original_box: LTTextBox, merged_text: str
    ) -> LTTextBox:
        """Create a new text box with merged text.

        Parameters
        ----------
        original_box : LTTextBox
            Original text box to use as template.
        merged_text : str
            Merged text content.

        Returns
        -------
        LTTextBox
            New text box with merged content.
        """

        class MergedTextBox:
            def __init__(self, original_box, text):
                self.x0 = original_box.x0
                self.y0 = original_box.y0
                self.x1 = original_box.x1
                self.y1 = original_box.y1
                self._text = text

            def get_text(self):
                return self._text

            def __iter__(self):
                return iter(original_box)

        return MergedTextBox(original_box, merged_text)

    def _detect_table(self, elements: list) -> tuple | None:
        """Detect table structure in page elements.

        Parameters
        ----------
        elements : list
            List of PDF layout elements.

        Returns
        -------
        tuple | None
            Table boundaries tuple or None if no table found.
        """
        lines = [e for e in elements if isinstance(e, (LTLine, LTCurve))]
        if len(lines) < 4:
            return None

        horizontal_lines = [line for line in lines if abs(line.y0 - line.y1) < 2]
        vertical_lines = [line for line in lines if abs(line.x0 - line.x1) < 2]

        if len(horizontal_lines) < 2 or len(vertical_lines) < 2:
            return None

        table_x0 = min(line.x0 for line in vertical_lines)
        table_x1 = max(line.x0 for line in vertical_lines)
        table_y0 = min(line.y0 for line in horizontal_lines)
        table_y1 = max(line.y0 for line in horizontal_lines)

        table_width = table_x1 - table_x0
        table_height = table_y1 - table_y0

        if table_width < 50 or table_height < 30:
            return None

        return (table_x0, table_y0, table_x1, table_y1)

    def _format_table(
        self,
        table_box: tuple,
        elements: list,
        page_elements: list,
        page_num: int,
    ) -> str:
        """Format table as markdown.

        Parameters
        ----------
        table_box : tuple
            Table boundaries.
        elements : list
            Page elements.
        page_elements : list
            All page elements.
        page_num : int
            Page number.

        Returns
        -------
        str
            Markdown formatted table.
        """
        table_name = f"table-{page_num}-{self.stats['tables']['total'] + 1}"
        table_x0, table_y0, table_x1, table_y1 = table_box

        self.stats["tables"]["total"] += 1
        self.stats["tables"]["generic"] += 1

        table_text_boxes = []
        for elem in page_elements:
            if isinstance(elem, LTTextBox):
                if table_x0 <= elem.x0 <= table_x1 and table_y0 <= elem.y0 <= table_y1:
                    table_text_boxes.append(elem)

        table_text_boxes.sort(key=lambda x: (-x.y0, x.x0))

        table_content = []
        for text_box in table_text_boxes:
            text = text_box.get_text().strip()
            if text:
                table_content.append(text)

        if table_content:
            table_markdown = f"\n**Table: {table_name}**\n\n"
            table_markdown += "| " + " | ".join(table_content) + " |\n"
            table_markdown += "|" + "---|" * len(table_content) + "\n"
            table_markdown += "| " + " | ".join(table_content) + " |\n\n"
        else:
            table_markdown = (
                f"\n**Table: {table_name}**\n\n"
                f"[Table content extracted but no text found]\n\n"
            )

        return table_markdown

    def _detect_header_by_pattern(self, text: str, font_size: float) -> int:
        """Detect headers based on text patterns commonly found in documents.
            This is by far the hardest part of the algo to detect ehaders.

        Parameters
        ----------
        text : str
            Text content to analyze.
        font_size : float
            Font size of the text.

        Returns
        -------
        int
            Header level (1-6) or 0 if not a header.
        """
        clean_text = text.strip()

        if len(clean_text) < 2:
            return 0

        if (
            clean_text.startswith("•")
            or clean_text.startswith("-")
            or clean_text.startswith("*")
        ):
            return 0

        if len(clean_text) > 80:
            return 0

        word_count = len(clean_text.split())
        if word_count > 6:
            return 0

        if clean_text.count(" ") > 10:
            return 0

        if re.search(r"[.!?]\s+[A-Z]", clean_text):
            return 0

        main_title_patterns = [
            r"^\d+[A-Z]+",  # digits followed by uppercase letters
            r"^\d+\.[a-zA-Z]+",  # digit.letters pattern
        ]

        for pattern in main_title_patterns:
            if re.match(pattern, clean_text):
                return 1

        complex_section_pattern = r"^(\d+\.{2,}\d+|\d+\.\d+\.{2,}|\d+\.\d+\.\d+)\.?[a-zA-Z]"  # complicated patterns
        if re.match(complex_section_pattern, clean_text):
            dots_count = clean_text.count(".")
            numbers_count = len(
                re.findall(
                    r"\d+",
                    (
                        clean_text.split(".")[0]
                        if "." in clean_text
                        else clean_text[:20]
                    ),
                )
            )

            if dots_count >= 5 or numbers_count >= 4:
                return 5
            elif dots_count >= 3 or numbers_count >= 3:
                return 4
            else:
                return 3

        # -- sections
        if clean_text.startswith("."):
            period_count = len(clean_text) - len(clean_text.lstrip("."))
            if re.match(r"^\.+\d+", clean_text):
                if period_count >= 3:
                    return 6
                elif period_count >= 2:
                    return 5
                else:
                    return 4

        # -- numbered sections
        simple_numbered_pattern = r"^\d+\.{1,3}\d*\.?[a-zA-Z]?"
        if re.match(simple_numbered_pattern, clean_text) and not re.match(
            complex_section_pattern, clean_text
        ):
            return 3

        # -- sectin subheads + special characters
        special_section_pattern = r"^(\d+\.{2,}[a-zA-Z]|\.{4,}\d+)"
        if re.match(special_section_pattern, clean_text):
            return 2

        # -- figure and table references
        figure_table_patterns = [
            r"^(regFiu|uirFge|Figure|reFugi|Feuirg|Fgeiur|Feugir|uFeigr|rguFie)",
            r"^(bealT|Table|eabTl|Teabl|ealTb|lbeaT)",
            r".*[–—-].*",  # Contains dash/em-dash
        ]

        for pattern in figure_table_patterns:
            if re.match(pattern, clean_text, re.IGNORECASE):
                return 4

        # front-sized headers
        if font_size > 18:
            return 1
        elif font_size > 16:
            if word_count <= 3:
                return 2
            else:
                return 3
        elif font_size > 14:
            if word_count <= 2:
                return 3
            else:
                return 4
        elif font_size > 12:
            if word_count <= 2:
                return 4
            else:
                return 5
        elif font_size > 10:
            if word_count <= 1:
                return 5
            else:
                return 6

        if clean_text.isupper() and word_count <= 4 and len(clean_text) >= 3:
            return 3

        if (
            word_count <= 3
            and any(char.isupper() for char in clean_text)
            and len(clean_text) >= 5
        ):
            return 5

        return 0

    def _detect_header_by_font_size(self, font_size: float) -> int:
        """Detect headers based on font size only (fallback method).

        Parameters
        ----------
        font_size : float
            Font size to analyze.

        Returns
        -------
        int
            Header level (1-6) or 0 if not a header.
        """
        if font_size > 20:
            return 1
        elif font_size > 18:
            return 2
        elif font_size > 16:
            return 3
        elif font_size > 14:
            return 4
        elif font_size > 12:
            return 5
        elif font_size > 10:
            return 6
        return 0

    def _get_header_level(self, text_box: LTTextBox) -> int:
        """Determine header level based on font size and text patterns.

        Parameters
        ----------
        text_box : LTTextBox
            Text box element.

        Returns
        -------
        int
            Header level (1-6) or 0 if not a header.
        """
        try:
            text = text_box.get_text().strip()
            if not text:
                return 0

            first_char = next(
                (char for char in text_box if isinstance(char, LTChar)), None
            )
            size = first_char.size if first_char else 12.0
            header_level = self._detect_header_by_pattern(text, size)
            if header_level > 0:
                return header_level

            if first_char and size > 0:
                return self._detect_header_by_font_size(size)

            return self._detect_header_by_pattern(text, 12.0)

        except Exception:
            try:
                text = text_box.get_text().strip()
                if text:
                    return self._detect_header_by_pattern(text, 12.0)
            except Exception:
                pass
            return 0

    def _add_to_structure(
        self,
        page_num: int,
        element_type: str,
        content: str,
        original_text: str = None,
        header_level: int = 0,
    ) -> None:
        """Add element to document structure with enhanced metadata.

        Parameters
        ----------
        page_num : int
            Page number.
        element_type : str
            Type of element.
        content : str
            Element content.
        original_text : str, optional
            Original text as read from PDF.
        header_level : int, optional
            Header level if it's a header.
        """
        subtype = self._determine_subtype(content, element_type)
        is_header = header_level > 0 or self._is_header_content(content)
        original_hierarchy = (
            self._extract_original_hierarchy(content) if is_header else ""
        )
        current_hierarchy = (
            self._get_current_hierarchy(header_level) if is_header else ""
        )
        structural_context = self._get_context_for_element(
            content, header_level, element_type
        )
        semantic_context = self._extract_semantic_context(
            content, element_type, page_num
        )
        # -- structure and semantic context
        if structural_context:
            context = f"{structural_context} - {semantic_context}"
        else:
            context = semantic_context

        raw_data = self._get_raw_data_content(content, element_type, page_num)

        self.document_structure.append(
            {
                "page": page_num,
                "type": element_type,
                "content": content,
                "original_text": original_text or content,
                "position": len(self.document_structure),
                "is_header": is_header,
                "header_level": header_level,
                "subtype": subtype,
                "original_hierarchy": original_hierarchy,
                "hierarchy": current_hierarchy,
                "context": context,
                "raw_data": raw_data,
            }
        )

    def _determine_subtype(self, content: str, element_type: str) -> str:
        """Determine the subtype of an element.

        Parameters
        ----------
        content : str
            Element content.
        element_type : str
            Type of element.

        Returns
        -------
        str
            Subtype of the element.
        """
        if element_type == "image":
            return "image"
        elif element_type == "table":
            return "table"
        elif element_type == "text":
            content_clean = content.strip()
            if content_clean.startswith("#") or re.match(r"^\d+\.", content_clean):
                return "heading"
            elif self._is_bullet_point(content_clean):
                return "bullet"
            else:
                return "paragraph"
        return "unknown"

    def _is_header_content(self, content: str) -> bool:
        """Check if content is a header.

        Parameters
        ----------
        content : str
            Content to check.

        Returns
        -------
        bool
            True if content is a header.
        """
        content_clean = content.strip()
        return (
            content_clean.startswith("#")
            or re.match(r"^\d+\.", content_clean)
            or self._is_header_start(content_clean)
        )

    def _extract_original_hierarchy(self, content: str) -> str:
        """Extract original hierarchy from content.

        Parameters
        ----------
        content : str
            Content to extract hierarchy from.

        Returns
        -------
        str
            Original hierarchy string.
        """
        # Extract patterns like "III.2)d. Requirements GPU"
        patterns = [
            r"^([IVX]+\.\d+\)[a-z]?\.?\s*[A-Z][^.]*)",  # Roman numerals
            r"^(\d+\.\d+\)[a-z]?\.?\s*[A-Z][^.]*)",  # Numbers
            r"^([A-Z]\.\d+\)[a-z]?\.?\s*[A-Z][^.]*)",  # Letters
        ]

        for pattern in patterns:
            match = re.match(pattern, content)
            if match:
                return match.group(1)

        return content.strip()

    def _get_current_hierarchy(self, header_level: int) -> str:
        """Get current hierarchy level.

        Parameters
        ----------
        header_level : int
            Header level.

        Returns
        -------
        str
            Current hierarchy string.
        """
        if header_level == 1:
            self._hierarchy_counter["main"] += 1
            self._hierarchy_counter["sub"] = 0
            self._hierarchy_counter["subsub"] = 0
            return str(self._hierarchy_counter["main"])
        elif header_level == 2:
            self._hierarchy_counter["sub"] += 1
            self._hierarchy_counter["subsub"] = 0
            return f"{self._hierarchy_counter['main']}.{self._hierarchy_counter['sub']}"
        elif header_level == 3:
            self._hierarchy_counter["subsub"] += 1
            return f"{self._hierarchy_counter['main']}.{self._hierarchy_counter['sub']}-{self._hierarchy_counter['subsub']}"

        return ""

    def _get_context_for_element(
        self, content: str, header_level: int, element_type: str = "text"
    ) -> str:
        """Get intelligent context for an element based on its type and position.

        Parameters
        ----------
        content : str
            Element content.
        header_level : int
            Header level.
        element_type : str
            Type of element (text, image, table, etc.)

        Returns
        -------
        str
            Context string with intelligent extraction.
        """
        if header_level > 0:
            if header_level == 2:
                return content.strip()
            elif header_level > 2:
                for item in reversed(self.document_structure):
                    if item.get("header_level") == 2:
                        return item.get("content", "").strip()

        if element_type == "text":
            for item in reversed(self.document_structure):
                if item.get("header_level", 0) > 0:
                    return item.get("content", "").strip()

        elif element_type == "image":
            for item in reversed(self.document_structure):
                if item.get("type") == "text" and item.get("header_level", 0) > 0:
                    return item.get("content", "").strip()
                elif item.get("type") == "text" and len(item.get("content", "")) > 10:
                    return item.get("content", "")[:50] + "..."

        elif element_type == "table":
            for item in reversed(self.document_structure):
                content_text = item.get("content", "").lower()
                if (
                    "table" in content_text
                    or "figure" in content_text
                    or "data" in content_text
                    or "summary" in content_text
                ):
                    return item.get("content", "").strip()
                elif item.get("header_level", 0) > 0:
                    return item.get("content", "").strip()

        elif element_type == "bullet":
            for item in reversed(self.document_structure):
                if item.get("type") == "text" and item.get("header_level", 0) > 0:
                    return item.get("content", "").strip()

        return ""

    def _get_raw_data_content(
        self, content: str, element_type: str = "text", page_num: int = 1
    ) -> str:
        """Get intelligent raw data for different element types.

        Parameters
        ----------
        content : str
            Element content.
        element_type : str
            Type of element (text, image, table, bullet, etc.)
        page_num : int
            Page number for context.

        Returns
        -------
        str
            Raw data content or blob reference.
        """
        if element_type == "image":
            # Extract image filename and create blob storage link
            if "images/" in content:
                filename = content.split("images/")[-1].split(")")[0]
                return f"blob://images/{filename}"
            elif content.endswith((".png", ".jpg", ".jpeg", ".tiff", ".bmp")):
                return f"blob://images/{content}"
            else:
                return f"blob://images/{content}.png"  # Default extension

        elif element_type == "table":
            return content

        elif element_type == "text":
            return content

        elif element_type == "bullet":
            return content

        return ""

    def _extract_semantic_context(
        self, content: str, element_type: str, page_num: int
    ) -> str:
        """Extract semantic context by analyzing content patterns and relationships.

        Parameters
        ----------
        content : str
            Element content.
        element_type : str
            Type of element.
        page_num : int
            Page number.

        Returns
        -------
        str
            Semantic context description.
        """
        if element_type == "image":
            image_keywords = self._extract_image_keywords(content)
            if image_keywords:
                return f"Image related to: {', '.join(image_keywords)}"
            return "Document image"

        elif element_type == "table":
            table_keywords = self._extract_table_keywords(content)
            if table_keywords:
                return f"Table containing: {', '.join(table_keywords)}"
            return "Data table"

        elif element_type == "bullet":
            if "requirements" in content.lower():
                return "Requirements list"
            elif "features" in content.lower():
                return "Features list"
            elif "steps" in content.lower() or "procedure" in content.lower():
                return "Procedure steps"
            else:
                return "Bullet point list"

        elif element_type == "text":
            if len(content) < 50:
                return "Short text element"
            elif "figure" in content.lower() or "table" in content.lower():
                return "Figure/Table reference"
            elif any(
                word in content.lower()
                for word in ["introduction", "conclusion", "summary"]
            ):
                return "Section text"
            else:
                return "Paragraph text"

        return "Document element"

    def _extract_image_keywords(self, content: str) -> list[str]:
        """Extract keywords that might indicate image context.

        Parameters
        ----------
        content : str
            Image content or filename.

        Returns
        -------
        list[str]
            List of relevant keywords.
        """
        keywords = []
        content_lower = content.lower()

        if any(word in content_lower for word in ["chart", "graph", "diagram"]):
            keywords.append("chart/diagram")
        if any(word in content_lower for word in ["photo", "image", "picture"]):
            keywords.append("photograph")
        if any(word in content_lower for word in ["logo", "brand"]):
            keywords.append("logo/branding")
        if any(word in content_lower for word in ["screenshot", "screen"]):
            keywords.append("screenshot")

        return keywords

    def _extract_table_keywords(self, content: str) -> list[str]:
        """Extract keywords that might indicate table content.

        Parameters
        ----------
        content : str
            Table content.

        Returns
        -------
        list[str]
            List of relevant keywords.
        """
        keywords = []
        content_lower = content.lower()

        # -- common table types
        if any(word in content_lower for word in ["specification", "specs"]):
            keywords.append("specifications")
        if any(word in content_lower for word in ["comparison", "compare"]):
            keywords.append("comparison")
        if any(word in content_lower for word in ["summary", "overview"]):
            keywords.append("summary")
        if any(word in content_lower for word in ["data", "statistics"]):
            keywords.append("data/statistics")
        if any(word in content_lower for word in ["requirements", "req"]):
            keywords.append("requirements")

        return keywords

    def _update_stats(self, page_content: str, page_elements: list) -> None:
        """Update document statistics.

        Parameters
        ----------
        page_content : str
            Processed page content.
        page_elements : list
            Page layout elements.
        """
        words = re.findall(r"\b\w+\b", page_content)
        self.stats["word_count"] += len(words)
        self._update_text_statistics(page_content)
        self._count_page_elements(page_elements)

    def _update_text_statistics(self, text: str) -> None:
        """Update comprehensive text statistics.

        Parameters
        ----------
        text : str
            Text content to analyze.
        """
        if not text.strip():
            return

        chars = len(re.sub(r"\s", "", text))
        self.stats["text_stats"]["total_characters"] += chars
        lines = len([line for line in text.split("\n") if line.strip()])
        self.stats["text_stats"]["total_lines"] += lines
        sentences = len(re.split(r"[.!?]+", text))
        self.stats["text_stats"]["total_sentences"] += sentences
        words = re.findall(r"\b\w+\b", text.lower())
        unique_words = set(words)
        self.stats["text_stats"]["unique_words"] += len(unique_words)

        if self.stats["text_stats"]["total_sentences"] > 0:
            self.stats["text_stats"]["average_sentence_length"] = (
                self.stats["word_count"] / self.stats["text_stats"]["total_sentences"]
            )

        if self.stats["word_count"] > 0:
            self.stats["text_stats"]["average_word_length"] = (
                self.stats["text_stats"]["total_characters"] / self.stats["word_count"]
            )

        if self.stats["word_count"] > 0:
            self.stats["text_stats"]["reading_time_minutes"] = (
                self.stats["word_count"] / 200.0
            )

    def _count_page_elements(self, page_elements: list) -> None:
        """Count various elements found on the page.

        Parameters
        ----------
        page_elements : list
            Page layout elements.
        """
        lines = [
            elem
            for elem in page_elements
            if hasattr(elem, "__class__") and "Line" in elem.__class__.__name__
        ]
        if len(lines) >= 4:
            self.stats["tables"]["total"] += 1

    async def _process_images_with_vlm(self, images_dir: str) -> None:
        """Process extracted images with VLM analysis.

        Parameters
        ----------
        images_dir : str
            Directory containing extracted images.
        """
        if not self.config.enable_vlm or not self.vlm_processor:
            return

        image_files = []
        for ext in [
            "*.png",
            "*.jpg",
            "*.jpeg",
            "*.tiff",
            "*.bmp",
            "*.gif",
            "*.webp",
        ]:
            image_files.extend(Path(images_dir).glob(ext))

        if not image_files:
            return

        image_paths = [str(f) for f in image_files]

        if self.config.compress_for_inference:
            image_config = ImageExtractionConfig(
                compress_for_inference=True,
                inference_quality=self.config.inference_quality,
                inference_max_size=self.config.inference_max_size,
            )
            processed_paths = await prepare_images_for_vlm_inference(
                image_paths, image_config
            )
            vlm_paths = list(processed_paths.values())
        else:
            vlm_paths = image_paths

        results = await self.vlm_processor.analyze_images_batch(vlm_paths)

        for i, image_path in enumerate(image_paths):
            vlm_path = vlm_paths[i] if i < len(vlm_paths) else image_path
            if vlm_path in results:
                image_name = Path(image_path).stem
                self.vlm_results[image_name] = results[vlm_path]

                self.stats["vlm_processed_images"] += 1
                if results[vlm_path].confidence > 0.5:
                    self.stats["vlm_successful_analyses"] += 1
                else:
                    self.stats["vlm_failed_analyses"] += 1

        vlm_stats = self.vlm_processor.stats
        self.stats["vlm_processing_time"] = vlm_stats["total_processing_time"]

    def markdown_with_vlm(self, markdown_content: str) -> str:
        """Enhance markdown content with VLM analysis.

        Parameters
        ----------
        markdown_content : str
            Original markdown content.

        Returns
        -------
        str
            Enhanced markdown content with VLM analysis.
        """
        if not self.config.enable_vlm or not self.vlm_results:
            return markdown_content

        lines = markdown_content.split("\n")
        enhanced_lines = []
        image_count = 0
        enhanced_count = 0

        for line in lines:
            enhanced_lines.append(line)

            if line.strip().startswith("![") and line.strip().endswith(")"):
                image_count += 1
                match = re.search(r"!\[([^\]]+)\]", line)
                if match:
                    image_name = match.group(1)

                    # Try to find VLM result with different name variations
                    vlm_result = None

                    # First try exact match
                    if image_name in self.vlm_results:
                        vlm_result = self.vlm_results[image_name]
                        print(
                            f"Markdown enhancement: Found exact match for {image_name}"
                        )
                    else:
                        # Try without extension
                        image_name_no_ext = Path(image_name).stem
                        if image_name_no_ext in self.vlm_results:
                            vlm_result = self.vlm_results[image_name_no_ext]
                            print(
                                f"Markdown enhancement: Found match without extension for {image_name} -> {image_name_no_ext}"
                            )
                        else:
                            # Try with common extensions
                            for ext in [
                                ".png",
                                ".jpg",
                                ".jpeg",
                                ".tiff",
                                ".bmp",
                            ]:
                                test_name = image_name_no_ext + ext
                                if test_name in self.vlm_results:
                                    vlm_result = self.vlm_results[test_name]
                                    print(
                                        f"Markdown enhancement: Found match with extension for {image_name} -> {test_name}"
                                    )
                                    break

                    if vlm_result and (
                        vlm_result.extracted_text or vlm_result.description
                    ):
                        analysis_text = (
                            self.vlm_processor.format_vlm_result_for_markdown(
                                vlm_result
                            )
                        )
                        enhanced_lines.append(analysis_text)
                        enhanced_lines.append("")
                        enhanced_count += 1
                        print(
                            f"Markdown enhancement: Added VLM analysis for {image_name}"
                        )
                    else:
                        print(
                            f"Markdown enhancement: No VLM result found for {image_name}"
                        )

        return "\n".join(enhanced_lines)

    def _format_document_summary(self) -> str:
        """Format document analysis summary.

        Returns
        -------
        str
            Markdown formatted summary table.
        """
        total_images = len(self.image_positions)
        table = SummaryTable("Document Analysis Summary")
        table.add_row("Total Pages", self.stats["pages"], "Number of pages processed")
        table.add_row("Images Found", total_images, "Total images found in PDF")
        table.add_row(
            "Images Extracted",
            self.stats["images"]["extracted"],
            "Successfully extracted images",
        )
        table.add_row(
            "Images Failed",
            self.stats["images"]["failed"],
            "Failed image extractions",
        )
        table.add_row(
            "Tables Detected",
            self.stats["tables"]["total"],
            "Data tables found",
        )
        table.add_row("Headers", sum(self.stats["headers"].values()), "Section headers")
        table.add_row("Paragraphs", self.stats["paragraphs"], "Text paragraphs")
        table.add_row(
            "Word Count",
            f"{self.stats['word_count']:,}",
            "Approximate word count",
        )
        table.add_section("Text Analysis")
        table.add_row(
            "Total Characters",
            f"{self.stats['text_stats']['total_characters']:,}",
            "Characters (excluding spaces)",
        )
        table.add_row(
            "Total Sentences",
            f"{self.stats['text_stats']['total_sentences']:,}",
            "Number of sentences",
        )
        table.add_row(
            "Total Lines",
            f"{self.stats['text_stats']['total_lines']:,}",
            "Number of text lines",
        )
        table.add_row(
            "Unique Words",
            f"{self.stats['text_stats']['unique_words']:,}",
            "Unique vocabulary",
        )
        table.add_row(
            "Avg Sentence Length",
            f"{self.stats['text_stats']['average_sentence_length']:.1f}",
            "Words per sentence",
        )
        table.add_row(
            "Avg Word Length",
            f"{self.stats['text_stats']['average_word_length']:.1f}",
            "Characters per word",
        )
        table.add_row(
            "Reading Time",
            f"{self.stats['text_stats']['reading_time_minutes']:.1f} min",
            "Estimated reading time",
        )

        if self.config.enable_vlm:
            table.add_section("VLM Analysis")
            table.add_row(
                "Images Analyzed",
                self.stats["vlm_processed_images"],
                "Images processed by VLM",
            )
            table.add_row(
                "Successful Analyses",
                self.stats["vlm_successful_analyses"],
                "Successful VLM analyses",
            )
            table.add_row(
                "Failed Analyses",
                self.stats["vlm_failed_analyses"],
                "Failed VLM analyses",
            )
            table.add_row(
                "VLM Processing Time",
                f"{self.stats['vlm_processing_time']:.1f}s",
                "Time spent on VLM analysis",
            )

        return table.to_markdown()

    def _write_markdown_file(self, markdown_path: str, content: str) -> None:
        """Write markdown content to file.

        Parameters
        ----------
        markdown_path : str
            Path to output markdown file.
        content : str
            Markdown content to write.
        """
        with open(markdown_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _export_structure_to_excel(self, excel_path: str) -> None:
        """Export document structure to Excel file with enhanced organization.

        Parameters
        ----------
        excel_path : str
            Path to output Excel file.
        """
        if not self.document_structure:
            return

        structured_data = []

        # Process each element in the document structure
        for item in self.document_structure:
            page_num = item["page"]
            content = item["content"]
            subtype = item.get("subtype", "unknown")
            hierarchy = item.get("hierarchy", "")
            original_hierarchy = item.get("original_hierarchy", "")
            context = item.get("context", "")
            raw_data = item.get("raw_data", "")

            # Get VLM data for images if available
            vlm_caption = ""
            vlm_description = ""

            if item["type"] == "image" and self.config.enable_vlm and self.vlm_results:
                # Extract base name without extension for VLM lookup
                base_name = (
                    content.replace(".png", "").replace(".jpg", "").replace(".jpeg", "")
                )

                if base_name in self.vlm_results:
                    vlm_result = self.vlm_results[base_name]
                    if vlm_result:
                        if vlm_result.extracted_text:
                            vlm_caption = vlm_result.extracted_text
                        if vlm_result.description:
                            vlm_description = vlm_result.description

            row_data = {
                "Page No": page_num,
                "Text": content,
                "SubType": subtype,
                "Hierarchy": hierarchy,
                "Original Hierarchy": original_hierarchy,
                "Context": context,
                "Raw Data": raw_data,
            }

            # Add VLM columns if enabled
            if self.config.enable_vlm:
                row_data["VLM Caption"] = vlm_caption
                row_data["VLM Description"] = vlm_description

            structured_data.append(row_data)

        df = pd.DataFrame(structured_data)
        with pd.ExcelWriter(excel_path, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="Document_Structure")

            workbook = writer.book
            worksheet = writer.sheets["Document_Structure"]

            header_format = workbook.add_format(
                {
                    "bold": True,
                    "bg_color": "#4CAF50",
                    "font_color": "white",
                    "border": 1,
                    "text_wrap": True,
                    "align": "center",
                    "valign": "top",
                }
            )

            section_format = workbook.add_format(
                {
                    "bold": True,
                    "bg_color": "#E8F5E8",
                    "border": 1,
                    "text_wrap": True,
                    "align": "left",
                    "valign": "top",
                }
            )

            cell_format = workbook.add_format(
                {
                    "text_wrap": True,
                    "align": "left",
                    "valign": "top",
                    "border": 1,
                }
            )

            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)

            for row_num in range(1, len(df) + 1):
                for col_num, col_name in enumerate(df.columns):
                    cell_value = df.iloc[row_num - 1, col_num]

                    if col_name == "SubType" and str(cell_value) == "heading":
                        worksheet.write(row_num, col_num, cell_value, section_format)
                    else:
                        worksheet.write(row_num, col_num, cell_value, cell_format)

            column_widths = {
                "Page No": 8,
                "Text": 50,
                "SubType": 12,
                "Hierarchy": 15,
                "Original Hierarchy": 25,
                "Context": 30,
                "Raw Data": 20,
            }

            if self.config.enable_vlm:
                column_widths["VLM Caption"] = 35
                column_widths["VLM Description"] = 35

            for col_num, (col_name, width) in enumerate(column_widths.items()):
                if col_name in df.columns:
                    worksheet.set_column(col_num, col_num, width)

            worksheet.set_default_row(30)

    def _detect_content_header_level(self, content: str) -> int:
        """Detect if content is a header and return its level.

        Parameters
        ----------
        content : str
            Content to analyze.

        Returns
        -------
        int
            Header level (1-6) or 0 if not a header.
        """
        return self._detect_header_by_pattern(
            content, 12
        )  # use default font size for pattern. should be less than 14

    def _is_bullet_point(self, text: str) -> bool:
        """Check if text is a bullet point.

        Parameters
        ----------
        text : str
            Text to check.

        Returns
        -------
        bool
            True if text is a bullet point.
        """
        text = text.strip()
        bullet_patterns = [
            r"^[•\-\*]\s+",  # • - *
            r"^\d+\.\s+",  # 1. 2. etc.
            r"^[a-z]\)\s+",  # a) b) etc.
            r"^[A-Z]\)\s+",  # A) B) etc.
        ]

        for pattern in bullet_patterns:
            if re.match(pattern, text):
                return True

        return False


async def markdown_converter_async(
    pdf_path: str,
    output_dir: str | None = None,
    enable_vlm: bool = False,
    vlm_model: str = "vllm-smolvlm-256m",
    **kwargs,
) -> dict[str, str]:
    """Convert PDF to Markdown asynchronously.

    Parameters
    ----------
    pdf_path : str
        Path to input PDF file.
    output_dir : str, optional
        Output directory (optional).
    enable_vlm : bool, optional
        Whether to enable VLM analysis, by default False.
    vlm_model : str, optional
        VLM model to use, by default "vllm-smolvlm-256m".
    **kwargs
        Additional configuration options.

    Returns
    -------
    dict[str, str]
        Dictionary with output file paths.
    """
    config = ConverterConfig(enable_vlm=enable_vlm, vlm_model=vlm_model, **kwargs)

    converter = PDFToMarkdownConverter(config)
    return await converter.convert(pdf_path, output_dir)


def markdown_converter(
    pdf_path: str,
    output_dir: str | None = None,
    enable_vlm: bool = False,
    vlm_model: str = "vllm-smolvlm-256m",
    **kwargs,
) -> dict[str, str]:
    """Convert PDF to Markdown synchronously.

    Parameters
    ----------
    pdf_path : str
        Path to input PDF file.
    output_dir : str, optional
        Output directory (optional).
    enable_vlm : bool, optional
        Whether to enable VLM analysis, by default False.
    vlm_model : str, optional
        VLM model to use, by default "vllm-smolvlm-256m".
    **kwargs
        Additional configuration options.

    Returns
    -------
    dict[str, str]
        Dictionary with output file paths.
    """
    return asyncio.run(
        markdown_converter_async(pdf_path, output_dir, enable_vlm, vlm_model, **kwargs)
    )
