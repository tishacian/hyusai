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

from docmeta.core.types import create_structured_data_metadata # returns dict[str, Any]
from docmeta.utils.text_processing import (
    analyze_list_structure,
    analyze_dict_structure,
    get_file_extension,
    initialize_metadata_with_encoding, # Returns (metadata_dict, encoding)
    infer_json_data_types,
    detect_csv_header
)

# Configure logger
logger = logging.getLogger(__name__)


def _detect_csv_delimiter(sample_line: str) -> str:
    """
    Detect CSV delimiter.
    """
    delimiters = [',', ';', '\t', '|']
    delimiter_counts = {d: sample_line.count(d) for d in delimiters}
    return max(delimiter_counts, key=delimiter_counts.get) if delimiter_counts else ','


def _infer_csv_column_data_types(values: list[str]) -> str:
    """
    Infer data types from CSV column values.
    """
    type_counts = {'int': 0, 'float': 0, 'bool': 0, 'str': 0}
    for value in values[:100]: # Sample first 100 values
        value = value.strip()
        if not value: continue
        if value.lower() in ['true', 'false', 'yes', 'no', '1', '0']: type_counts['bool'] += 1
        elif value.isdigit() or (value.startswith('-') and value[1:].isdigit()): type_counts['int'] += 1
        elif '.' in value and value.replace('.', '', 1).replace('-', '', 1).isdigit(): type_counts['float'] += 1
        else: type_counts['str'] += 1
    return max(type_counts, key=type_counts.get) if type_counts else 'str'


def _extract_with_csv(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and raw text content from a CSV file.
    """
    metadata, encoding = initialize_metadata_with_encoding(path, create_structured_data_metadata, "CSV")
    raw_content: str | None = None
    try:
        with open(path, 'r', encoding=encoding, errors='replace') as f:
            raw_content = f.read()
            # For CSV analysis, re-read after getting raw_content or use StringIO
            f.seek(0)
            first_line = f.readline()
            if not first_line: # Empty file
                return metadata, raw_content
            delimiter = _detect_csv_delimiter(first_line)
            f.seek(0)
            reader = csv.reader(f, delimiter=delimiter)
            rows = list(reader)
        
        if not rows:
            return metadata, raw_content

        first_row = rows[0]
        has_header = detect_csv_header(first_row)
        metadata["has_header"] = has_header

        if has_header:
            metadata["columns"] = first_row
            data_rows = rows[1:]
        else:
            metadata["columns"] = [f"Column_{i+1}" for i in range(len(first_row))]
            data_rows = rows
        
        metadata["column_count"] = len(metadata["columns"])
        metadata["record_count"] = len(data_rows)

        if data_rows and metadata["columns"]:
            data_types = {}
            for i, column_name in enumerate(metadata["columns"]):
                # Ensure index i is within bounds for all data_rows
                column_values = [row[i] if i < len(row) else '' for row in data_rows]
                data_types[column_name] = _infer_csv_column_data_types(column_values)
            metadata["data_types"] = data_types
            
    except Exception as e:
        logger.error(f"Error extracting CSV metadata from {path}: {e}")
        # raw_content might be partially read or None, return what we have
    return metadata, raw_content


def _extract_with_json(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and raw text content from a JSON file.
    """
    metadata, encoding = initialize_metadata_with_encoding(path, create_structured_data_metadata, "JSON")
    raw_content: str | None = None
    try:
        with open(path, 'r', encoding=encoding, errors='replace') as f:
            raw_content = f.read()
        data = json.loads(raw_content)

        if isinstance(data, list):
            structure_info = analyze_list_structure(data)
            metadata.update(structure_info)
            if data and isinstance(data[0], dict):
                metadata["data_types"] = infer_json_data_types(data[0])
        elif isinstance(data, dict):
            structure_info = analyze_dict_structure(data)
            metadata.update(structure_info)
            metadata["data_types"] = infer_json_data_types(data) # Infer for top-level dict
            
    except Exception as e:
        logger.error(f"Error extracting JSON metadata from {path}: {e}")
    return metadata, raw_content


def _extract_with_yaml(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and raw text content from a YAML file.
    """
    metadata, encoding = initialize_metadata_with_encoding(path, create_structured_data_metadata, "YAML")
    raw_content: str | None = None
    try:
        with open(path, 'r', encoding=encoding, errors='replace') as f:
            raw_content = f.read()
        data = yaml.safe_load(raw_content)
        if isinstance(data, list):
            structure_info = analyze_list_structure(data)
            metadata.update(structure_info)
            # data_types could be inferred similarly to JSON if needed
        elif isinstance(data, dict):
            structure_info = analyze_dict_structure(data)
            metadata.update(structure_info)
            # data_types could be inferred similarly to JSON if needed
    except Exception as e:
        logger.error(f"Error extracting YAML metadata from {path}: {e}")
    return metadata, raw_content


def _extract_with_toml(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and raw text content from a TOML file.
    """
    metadata, _ = initialize_metadata_with_encoding(path, create_structured_data_metadata, "TOML") # encoding not used by tomli.load with 'rb'
    raw_content: str | None = None
    try:
        with open(path, 'rb') as f: # tomli.load expects a binary file
            data = tomli.load(f)
        # Read again in text mode for raw_content, using detected encoding for consistency
        _, encoding = initialize_metadata_with_encoding(path, lambda p: {}, None) # Just to get encoding
        with open(path, 'r', encoding=encoding, errors='replace') as f_text:
            raw_content = f_text.read()

        if isinstance(data, dict):
            structure_info = analyze_dict_structure(data)
            metadata.update(structure_info)
    except Exception as e:
        logger.error(f"Error extracting TOML metadata from {path}: {e}")
        if not raw_content: # If text read failed too
            try: # Attempt to get raw content even if TOML parsing failed
                _, encoding = initialize_metadata_with_encoding(path, lambda p: {}, None)
                with open(path, 'r', encoding=encoding, errors='replace') as f_text:
                    raw_content = f_text.read()
            except: pass
    return metadata, raw_content


def _extract_with_ini(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and raw text content from an INI file.
    """
    metadata, encoding = initialize_metadata_with_encoding(path, create_structured_data_metadata, "INI")
    raw_content: str | None = None
    try:
        with open(path, 'r', encoding=encoding, errors='replace') as f:
            raw_content = f.read()
        
        config = configparser.ConfigParser()
        # Use read_string instead of read(path) to avoid re-opening after getting raw_content
        config.read_string(raw_content)

        sections = config.sections()
        metadata["record_count"] = len(sections)
        all_keys = set()
        for section in sections:
            all_keys.update(config[section].keys())
        metadata["columns"] = list(all_keys)
        metadata["column_count"] = len(all_keys)
    except Exception as e:
        logger.error(f"Error extracting INI metadata from {path}: {e}")
    return metadata, raw_content


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
        logger.warning(f"Unsupported structured data file type: {path}, returning default metadata.")
        return create_structured_data_metadata(), None
