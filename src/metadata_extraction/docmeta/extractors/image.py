"""
Image Metadata Extractor

This module provides functionality to extract metadata from image files.
"""

import os
from typing import Any, cast

try:
    from PIL import Image, ExifTags
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from docmeta.core.common import get_file_common_metadata
from docmeta.core.types import ImageMetaData


def extract_image_metadata(path: str) -> ImageMetaData:
    """
    Extract metadata from an image file.

    Args:
        path: Path to the image file

    Returns:
        ImageMetaData: Metadata for the image file
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    # Get common metadata
    common_metadata = get_file_common_metadata(path)

    # Initialize image-specific metadata with default values
    image_metadata: dict[str, Any] = {
        **common_metadata,
        "width": 0,
        "height": 0,
        "color_mode": None,
        "bit_depth": 0,
        "dpi_x": None,
        "dpi_y": None,
        "exif_data": None,
    }

    # Try to extract image-specific metadata using PIL
    if PIL_AVAILABLE:
        try:
            with Image.open(path) as img:
                # Get image dimensions
                image_metadata["width"], image_metadata["height"] = img.size

                # Get color mode
                image_metadata["color_mode"] = img.mode

                # Get bit depth
                if hasattr(img, 'bits'):
                    image_metadata["bit_depth"] = img.bits

                # Get DPI
                if hasattr(img, 'info') and 'dpi' in img.info:
                    dpi = img.info['dpi']
                    image_metadata["dpi_x"] = dpi[0]
                    image_metadata["dpi_y"] = dpi[1]

                # Extract EXIF data if available
                exif_data = {}
                if hasattr(img, '_getexif') and img._getexif():
                    exif = img._getexif()
                    if exif:
                        for tag_id, value in exif.items():
                            tag = ExifTags.TAGS.get(tag_id, tag_id)
                            # Convert bytes to string if possible
                            if isinstance(value, bytes):
                                try:
                                    value = value.decode('utf-8')
                                except UnicodeDecodeError:
                                    value = str(value)
                            exif_data[tag] = value

                if exif_data:
                    image_metadata["exif_data"] = exif_data

        except Exception as e:
            print(f"Error extracting image metadata: {e}")

    return cast(ImageMetaData, image_metadata)
