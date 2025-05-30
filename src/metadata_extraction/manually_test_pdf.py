"""
Command-line interface for the docmeta package.

This module provides a command-line interface for extracting metadata from files.
"""

import argparse
import os
from typing import Any

from docmeta.core import extract_metadata
from docmeta.utils.serializers import save_json


def find_files(path: str) -> list[str]:
    """
    Find files in the given path.

    Args:
        path: File or directory path

    Returns:
        List[str]: List of file paths
    """
    file_paths = []

    if os.path.isfile(path):
        file_paths.append(path)
    elif os.path.isdir(path):
        for root, _, files in os.walk(path):
            for file in files:
                file_paths.append(os.path.join(root, file))

    return file_paths


def extract_and_save_metadata(
    file_paths: list[str],
    output_dir: str,
    count_tokens: bool = False,
    extract_keywords_language: str | None = None,
) -> dict[str, dict[str, Any]]:
    # Create output directory
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Extract metadata from each file
    all_metadata = {}

    for file_path in file_paths:
        # Extract metadata
        metadata = extract_metadata(
            file_path,
            count_tokens_flag=count_tokens,
            extract_keywords_language=extract_keywords_language,
        )

        file_name = os.path.basename(file_path)
        all_metadata[file_name] = metadata

        # Save to JSON file
        output_file = os.path.join(output_dir, f"{file_name}.json")
        save_json(metadata, output_file)
        print(f"Extracted metadata from {file_name} and saved to {output_file}")

    # Summarize keyword extraction
    files_with_keywords = sum(
        1 for m in all_metadata.values() if m.get("extracted_keywords")
    )
    if files_with_keywords > 0:
        print(
            f"\nKeywords extracted for: {files_with_keywords} file(s) using language: {extract_keywords_language}"
        )

    return all_metadata


def main() -> None:
    """Main entry point for the command-line interface."""
    parser = argparse.ArgumentParser(description="Extract metadata from files.")
    parser.add_argument(
        "--path", default="pdfs", help="Path to file or directory (default: pdfs)"
    )
    parser.add_argument(
        "--outdir",
        default="output",
        help="Output directory for JSON files (default: output)",
    )
    parser.add_argument(
        "--token-count", action="store_true", help="Count tokens in text-based files"
    )
    parser.add_argument(
        "--extract-keywords",
        help='Extract keywords from text-based files (specify language, e.g., "french", "english")',
    )

    args = parser.parse_args()

    # Find files
    file_paths = find_files(args.path)

    if not file_paths:
        print("No files found.")
        return

    print(f"Found {len(file_paths)} files.")

    # Extract and save metadata
    extract_and_save_metadata(
        file_paths,
        output_dir=args.outdir,
        count_tokens=args.token_count,
        extract_keywords_language=args.extract_keywords,
    )


if __name__ == "__main__":
    main()
