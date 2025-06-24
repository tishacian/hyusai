"""
Structured Data Metadata Extractor

This module provides functionality to extract metadata from structured data files.
Supports CSV, JSON, YAML, and other structured data formats with comprehensive analysis.
"""

import configparser
import csv
import json
import logging
from typing import Any

import tomli
import yaml

from ..core.defaults import \
    create_structured_data_metadata  # returns dict[str, Any]
from ..utils.text_processing import \
    initialize_metadata  # Returns (metadata_dict, encoding)
from ..utils.text_processing import (analyze_dict_structure,
                                           analyze_list_structure,
                                           detect_csv_header,
                                           get_file_extension,
                                           infer_json_data_types)

# Configure logger
logger = logging.getLogger(__name__)


def _detect_csv_delimiter(sample_line: str) -> str:
    """
    Detect CSV delimiter.
    """
    delimiters = [",", ";", "\t", "|"]
    counts = {d: sample_line.count(d) for d in delimiters}
    return max(counts, key=counts.get) if counts else ","


def _infer_csv_column_data_types(values: list[str]) -> str:
    """
    Infer data types from CSV column values.
    """
    counts = {"int": 0, "float": 0, "bool": 0, "str": 0}
    for value in values[:100]:  # Sample first 100 values
        value = value.strip()
        if not value:
            continue
        if value.lower() in ["true", "false", "yes", "no", "1", "0"]:
            counts["bool"] += 1
        elif value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
            counts["int"] += 1
        elif "." in value and value.replace(".", "", 1).replace("-", "", 1).isdigit():
            counts["float"] += 1
        else:
            counts["str"] += 1
    return max(counts, key=counts.get) if counts else "str"


def _extract_with_csv(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and raw text content from a CSV file.
    """
    metadata, encoding = initialize_metadata(
        path, create_structured_data_metadata, "CSV"
    )
    content: str | None = None

    with open(path, "r", encoding=encoding, errors="replace") as f:
        content = f.read()
        # For CSV analysis, re-read after getting content or use StringIO
        f.seek(0)
        first_line = f.readline()
        if not first_line:  # Empty file
            return metadata, content
        delimiter = _detect_csv_delimiter(first_line)
        f.seek(0)
        reader = csv.reader(f, delimiter=delimiter)
        rows = list(reader)

    if not rows:
        return metadata, content

    header = rows[0]
    has_header = detect_csv_header(header)
    metadata["has_header"] = has_header

    if has_header:
        metadata["columns"] = header
        rows = rows[1:]
    else:
        metadata["columns"] = [f"Column_{i+1}" for i in range(len(header))]
        rows = rows

    metadata["column_count"] = len(metadata["columns"])
    metadata["record_count"] = len(rows)

    if rows and metadata["columns"]:
        types = {}
        for i, column_name in enumerate(metadata["columns"]):
            # Ensure index i is within bounds for all rows
            values = [row[i] if i < len(row) else "" for row in rows]
            types[column_name] = _infer_csv_column_data_types(values)
        metadata["data_types"] = types

    return metadata, content


def _extract_with_json(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and raw text content from a JSON file.
    """
    metadata, encoding = initialize_metadata(
        path, create_structured_data_metadata, "JSON"
    )
    content: str | None = None

    with open(path, "r", encoding=encoding, errors="replace") as f:
        content = f.read()

    data = json.loads(content)

    if isinstance(data, list):
        structure = analyze_list_structure(data)
        metadata.update(structure)
        if data and isinstance(data[0], dict):
            metadata["data_types"] = infer_json_data_types(data[0])
    elif isinstance(data, dict):
        structure = analyze_dict_structure(data)
        metadata.update(structure)
        metadata["data_types"] = infer_json_data_types(data)  # Infer for top-level dict

    return metadata, content


def _extract_with_yaml(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and raw text content from a YAML file.
    """
    metadata, encoding = initialize_metadata(
        path, create_structured_data_metadata, "YAML"
    )
    content: str | None = None

    with open(path, "r", encoding=encoding, errors="replace") as f:
        content = f.read()
    data = yaml.safe_load(content)
    if isinstance(data, list):
        structure = analyze_list_structure(data)
        metadata.update(structure)
        # data_types could be inferred similarly to JSON if needed
    elif isinstance(data, dict):
        structure = analyze_dict_structure(data)
        metadata.update(structure)
        # data_types could be inferred similarly to JSON if needed

    return metadata, content


def _extract_with_toml(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and raw text content from a TOML file.
    """
    metadata, _ = initialize_metadata(
        path, create_structured_data_metadata, "TOML"
    )  # encoding not used by tomli.load with 'rb'
    content: str | None = None

    with open(path, "rb") as f:  # tomli.load expects a binary file
        data = tomli.load(f)
    # Read again in text mode for content, using detected encoding for consistency
    _, encoding = initialize_metadata(path, lambda p: {}, None)  # Just to get encoding
    with open(path, "r", encoding=encoding, errors="replace") as f_text:
        content = f_text.read()

    if isinstance(data, dict):
        structure = analyze_dict_structure(data)
        metadata.update(structure)

    return metadata, content


def _extract_with_ini(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and raw text content from an INI file.
    """
    metadata, encoding = initialize_metadata(
        path, create_structured_data_metadata, "INI"
    )
    content: str | None = None

    with open(path, "r", encoding=encoding, errors="replace") as f:
        content = f.read()

    config = configparser.ConfigParser()
    # Use read_string instead of read(path) to avoid re-opening after getting content
    config.read_string(content)

    sections = config.sections()
    metadata["record_count"] = len(sections)
    all_keys = set()
    for section in sections:
        all_keys.update(config[section].keys())
    metadata["columns"] = list(all_keys)
    metadata["column_count"] = len(all_keys)

    return metadata, content


def extract_structured_data_metadata(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and raw text content from a structured data file.

    Args:
        path: Path to the structured data file

    Returns:
        tuple[dict[str, Any], str | None]: Specific metadata and raw text content.
    """
    # File existence validation is handled by the factory
    extension = get_file_extension(path)

    if extension == ".csv":
        return _extract_with_csv(path)
    elif extension == ".json":
        return _extract_with_json(path)
    elif extension in [".yaml", ".yml"]:
        return _extract_with_yaml(path)
    elif extension == ".toml":
        return _extract_with_toml(path)
    elif extension == ".ini":
        return _extract_with_ini(path)
    else:
        logger.warning(
            f"Unsupported structured data file type: {path}, returning default metadata."
        )
        return create_structured_data_metadata(), None
