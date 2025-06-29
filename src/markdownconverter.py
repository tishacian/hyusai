import asyncio
import multiprocessing as mp
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from langchain_community.document_loaders import UnstructuredEmailLoader
from langchain_core.documents import Document
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTChar, LTTextBox, LTFigure, LTCurve, LTLine
from src.vlmprocessor import VLMProcessor, VLMResult, get_supported_models


class MyEmlLoader(UnstructuredEmailLoader):
    def load(self) -> list[Document]:
        """
        Load email content with fallback to text/plain.

        Returns
        -------
        list[Document]
            List of documents extracted from the email.

        Raises
        ------
        Exception
            If email loading fails completely.
        """
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


@dataclass
class ConverterConfig:
    max_workers: int = field(
        default_factory=lambda: min(32, (mp.cpu_count() or 1) + 4)
    )
    extract_images: bool = True
    extract_tables: bool = True

    # VLM settings
    enable_vlm: bool = False
    vlm_model: str = "vllm-smolvlm-256m"
    vlm_workers: int = 2
    vlm_kwargs: dict[str, any] = field(default_factory=dict)

    # Output settings
    include_summary: bool = True
    export_excel: bool = True
    filter_nonexistent_images: bool = True

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


class PDFToMarkdownConverter:
    """PDF-to-Markdown converter with opt/ VLM image analysis.

    Provides a clean interface for converting PDF documents to
    Markdown format while preserving document structure and optionally
    analyzing images using Vision Language Models.

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
        self.document_structure: list[dict[str, any]] = []
        self.vlm_processor: VLMProcessor | None = None
        self.vlm_results: dict[str, VLMResult] = {}
        self.images_dir: str | None = None

        if self.config.enable_vlm:
            self._initialize_vlm()

    def _initialize_stats(self) -> dict[str, int | float | dict[str, int]]:
        """Initialize statistics dictionary.

        Returns
        -------
        dict[str, int | float | dict[str, int]]
            Statistics dictionary with default values.
        """
        return {
            "pages": 0,
            "images": {"total": 0, "named": 0, "generic": 0},
            "tables": {"total": 0, "named": 0, "generic": 0},
            "headers": {"h1": 0, "h2": 0, "h3_h4": 0},
            "paragraphs": 0,
            "word_count": 0,
            "file_size": 0,
            "processing_time": 0,
            "vlm_processed_images": 0,
            "vlm_successful_analyses": 0,
            "vlm_failed_analyses": 0,
            "vlm_processing_time": 0.0,
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
        """Convert PDF to Markdown with optional VLM analysis.

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
            markdown_content = await self._extract_pdf_content(pdf_path)

            if self.config.enable_vlm:
                await self._process_images_with_vlm(output_paths["images_dir"])
                markdown_content = self._enhance_markdown_with_vlm(
                    markdown_content
                )

            self._write_markdown_file(
                output_paths["markdown"], markdown_content
            )

            if self.config.export_excel:
                self._export_structure_to_excel(output_paths["excel"])

            self.stats["processing_time"] = time.time() - start_time
            self.stats["file_size"] = os.path.getsize(pdf_path)

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
        self.stats = self._initialize_stats()

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

            if self.config.extract_tables:
                table_box = self._detect_table(page_elements)
                if table_box:
                    table_markdown = self._format_table(
                        table_box, page_elements, page_elements, page_num
                    )
                    if table_markdown:
                        page_content.append(table_markdown)
                        self._add_to_structure(
                            page_num, "table", table_markdown.strip()
                        )

            if self.config.extract_images:
                self._process_images_on_page(
                    page_elements, page_content, page_num, self.images_dir
                )

            self._process_text_content(page_elements, page_content, page_num)

            return "".join(page_content)

        except Exception as e:
            return (
                f"{'─' * 35} page {page_num} {'─' * 35}\n\n"
                f"Error: {str(e)}\n\n"
            )

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

        horizontal_lines = [
            line for line in lines if abs(line.y0 - line.y1) < 2
        ]
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

        self.stats["tables"]["total"] += 1
        self.stats["tables"]["generic"] += 1

        return (
            f"\n**Table: {table_name}**\n\n"
            f"[Table content would be extracted here]\n\n"
        )

    def _process_images_on_page(
        self,
        page_elements: list,
        page_content: list[str],
        page_num: int,
        images_dir: str | None = None,
    ) -> None:
        """Process images on a page.

        Parameters
        ----------
        page_elements : list
            Page layout elements.
        page_content : list[str]
            List to append markdown content.
        page_num : int
            Page number.
        images_dir : str, optional
            Directory to save extracted images.
        """
        valid_images = [
            elem
            for elem in page_elements
            if isinstance(elem, LTFigure) and self._is_valid_image(elem)
        ]

        for i, image in enumerate(valid_images):
            image_name = f"image_{page_num}_{i + 1}"
            image_path = self._extract_image_from_figure(
                image, image_name, images_dir
            )

            if image_path:
                page_content.append(f"\n![{image_name}]({image_path})\n\n")
                self._add_to_structure(page_num, "image", image_name)
                self.stats["images"]["total"] += 1
                self.stats["images"]["generic"] += 1

    def _is_valid_image(self, element: LTFigure) -> bool:
        """Check if figure element represents a valid image.

        Parameters
        ----------
        element : LTFigure
            Figure element to validate.

        Returns
        -------
        bool
            True if element is a valid image.
        """
        width = element.x1 - element.x0
        height = element.y1 - element.y0
        return width >= 20 and height >= 20

    def _extract_image_from_figure(
        self,
        figure_element: LTFigure,
        image_name: str,
        images_dir: str | None = None,
    ) -> str:
        """Extract image from figure element and save to file.

        Parameters
        ----------
        figure_element : LTFigure
            Figure element containing image.
        image_name : str
            Name for the extracted image.
        images_dir : str, optional
            Directory to save the image file.

        Returns
        -------
        str
            Relative path to extracted image or empty string.
        """
        try:
            if hasattr(figure_element, "_objs"):
                for obj in figure_element._objs:
                    if hasattr(obj, "stream"):
                        image_data = obj.stream.get_data()

                        if image_data.startswith(b"\xff\xd8\xff"):
                            extension = ".jpg"
                        elif image_data.startswith(b"\x89PNG"):
                            extension = ".png"
                        else:
                            extension = ".png"

                        safe_name = re.sub(r"[^\w\-_.]", "_", image_name)
                        filename = f"{safe_name}{extension}"

                        if images_dir:
                            os.makedirs(images_dir, exist_ok=True)
                            full_image_path = os.path.join(
                                images_dir, filename
                            )

                            with open(full_image_path, "wb") as f:
                                f.write(image_data)

                            return f"images/{filename}"
                        else:
                            return f"images/{filename}"

            return ""

        except Exception:
            return ""

    def _process_text_content(
        self, page_elements: list, page_content: list[str], page_num: int
    ) -> None:
        """Process text content on a page.

        Parameters
        ----------
        page_elements : list
            Page layout elements.
        page_content : list[str]
            List to append markdown content.
        page_num : int
            Page number.
        """
        text_boxes = [
            elem for elem in page_elements if isinstance(elem, LTTextBox)
        ]

        for text_box in text_boxes:
            text = text_box.get_text().strip()
            if text:
                header_level = self._get_header_level(text_box)

                if header_level > 0:
                    hashes = "#" * header_level
                    formatted_text = f"{hashes} {text}\n\n"
                    self.stats["headers"][f"h{header_level}"] += 1
                else:
                    formatted_text = f"{text}\n\n"
                    self.stats["paragraphs"] += 1

                page_content.append(formatted_text)
                self._add_to_structure(page_num, "text", text)

    def _get_header_level(self, text_box: LTTextBox) -> int:
        """Determine header level based on font size.

        Parameters
        ----------
        text_box : LTTextBox
            Text box element.

        Returns
        -------
        int
            Header level (1-4) or 0 if not a header.
        """
        try:
            first_char = next(
                (char for char in text_box if isinstance(char, LTChar)), None
            )
            if not first_char:
                return 0

            size = first_char.size
            if size > 20:
                return 1
            elif size > 16:
                return 2
            elif size > 14:
                return 3
            elif size > 12:
                return 4
            return 0
        except Exception:
            return 0

    def _add_to_structure(
        self, page_num: int, element_type: str, content: str
    ) -> None:
        """Add element to document structure.

        Parameters
        ----------
        page_num : int
            Page number.
        element_type : str
            Type of element.
        content : str
            Element content.
        """
        self.document_structure.append(
            {
                "page": page_num,
                "type": element_type,
                "content": content,
                "position": len(self.document_structure),
            }
        )

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
        for ext in ["*.png", "*.jpg", "*.jpeg"]:
            image_files.extend(Path(images_dir).glob(ext))

        if not image_files:
            return

        image_paths = [str(f) for f in image_files]
        results = await self.vlm_processor.analyze_images_batch(image_paths)

        for image_path, result in results.items():
            image_name = Path(image_path).stem
            self.vlm_results[image_name] = result

            self.stats["vlm_processed_images"] += 1
            if result.confidence > 0.5:
                self.stats["vlm_successful_analyses"] += 1
            else:
                self.stats["vlm_failed_analyses"] += 1

        vlm_stats = self.vlm_processor.stats
        self.stats["vlm_processing_time"] = vlm_stats["total_processing_time"]

    def _enhance_markdown_with_vlm(self, markdown_content: str) -> str:
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

        for line in lines:
            enhanced_lines.append(line)

            if line.strip().startswith("![") and line.strip().endswith(")"):
                match = re.search(r"!\[([^\]]+)\]", line)
                if match:
                    image_name = match.group(1)

                    if image_name in self.vlm_results:
                        vlm_result = self.vlm_results[image_name]
                        if vlm_result and (
                            vlm_result.extracted_text or vlm_result.description
                        ):
                            analysis_text = self.vlm_processor.format_vlm_result_for_markdown(
                                vlm_result
                            )
                            enhanced_lines.append(analysis_text)
                            enhanced_lines.append("")

        return "\n".join(enhanced_lines)

    def _format_document_summary(self) -> str:
        """Format document analysis summary.

        Returns
        -------
        str
            Markdown formatted summary table.
        """
        summary_lines = [
            "# Document Analysis Summary\n",
            "| Metric | Value | Description |",
            "|--------|-------|-------------|",
            (
                f"| Total Pages | {self.stats['pages']} | "
                f"Number of pages processed |"
            ),
            (
                f"| Images | {self.stats['images']['total']} | "
                f"Figures and diagrams |"
            ),
            (
                f"| Tables | {self.stats['tables']['total']} | "
                f"Data tables |"
            ),
            (
                f"| Headers | {sum(self.stats['headers'].values())} | "
                f"Section headers |"
            ),
            (
                f"| Paragraphs | {self.stats['paragraphs']} | "
                f"Text paragraphs |"
            ),
            (
                f"| Word Count | {self.stats['word_count']} | "
                f"Approximate word count |"
            ),
        ]

        if self.config.enable_vlm:
            summary_lines.extend(
                [
                    "| | | |",
                    "| **VLM Analysis** | | |",
                    (
                        f"| Images Analyzed | {self.stats['vlm_processed_images']} | "
                        f"Images processed by VLM |"
                    ),
                    (
                        f"| Successful Analyses | {self.stats['vlm_successful_analyses']} | "
                        f"Successful VLM analyses |"
                    ),
                    (
                        f"| Failed Analyses | {self.stats['vlm_failed_analyses']} | "
                        f"Failed VLM analyses |"
                    ),
                    (
                        f"| VLM Processing Time | {self.stats['vlm_processing_time']:.1f}s | "
                        f"Time spent on VLM analysis |"
                    ),
                ]
            )

        return "\n".join(summary_lines) + "\n\n"

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
        """Export document structure to Excel file.

        Parameters
        ----------
        excel_path : str
            Path to output Excel file.
        """
        if not self.document_structure:
            return

        df_data = []
        for item in self.document_structure:
            row = {
                "Page": item["page"],
                "Type": item["type"],
                "Content": item["content"],
                "Position": item["position"],
            }

            if item["type"] == "image" and item["content"] in self.vlm_results:
                vlm_result = self.vlm_results[item["content"]]
                row["VLM_Description"] = (
                    vlm_result.description if vlm_result else ""
                )
                row["VLM_Extracted_Text"] = (
                    vlm_result.extracted_text if vlm_result else ""
                )
            else:
                row["VLM_Description"] = ""
                row["VLM_Extracted_Text"] = ""

            df_data.append(row)

        df = pd.DataFrame(df_data)

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
                }
            )

            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)

            for i, col in enumerate(df.columns):
                max_len = max(df[col].astype(str).apply(len).max(), len(col))
                worksheet.set_column(i, i, min(max_len + 2, 50))


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
    config = ConverterConfig(
        enable_vlm=enable_vlm, vlm_model=vlm_model, **kwargs
    )

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
        markdown_converter_async(
            pdf_path, output_dir, enable_vlm, vlm_model, **kwargs
        )
    )
