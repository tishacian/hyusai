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

## Installation

```bash
# Install from the current directory
pip install -r requirments.txt

```

## Usage

### Python API

```python
from docmeta.core import extract_metadata

# Basic metadata extraction
metadata = extract_metadata("path/to/file.pdf")

# Extract metadata with token counting for LLMs
metadata = extract_metadata("path/to/file.pdf", count_tokens=True)

# Extract metadata with keywords using TF-IDF
metadata = extract_metadata("path/to/file.pdf", extract_keywords=True)

# Extract with both token counting and keywords
metadata = extract_metadata("path/to/file.pdf", count_tokens=True, extract_keywords=True)
```

### Command-line Interface

```bash
# Extract metadata from all PDFs in a directory
python run_pdf_extraction.py --data-dir my_documents --output-dir metadata_output

# Count tokens in PDFs (useful for RAG systems)
python run_pdf_extraction.py --count-tokens

# Extract keywords using TF-IDF
python run_pdf_extraction.py --extract-keywords

# Use both token counting and keyword extraction
python run_pdf_extraction.py --count-tokens --extract-keywords
```

## Supported File Types

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

### PDF Metadata

- Author
- Creator
- Producer
- Subject
- Title
- Number of pages
- Keywords (embedded in PDF)
- Extracted keywords (TF-IDF, when requested)
- Token count (for LLM context estimation)
- Encryption status
- Page size
- Processing time (when timing is enabled)

### Image Metadata

- Width
- Height
- Color mode
- Bit depth
- DPI
- EXIF data

### Document Metadata

- Author
- Title
- Subject
- Keywords
- Created date
- Modified date
- Last modified by
- Number of pages
- Word count
- Character count
- Paragraph count
- Line count
- Extracted keywords (TF-IDF, when requested)

## Architecture

The package uses a factory pattern for extensibility:

- **Core Module**: Defines common types, the factory system, and the API
- **Extractors**: Specialized extractors for different file types
- **Utils**: Serialization, keyword extraction, and other utilities


## Dependencies

- **Core**: typing-extensions
- **PDF Processing**: PyPDF2, PyMuPDF, tiktoken (for token counting)
- **Image Processing**: Pillow
- **Document Processing**: python-docx, odfpy
- **Keyword Extraction**: scikit-learn (for TF-IDF)

## Future Enhancements

- Support for more file formats (audio, video, specialized document types)
- Additional metadata extraction methods (NER, language detection)
- Support for OCR in image-based documents
- Asynchronous processing for large batches
- Integration with document chunking strategies for RAG
- Persistent corpus model for more accurate TF-IDF scores
