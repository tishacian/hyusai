"""
Serializers for document metadata.

This module provides serializers for converting document metadata to various formats.
"""

import json
from datetime import datetime
from typing import Any, Dict, Union

from docmeta.core.types import MetadataType


class DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime objects."""
    
    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def to_json(metadata: MetadataType, indent: int = None) -> str:
    """
    Convert metadata to JSON.
    
    Args:
        metadata: Metadata to convert
        indent: Number of spaces to indent (None for no indentation)
        
    Returns:
        str: JSON string
    """
    return json.dumps(metadata, cls=DateTimeEncoder, indent=indent, ensure_ascii=False)


def to_dict(metadata: MetadataType) -> Dict[str, Any]:
    """
    Convert metadata to a dictionary.
    
    Args:
        metadata: Metadata to convert
        
    Returns:
        Dict[str, Any]: Dictionary representation of metadata
    """
    # Convert datetime objects to ISO format strings
    result = {}
    for key, value in metadata.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


def save_json(metadata: MetadataType, path: str, indent: int = 2) -> None:
    """
    Save metadata to a JSON file.
    
    Args:
        metadata: Metadata to save
        path: Path to the output file
        indent: Number of spaces to indent (None for no indentation)
    """
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, cls=DateTimeEncoder, indent=indent, ensure_ascii=False)
