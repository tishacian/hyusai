"""
Image Metadata Extractor

This module provides functionality to extract metadata from image files.
"""

from typing import Any

from PIL import ExifTags, Image

from ..core.defaults import \
    create_image_metadata  # create_image_metadata returns dict[str, Any]


def extract_image_metadata(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata from an image file.

    Args:
        path: Path to the image file

    Returns:
        tuple[dict[str, Any], str | None]: Specific image metadata and None for text content.
    """
    # Initialize specific metadata with defaults
    metadata = create_image_metadata()

    with Image.open(path) as img:
        width, height = img.size
        metadata["width"] = width
        metadata["height"] = height

        metadata["color_mode"] = getattr(img, "mode", None)
        metadata["bit_depth"] = getattr(img, "bits", None)

        dpi_info = getattr(img, "info", {}).get("dpi", None)
        if dpi_info and len(dpi_info) >= 2:
            metadata["dpi_x"] = int(dpi_info[0]) if dpi_info[0] is not None else None
            metadata["dpi_y"] = int(dpi_info[1]) if dpi_info[1] is not None else None

        exif_data = {}
        exif_method = getattr(img, "_getexif", None)
        if exif_method:
            exif = exif_method()
            if exif:
                for tag_id, value in exif.items():
                    tag = ExifTags.TAGS.get(tag_id, str(tag_id))
                    if isinstance(value, bytes):
                        value = value.decode("utf-8", errors="replace")
                    exif_data[tag] = value

        metadata["exif_data"] = exif_data if exif_data else None

    return metadata, None
