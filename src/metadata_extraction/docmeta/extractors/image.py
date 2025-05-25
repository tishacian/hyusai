"""
Image Metadata Extractor

This module provides functionality to extract metadata from image files.
"""

import os

from PIL import Image, ExifTags

from docmeta.core.types import ImageMetaData, create_image_metadata


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

    # Initialize metadata with common file properties and defaults
    image_metadata = create_image_metadata(path)

    # Extract image-specific metadata using PIL
    with Image.open(path) as img:
        # Get image dimensions (required fields)
        width, height = img.size
        image_metadata["width"] = width
        image_metadata["height"] = height

        # Get color mode (optional field)
        image_metadata["color_mode"] = getattr(img, 'mode', None)

        # Get bit depth (optional field)
        image_metadata["bit_depth"] = getattr(img, 'bits', None)

        # Get DPI (optional fields)
        dpi_info = getattr(img, 'info', {}).get('dpi', None)
        if dpi_info and len(dpi_info) >= 2:
            image_metadata["dpi_x"] = int(dpi_info[0]) if dpi_info[0] is not None else None
            image_metadata["dpi_y"] = int(dpi_info[1]) if dpi_info[1] is not None else None

        # Extract EXIF data if available (optional field)
        exif_data = {}
        exif_method = getattr(img, '_getexif', None)
        if exif_method:
            exif = exif_method()
            if exif:
                for tag_id, value in exif.items():
                    tag = ExifTags.TAGS.get(tag_id, str(tag_id))
                    # Convert bytes to string if possible
                    if isinstance(value, bytes):
                        try:
                            value = value.decode('utf-8')
                        except UnicodeDecodeError:
                            value = str(value)
                    exif_data[tag] = value

        # Only set exif_data if we found any data
        image_metadata["exif_data"] = exif_data if exif_data else None

    return image_metadata
