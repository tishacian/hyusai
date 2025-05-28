import os

import chardet


def validate_file_exists(path: str) -> None:
    """
    Validate that a file exists.

    Args:
        path: Path to the file

    Raises:
        FileNotFoundError: If the file does not exist
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")


def detect_encoding(path: str) -> str:
    """
    Detect file encoding.

    Args:
        path: Path to the file

    Returns:
        str: Detected encoding
    """
    with open(path, "rb") as f:
        raw_data = f.read(10000)  # Read first 10KB for detection
        result = chardet.detect(raw_data)
        return result["encoding"] or "utf-8"


def analyze_list_structure(data: list) -> dict:
    """
    Analyze structure of a list data structure.

    Args:
        data: List to analyze

    Returns:
        Dictionary with structure information
    """
    result = {"record_count": len(data), "columns": None, "column_count": 0}

    # If list of objects, analyze first object for schema
    if data and isinstance(data[0], dict):
        obj = data[0]
        result["columns"] = list(obj.keys())
        result["column_count"] = len(obj.keys())

    return result


def analyze_dict_structure(data: dict) -> dict:
    """
    Analyze structure of a dictionary data structure.

    Args:
        data: Dictionary to analyze

    Returns:
        Dictionary with structure information
    """
    return {
        "record_count": 1,
        "columns": list(data.keys()),
        "column_count": len(data.keys()),
    }


def get_file_extension(path: str) -> str:
    """
    Get normalized file extension.

    Args:
        path: Path to the file

    Returns:
        Lowercase file extension (e.g., '.pdf', '.docx')
    """
    _, extension = os.path.splitext(path)
    return extension.lower()


def extract_common_metadata_fields(
    properties_obj, metadata_dict: dict, field_mapping: dict
) -> None:
    """
    Extract common metadata fields.

    This function handles the common pattern of extracting metadata fields
    like author, title, subject, etc. from document properties objects.

    Args:
        properties_obj: Object containing document properties
        metadata_dict: Dictionary to update with extracted metadata
        field_mapping: Mapping of metadata field names to property names
                      e.g., {'author': 'author', 'title': 'title'}
    """
    for metadata_field, property_name in field_mapping.items():
        if hasattr(properties_obj, property_name):
            metadata_dict[metadata_field] = getattr(properties_obj, property_name, None)
        elif hasattr(properties_obj, "get"):
            # For dict-like objects
            metadata_dict[metadata_field] = properties_obj.get(property_name)
        elif hasattr(properties_obj, "getAttribute"):
            # For OpenDocument meta objects
            metadata_dict[metadata_field] = properties_obj.getAttribute(property_name)


def extract_keywords(properties_obj, metadata_dict: dict, keyword_field: str) -> None:
    """
    Extract and parse keywords.

    Args:
        properties_obj: Object containing document properties
        metadata_dict: Dictionary to update with parsed keywords
        keyword_field: Name of the keyword field in the properties object
    """
    keywords = None

    if hasattr(properties_obj, keyword_field):
        keywords = getattr(properties_obj, keyword_field, None)
    elif hasattr(properties_obj, "get"):
        # For dict-like objects
        keywords = properties_obj.get(keyword_field)
    elif hasattr(properties_obj, "getAttribute"):
        # For OpenDocument meta objects
        keywords = properties_obj.getAttribute(keyword_field)

    if keywords and isinstance(keywords, str):
        metadata_dict["embedded_keywords"] = parse_keywords(keywords)


def initialize_metadata(path: str, create_metadata_func, schema_type: str = None):
    """
    Initialize metadata with common file properties and encoding.

    This function handles the common pattern of:
    1. Initialize metadata with file properties
    2. Detect encoding
    3. Set encoding in metadata
    4. Optionally set schema_type

    Args:
        path: Path to the file
        create_metadata_func: Function to create initial metadata
        schema_type: Optional schema type to set (e.g., "CSV", "JSON")

    Returns:
        tuple: (metadata_dict, encoding)
    """
    # Initialize metadata with common file properties and defaults
    metadata = create_metadata_func()

    # Detect encoding
    encoding = detect_encoding(path)
    metadata["encoding"] = encoding

    # Set schema type if provided
    if schema_type:
        metadata["schema_type"] = schema_type

    return metadata, encoding


def infer_json_data_types(data_obj: dict) -> dict:
    """
    Infer data types for JSON object fields.

    Args:
        data_obj: Dictionary object to analyze

    Returns:
        Dictionary mapping field names to inferred types
    """
    data_types = {}
    for key in data_obj.keys():
        value = data_obj[key]
        if isinstance(value, bool):
            data_types[key] = "bool"
        elif isinstance(value, int):
            data_types[key] = "int"
        elif isinstance(value, float):
            data_types[key] = "float"
        elif isinstance(value, str):
            data_types[key] = "str"
        elif isinstance(value, (list, dict)):
            data_types[key] = "object"
        else:
            data_types[key] = "unknown"
    return data_types


def detect_csv_header(first_row: list[str]) -> bool:
    """
    Detect if the first row of a CSV is a header.

    Uses a simple heuristic: if any cell is not numeric, assume it's a header.

    Args:
        first_row: List of values from the first row

    Returns:
        True if first row appears to be a header, False otherwise
    """
    for cell in first_row:
        # If any cell is not numeric, assume it's a header
        if not (cell.strip().replace(".", "").replace("-", "").isdigit()):
            return True
    return False


def count_text_statistics(text_elements: list[str]) -> dict:
    """
    Count text statistics.

    Args:
        text_elements: List of text strings

    Returns:
        Dictionary with word_count, char_count, and all_text
    """
    word_count = 0
    char_count = 0
    all_text = []

    for text in text_elements:
        if text and text.strip():
            words = text.split()
            word_count += len(words)
            char_count += len(text)
            all_text.append(text)

    return {"word_count": word_count, "char_count": char_count, "all_text": all_text}


def extract_statistics(stats_obj, field_mapping: dict) -> dict:
    """
    Extract statistics from a metadata statistics object.

    Args:
        stats_obj: Statistics object with getAttribute method
        field_mapping: Mapping of output field names to attribute names
                      e.g., {'num_pages': 'page-count', 'word_count': 'word-count'}

    Returns:
        Dictionary with extracted statistics
    """
    result = {}

    if hasattr(stats_obj, "getAttribute"):
        for output_field, attr_name in field_mapping.items():
            value = stats_obj.getAttribute(attr_name)
            if value:
                result[output_field] = int(value)

    return result


def parse_keywords(keywords_str: str) -> list[str]:
    """
    Parse keywords string into a list.

    This function handles different keyword separators commonly found in document metadata:
    - Comma-separated: "keyword1, keyword2, keyword3"
    - Semicolon-separated: "keyword1; keyword2; keyword3"
    - Single keyword: "keyword1"

    Args:
        keywords_str: String containing keywords

    Returns:
        list[str]: List of keywords with whitespace stripped
    """
    if not keywords_str:
        return []

    if "," in keywords_str:
        return [k.strip() for k in keywords_str.split(",")]
    elif ";" in keywords_str:
        return [k.strip() for k in keywords_str.split(";")]
    else:
        return [keywords_str.strip()]
