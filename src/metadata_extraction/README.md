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

### PDF Metadata

- Number of pages
- Encryption status
- Author (optional)
- Creator (optional)
- Producer (optional)
- Subject (optional)
- Title (optional)
- Keywords (embedded in PDF, optional)
- Page size - width and height (optional)
- Extracted keywords (TF-IDF, when requested, optional)
- Token count (for LLM context estimation, when requested, optional)

### Image Metadata

- Width
- Height
- Color mode (optional)
- Bit depth (optional)
- DPI - horizontal and vertical (optional)
- EXIF data (optional)

### Microsoft Office Document Metadata (.docx, .xlsx, .pptx)

- Word count
- Character count
- Paragraph count
- Author (optional)
- Title (optional)
- Subject (optional)
- Embedded keywords (optional)
- Last modified by (optional)
- Number of pages (for .docx, .pptx) or sheets (for .xlsx) (optional)
- Number of slides (for .pptx) (optional)
- Application (e.g., "Microsoft Word", "Microsoft Excel") (optional)
- Application version (optional)
- Extracted keywords (TF-IDF, when requested, optional)
- Token count (for LLM context estimation, when requested, optional)

### OpenDocument Metadata (.odt, .ods, .odp)

- Word count
- Character count
- Paragraph count
- Author (optional)
- Title (optional)
- Subject (optional)
- Embedded keywords (optional)
- Last modified by (optional)
- Number of pages (optional)
- Generator - application that created the document (optional)
- Language (optional)
- Extracted keywords (TF-IDF, when requested, optional)
- Token count (for LLM context estimation, when requested, optional)

### Text File Metadata (.txt, .md, .rst, .log)

- Word count
- Character count
- Line count
- Paragraph count
- Has front matter (for .md files with YAML front matter)
- Encoding (optional)
- Language (detected, optional)
- Extracted keywords (TF-IDF, when requested, optional)
- Token count (for LLM context estimation, when requested, optional)

### Markup File Metadata (.html, .htm, .xml, .xhtml)

- Element count
- Title (e.g., from `<title>` tag or root XML tag) (optional)
- Encoding (optional)
- Doctype (for HTML) (optional)
- Meta description (for HTML) (optional)
- Meta keywords (for HTML) (optional)
- Language (e.g., from `lang` attribute) (optional)
- Link count (HTML specific) (optional)
- Image count (HTML specific) (optional)
- Extracted keywords (TF-IDF, when requested, optional)
- Token count (for LLM context estimation, when requested, optional)

### Structured Data File Metadata (.csv, .json, .yaml, .toml, .ini)

- Encoding (optional)
- Schema type (e.g., "CSV", "JSON", "YAML", "TOML", "INI") (optional)
- Record count (e.g., rows for CSV, top-level items for JSON list, sections for INI) (optional)
- Column count (e.g., CSV specific, or number of keys in top-level JSON object) (optional)
- Columns (e.g., CSV column names, or keys in top-level JSON object) (optional)
- Data types (inferred column/field data types) (optional)
- Has header (CSV specific) (optional)
- Extracted keywords (TF-IDF, when requested, if text content is meaningful) (optional)
- Token count (for LLM context estimation, when requested, if text content is meaningful) (optional)

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
