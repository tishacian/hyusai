"""
Structured Data Metadata Extractor

This module provides functionality to extract metadata from structured data files.
Supports CSV, JSON, YAML, and other structured data formats with comprehensive analysis.
"""

import csv
import json
import logging
import os


from docmeta.core.types import StructuredDataMetaData, create_structured_data_metadata
from docmeta.utils.token_counter import count_tokens

# Configure logger
logger = logging.getLogger(__name__)


def _detect_encoding(path: str) -> str:
    """
    Detect file encoding using common encodings.

    Args:
        path: Path to the data file

    Returns:
        str: Detected encoding
    """
    # Try common encodings
    encodings = ['utf-8', 'utf-16', 'latin-1', 'cp1252']

    for encoding in encodings:
        try:
            with open(path, 'r', encoding=encoding) as f:
                f.read(1024)  # Read a small chunk to test
                return encoding
        except UnicodeDecodeError:
            continue

    return 'utf-8'  # Default fallback


def _detect_csv_delimiter(sample_line: str) -> str:
    """
    Detect CSV delimiter from sample line.

    Args:
        sample_line: First line of CSV file

    Returns:
        str: Detected delimiter
    """
    # Common delimiters to test
    delimiters = [',', ';', '\t', '|']

    # Count occurrences of each delimiter
    delimiter_counts = {}
    for delimiter in delimiters:
        delimiter_counts[delimiter] = sample_line.count(delimiter)

    # Return delimiter with highest count
    if delimiter_counts:
        return max(delimiter_counts, key=delimiter_counts.get)

    return ','  # Default to comma


def _infer_data_types(values: list[str]) -> dict[str, str]:
    """
    Infer data types from sample values.

    Args:
        values: List of string values

    Returns:
        dict[str, str]: Data type inference results
    """
    type_counts = {'int': 0, 'float': 0, 'bool': 0, 'str': 0}

    for value in values[:100]:  # Sample first 100 values
        value = value.strip()
        if not value:
            continue

        # Try to infer type
        if value.lower() in ['true', 'false', 'yes', 'no', '1', '0']:
            type_counts['bool'] += 1
        else:
            try:
                int(value)
                type_counts['int'] += 1
                continue
            except ValueError:
                pass

            try:
                float(value)
                type_counts['float'] += 1
                continue
            except ValueError:
                pass

            type_counts['str'] += 1

    # Return most common type
    if type_counts:
        return max(type_counts, key=type_counts.get)
    return 'str'


def _extract_with_csv(path: str) -> StructuredDataMetaData:
    """
    Extract metadata from a CSV file.

    Args:
        path: Path to the CSV file

    Returns:
        StructuredDataMetaData: Metadata for the CSV file
    """
    # Initialize metadata with common file properties and defaults
    csv_metadata = create_structured_data_metadata(path)

    # Detect encoding
    encoding = _detect_encoding(path)
    csv_metadata["encoding"] = encoding
    csv_metadata["schema_type"] = "CSV"

    with open(path, 'r', encoding=encoding, errors='replace') as f:
        # Read first line to detect delimiter
        first_line = f.readline()
        delimiter = _detect_csv_delimiter(first_line)

        # Reset file pointer
        f.seek(0)

        # Create CSV reader
        reader = csv.reader(f, delimiter=delimiter)

        rows = list(reader)
        if not rows:
            return csv_metadata

        # Determine if first row is header
        first_row = rows[0]
        has_header = True  # Assume header by default

        # Simple heuristic: if first row contains non-numeric values, likely header
        try:
            for cell in first_row:
                float(cell)
            has_header = False  # All numeric, probably not header
        except ValueError:
            has_header = True  # Contains non-numeric, likely header

        csv_metadata["has_header"] = has_header

        # Set column information
        if has_header:
            csv_metadata["columns"] = first_row
            data_rows = rows[1:]
        else:
            csv_metadata["columns"] = [f"Column_{i+1}" for i in range(len(first_row))]
            data_rows = rows

        csv_metadata["column_count"] = len(first_row)
        csv_metadata["record_count"] = len(data_rows)

        # Infer data types for each column
        if data_rows and csv_metadata["columns"]:
            data_types = {}
            for i, column_name in enumerate(csv_metadata["columns"]):
                if i < len(first_row):
                    column_values = [row[i] if i < len(row) else '' for row in data_rows]
                    data_types[column_name] = _infer_data_types(column_values)
            csv_metadata["data_types"] = data_types

    # Count tokens from raw file content
    with open(path, 'r', encoding=encoding, errors='replace') as f:
        content = f.read()
        if content.strip():
            csv_metadata["token_count"] = count_tokens(content)

    return csv_metadata


def _extract_with_json(path: str) -> StructuredDataMetaData:
    """
    Extract metadata from a JSON file.

    Args:
        path: Path to the JSON file

    Returns:
        StructuredDataMetaData: Metadata for the JSON file
    """
    # Initialize metadata with common file properties and defaults
    json_metadata = create_structured_data_metadata(path)

    # Detect encoding
    encoding = _detect_encoding(path)
    json_metadata["encoding"] = encoding
    json_metadata["schema_type"] = "JSON"

    with open(path, 'r', encoding=encoding, errors='replace') as f:
        content = f.read()

        # Parse JSON
        data = json.loads(content)

        # Analyze structure
        if isinstance(data, list):
            json_metadata["record_count"] = len(data)

            # If list of objects, analyze first object for schema
            if data and isinstance(data[0], dict):
                first_object = data[0]
                json_metadata["columns"] = list(first_object.keys())
                json_metadata["column_count"] = len(first_object.keys())

                # Infer data types
                data_types = {}
                for key in first_object.keys():
                    value = first_object[key]
                    if isinstance(value, bool):
                        data_types[key] = 'bool'
                    elif isinstance(value, int):
                        data_types[key] = 'int'
                    elif isinstance(value, float):
                        data_types[key] = 'float'
                    elif isinstance(value, str):
                        data_types[key] = 'str'
                    elif isinstance(value, (list, dict)):
                        data_types[key] = 'object'
                    else:
                        data_types[key] = 'unknown'

                json_metadata["data_types"] = data_types

        elif isinstance(data, dict):
            json_metadata["record_count"] = 1
            json_metadata["columns"] = list(data.keys())
            json_metadata["column_count"] = len(data.keys())

        # Count tokens from raw content
        if content.strip():
            json_metadata["token_count"] = count_tokens(content)

    return json_metadata


def _extract_with_yaml(path: str) -> StructuredDataMetaData:
    """
    Extract metadata from a YAML file.

    Args:
        path: Path to the YAML file

    Returns:
        StructuredDataMetaData: Metadata for the YAML file
    """
    # Initialize metadata with common file properties and defaults
    yaml_metadata = create_structured_data_metadata(path)

    # Detect encoding
    encoding = _detect_encoding(path)
    yaml_metadata["encoding"] = encoding
    yaml_metadata["schema_type"] = "YAML"

    import yaml

    with open(path, 'r', encoding=encoding, errors='replace') as f:
        content = f.read()
        data = yaml.safe_load(content)

        # Analyze structure similar to JSON
        if isinstance(data, list):
            yaml_metadata["record_count"] = len(data)

            if data and isinstance(data[0], dict):
                first_object = data[0]
                yaml_metadata["columns"] = list(first_object.keys())
                yaml_metadata["column_count"] = len(first_object.keys())

        elif isinstance(data, dict):
            yaml_metadata["record_count"] = 1
            yaml_metadata["columns"] = list(data.keys())
            yaml_metadata["column_count"] = len(data.keys())

        # Count tokens from raw content
        if content.strip():
            yaml_metadata["token_count"] = count_tokens(content)

    return yaml_metadata


def _extract_with_toml(path: str) -> StructuredDataMetaData:
    """
    Extract metadata from a TOML file.

    Args:
        path: Path to the TOML file

    Returns:
        StructuredDataMetaData: Metadata for the TOML file
    """
    # Initialize metadata with common file properties and defaults
    toml_metadata = create_structured_data_metadata(path)

    # Detect encoding
    encoding = _detect_encoding(path)
    toml_metadata["encoding"] = encoding
    toml_metadata["schema_type"] = "TOML"

    import tomli

    with open(path, 'rb') as f:
        data = tomli.load(f)

        # Analyze structure
        if isinstance(data, dict):
            toml_metadata["record_count"] = 1
            toml_metadata["columns"] = list(data.keys())
            toml_metadata["column_count"] = len(data.keys())

    # Count tokens from raw content
    with open(path, 'r', encoding=encoding, errors='replace') as f:
        content = f.read()
        if content.strip():
            toml_metadata["token_count"] = count_tokens(content)

    return toml_metadata


def _extract_with_ini(path: str) -> StructuredDataMetaData:
    """
    Extract metadata from an INI file.

    Args:
        path: Path to the INI file

    Returns:
        StructuredDataMetaData: Metadata for the INI file
    """
    # Initialize metadata with common file properties and defaults
    ini_metadata = create_structured_data_metadata(path)

    # Detect encoding
    encoding = _detect_encoding(path)
    ini_metadata["encoding"] = encoding
    ini_metadata["schema_type"] = "INI"

    import configparser

    config = configparser.ConfigParser()
    config.read(path, encoding=encoding)

    # Count sections and keys
    sections = config.sections()
    ini_metadata["record_count"] = len(sections)

    # Collect all unique keys across sections
    all_keys = set()
    for section in sections:
        all_keys.update(config[section].keys())

    ini_metadata["columns"] = list(all_keys)
    ini_metadata["column_count"] = len(all_keys)

    # Count tokens from raw content
    with open(path, 'r', encoding=encoding, errors='replace') as f:
        content = f.read()
        if content.strip():
            ini_metadata["token_count"] = count_tokens(content)

    return ini_metadata


def extract_structured_data_metadata(path: str) -> StructuredDataMetaData:
    """
    Extract metadata from a structured data file.

    Args:
        path: Path to the structured data file

    Returns:
        StructuredDataMetaData: Metadata for the structured data file
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    # Get file extension to determine extraction method
    _, extension = os.path.splitext(path)
    extension = extension.lower()

    # Extract metadata based on file type
    if extension == '.csv':
        return _extract_with_csv(path)
    elif extension == '.json':
        return _extract_with_json(path)
    elif extension in ['.yaml', '.yml']:
        return _extract_with_yaml(path)
    elif extension == '.toml':
        return _extract_with_toml(path)
    elif extension == '.ini':
        return _extract_with_ini(path)
    else:
        # For unsupported data types, return basic metadata
        return create_structured_data_metadata(path)
