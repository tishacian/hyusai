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

    return image_metadata
