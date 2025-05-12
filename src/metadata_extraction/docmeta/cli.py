"""
Command-line interface for the docmeta package.

This module provides a command-line interface for extracting metadata from files.
"""

import argparse
import os
import sys
from typing import Dict, Any, List

from docmeta.core.api import extract_metadata
from docmeta.utils.serializers import save_json


def find_files(paths: List[str], recursive: bool = False) -> List[str]:
    """
    Find files from a list of paths.
    
    Args:
        paths: List of file or directory paths
        recursive: Whether to search directories recursively
        
    Returns:
        List[str]: List of file paths
    """
    file_paths = []
    
    for path in paths:
        if os.path.isfile(path):
            file_paths.append(path)
        elif os.path.isdir(path):
            if recursive:
                for root, _, files in os.walk(path):
                    for file in files:
                        file_paths.append(os.path.join(root, file))
            else:
                for item in os.listdir(path):
                    item_path = os.path.join(path, item)
                    if os.path.isfile(item_path):
                        file_paths.append(item_path)
    
    return file_paths


def extract_and_save_metadata(file_paths: List[str], output_dir: str = None, 
                             all_metadata_file: str = None,
                             count_tokens: bool = False,
                             extract_keywords: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    Extract metadata from files and save to JSON files.
    
    Args:
        file_paths: List of file paths
        output_dir: Directory to save individual JSON files (None to skip)
        all_metadata_file: Path to save all metadata (None to skip)
        count_tokens: Whether to count tokens in text-based files
        extract_keywords: Whether to extract keywords from text-based files
        
    Returns:
        Dict[str, Dict[str, Any]]: Dictionary of metadata for each file
    """
    # Create output directory if specified
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Extract metadata from each file
    all_metadata = {}
    
    for file_path in file_paths:
        try:
            # Extract metadata
            metadata = extract_metadata(file_path, count_tokens=count_tokens, extract_keywords=extract_keywords)
            
            # Add to dictionary
            file_name = os.path.basename(file_path)
            all_metadata[file_name] = metadata
            
            # Save to JSON file if output directory is specified
            if output_dir:
                output_file = os.path.join(output_dir, f"{file_name}.json")
                save_json(metadata, output_file)
                print(f"Extracted metadata from {file_name} and saved to {output_file}")
        
        except Exception as e:
            print(f"Error extracting metadata from {file_path}: {e}", file=sys.stderr)
    
    # Save all metadata to a single JSON file if specified
    if all_metadata_file:
        save_json(all_metadata, all_metadata_file)
        print(f"Saved all metadata to {all_metadata_file}")
    
    # Summarize keyword extraction
    files_with_keywords = sum(1 for m in all_metadata.values() if m.get('extracted_keywords'))
    if files_with_keywords > 0:
        print(f"\nKeywords extracted for: {files_with_keywords} file(s)")
    
    return all_metadata


def print_summary(all_metadata: Dict[str, Dict[str, Any]]) -> None:
    """
    Print a summary of the extracted metadata.
    
    Args:
        all_metadata: Dictionary of metadata for each file
    """
    print("\nSummary of extracted metadata:")
    print(f"Total number of files: {len(all_metadata)}")
    
    # Count files by type
    file_types = {}
    for metadata in all_metadata.values():
        ext = metadata.get('file_extension', '').lower()
        file_types[ext] = file_types.get(ext, 0) + 1
    
    print("\nFile types:")
    for ext, count in sorted(file_types.items()):
        print(f"  {ext or 'unknown'}: {count}")
    
    # Calculate total size
    total_size = sum(metadata.get('size', 0) for metadata in all_metadata.values())
    avg_size = total_size / len(all_metadata) if all_metadata else 0
    print(f"\nTotal size: {total_size / 1024 / 1024:.2f} MB")
    print(f"Average size: {avg_size / 1024 / 1024:.2f} MB")


def main() -> None:
    """Main entry point for the command-line interface."""
    parser = argparse.ArgumentParser(description='Extract metadata from files.')
    parser.add_argument('paths', nargs='+', help='Paths to files or directories')
    parser.add_argument('--recursive', '-r', action='store_true', help='Search directories recursively')
    parser.add_argument('--output-dir', '-o', help='Output directory for individual JSON files')
    parser.add_argument('--all-metadata', '-a', help='Path to save all metadata in a single JSON file')
    parser.add_argument('--summary', '-s', action='store_true', help='Print summary of extracted metadata')
    parser.add_argument('--count-tokens', action='store_true', help='Count tokens in text-based files (e.g., for PDFs)')
    parser.add_argument('--extract-keywords', action='store_true', help='Extract keywords from text-based files')
    
    args = parser.parse_args()
    
    # Find files
    file_paths = find_files(args.paths, args.recursive)
    
    if not file_paths:
        print("No files found.")
        return
    
    print(f"Found {len(file_paths)} files.")
    
    # Extract and save metadata
    all_metadata = extract_and_save_metadata(
        file_paths, 
        output_dir=args.output_dir, 
        all_metadata_file=args.all_metadata,
        count_tokens=args.count_tokens,
        extract_keywords=args.extract_keywords
    )
    
    # Print summary if requested
    if args.summary:
        print_summary(all_metadata)


if __name__ == "__main__":
    main()
