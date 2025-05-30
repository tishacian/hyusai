# Metadata Extraction Service

A flexible microservice for extracting metadata from various document types, designed for integration with RAG systems and document management pipelines.

## Features

- Extract common metadata from any file type
- Extract specific metadata from supported file types:
  - PDF files
  - Image files (jpg, png, gif, etc.)
  - Document files (docx, odt, etc.)
- Extract and count tokens for text-based files (for LLM context estimation)
- Extract keywords using TF-IDF for improved document searchability and RAG retrieval
- Performance timing for extraction processes
- Extensible factory architecture for adding support for new file types
- Command-line interface for batch processing and integration
- JSON serialization for easy integration with other systems


## Usage

### Python API

```python
from docmeta.core import extract_metadata

# Basic metadata extraction
metadata = extract_metadata("path/to/file.pdf")

# Extract metadata with token counting for LLMs
metadata = extract_metadata("path/to/file.pdf", count_tokens_flag=True)

# Extract metadata with keywords using TF-IDF (specify language)
metadata = extract_metadata("path/to/file.pdf", extract_keywords_language="french")

# Extract with both token counting and keywords
metadata = extract_metadata("path/to/file.pdf", count_tokens_flag=True, extract_keywords_language="english")
```

### Command-line Interface

```bash
# Extract metadata from all PDFs in a directory
python manually_test_pdf.py --data-dir my_documents --output-dir metadata_output

# Count tokens in PDFs (useful for RAG systems)
python manually_test_pdf.py --count-tokens

# Extract keywords using TF-IDF (specify language, e.g., english, french)
python manually_test_pdf.py --extract-keywords [language]

# Use both token counting and keyword extraction
python manually_test_pdf.py --count-tokens --extract-keywords [language]
```

## Supported File Types
- PDF (`.pdf`)
- Images (`.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.tiff`, `.webp`)
- Microsoft Office (`.docx`, `.xlsx`, `.pptx`)
- OpenDocument (`.odt`, `.ods`, `.odp`)
- Text files (`.txt`, `.md`, `.rst`, `.log`)
- Markup files (`.html`, `.htm`, `.xml`, `.xhtml`)
- Structured Data files (`.csv`, `.json`, `.yaml`, `.yml`, `.toml`, `.ini`)

### Common Metadata (All File Types)

- File path
- File name
- File extension
- MIME type
- File permissions
- File size
- Creation time
- Last modified time
- Last accessed time
- Extracted keywords (when requested)
- Subject
- Title
- Number of pages
- Keywords (embedded in PDF)
- Extracted keywords (TF-IDF, when requested)
- Token count (for LLM context estimation, when requested)
- Encryption status
- Page size (width and height)

### Image Metadata

- Width
- Height
- Color mode
- Bit depth
- DPI (horizontal and vertical)
- EXIF data

### Microsoft Office Document Metadata (.docx, .xlsx, .pptx)

- Author
- Title
- Subject
- Embedded keywords
- Last modified by
- Number of pages (for .docx, .pptx) or Sheets (for .xlsx)
- Number of slides (for .pptx)
- Word count
- Character count
- Paragraph count (primarily for .docx)
- Application (e.g., "Microsoft Word", "Microsoft Excel")
- Application version
- Extracted keywords (TF-IDF, when requested)
- Token count (for LLM context estimation, when requested)

### OpenDocument Metadata (.odt, .ods, .odp)

- Author
- Title
- Subject
- Embedded keywords
- Last modified by
- Number of pages
- Word count
- Character count
- Paragraph count
- Generator (Application that created the document)
- Language
- Extracted keywords (TF-IDF, when requested)
- Token count (for LLM context estimation, when requested)

### Text File Metadata (.txt, .md, .rst, .log)

- Encoding
- Word count
- Character count
- Line count
- Paragraph count
- Language (Detected, if available)
- Has front matter (for .md files with YAML front matter)
- Extracted keywords (TF-IDF, when requested)
- Token count (for LLM context estimation, when requested)

### Markup File Metadata (.html, .htm, .xml, .xhtml)

- Title (e.g., from `<title>` tag or root XML tag)
- Encoding
- Doctype (for HTML)
- Meta description (for HTML)
- Meta keywords (for HTML)
- Language (e.g., from `lang` attribute)
- Element count
- Link count (HTML specific)
- Image count (HTML specific)
- Extracted keywords (TF-IDF, when requested)
- Token count (for LLM context estimation, when requested)

### Structured Data File Metadata (.csv, .json, .yaml, .toml, .ini)

- Encoding
- Schema type (e.g., "CSV", "JSON", "YAML", "TOML", "INI")
- Record count (e.g., rows for CSV, top-level items for JSON list, sections for INI)
- Column count (e.g., CSV specific, or number of keys in top-level JSON object)
- Columns (e.g., CSV column names, or keys in top-level JSON object)
- Data types (Inferred column/field data types)
- Has header (CSV specific)
- Extracted keywords (TF-IDF, when requested, if text content is meaningful for keyword extraction)
- Token count (for LLM context estimation, when requested, if text content is meaningful)

## Architecture

The package uses a factory pattern for extensibility:

- **Core Module**: Defines common types, the factory system, and the API
- **Extractors**: Specialized extractors for different file types
- **Utils**: Serialization, keyword extraction, and other utilities


## Dependencies

- **Core**: `typing-extensions`
- **PDF Processing**: `PyPDF2`, `PyMuPDF` (fitz), `tiktoken`
- **Image Processing**: `Pillow`
- **Microsoft Office Document Processing**: `python-docx`, `openpyxl`, `python-pptx`
- **OpenDocument Processing**: `odfpy`
- **Markup Processing**: `beautifulsoup4`
- **Structured Data Processing**: `PyYAML`, `tomli`
- **Keyword Extraction**: `scikit-learn`, `nltk`
- **Text Processing Utilities**: `chardet`

## Future Enhancements

- Support for more file formats (audio, video, specialized document types)
- Additional metadata extraction methods (NER, language detection)
- Support for OCR in image-based documents
- Asynchronous processing for large batches
- Integration with document chunking strategies for RAG
- Persistent corpus model for more accurate TF-IDF scores
