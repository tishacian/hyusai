"""
Script to extract metadata from PDF files in the data folder.

This script:
1. Finds all PDF files in the data folder
2. Extracts metadata from each PDF
3. Saves the metadata to a JSON file in the output folder
4. Prints a summary of the extracted metadata

Optional token counting can be enabled with the --count-tokens flag.
Optional keyword extraction can be enabled with the --extract-keywords flag.
"""

import os
import sys
import argparse
import time # Added for timing
from typing import Any, Dict, List

# Import from the new modular structure
from docmeta.core.api import extract_metadata
from docmeta.utils.serializers import save_json

# Import extractors to register them
import docmeta.extractors


def find_pdf_files(data_dir: str) -> List[str]:
    """
    Find all PDF files in the data directory.

    Args:
        data_dir: Path to the data directory

    Returns:
        List[str]: List of paths to PDF files
    """
    pdf_files = []

    # Check if data directory exists
    if not os.path.exists(data_dir):
        print(f"Error: Data directory not found: {data_dir}", file=sys.stderr)
        return pdf_files

    # Find all PDF files
    for root, _, files in os.walk(data_dir):
        for file in files:
            if file.lower().endswith('.pdf'):
                pdf_files.append(os.path.join(root, file))

    return pdf_files


def extract_and_save_metadata(pdf_files: List[str], output_dir: str, 
                              count_tokens: bool = False, 
                              extract_keywords: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    Extract metadata from PDF files and save to JSON files.

    Args:
        pdf_files: List of paths to PDF files
        output_dir: Path to the output directory
        count_tokens: Whether to count tokens in the PDF text
        extract_keywords: Whether to extract keywords from PDF text

    Returns:
        Dict[str, Dict[str, Any]]: Dictionary of metadata for each PDF file
    """
    # Create output directory if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Extract metadata from each PDF file
    all_metadata = {}

    for pdf_file in pdf_files:
        pdf_start_time = time.perf_counter()
        try:
            # Extract metadata using the new API
            metadata = extract_metadata(pdf_file, count_tokens=count_tokens, extract_keywords=extract_keywords)
            
            pdf_end_time = time.perf_counter()
            processing_time_pdf = pdf_end_time - pdf_start_time
            metadata['processing_time_seconds'] = processing_time_pdf

            # Add to dictionary
            file_name = os.path.basename(pdf_file)
            all_metadata[file_name] = metadata

            # Save to JSON file
            output_file = os.path.join(output_dir, f"{file_name}.json")
            save_json(metadata, output_file)

            # Print token count information if available
            time_str = f"(time: {processing_time_pdf:.2f}s)"
            if count_tokens and metadata.get('token_count'):
                cl100k_tokens = metadata['token_count'].get('cl100k_base', 0)
                print(f"Extracted metadata from {file_name} (tokens: {cl100k_tokens}) {time_str} and saved to {output_file}")
            elif extract_keywords and metadata.get('extracted_keywords'):
                print(f"Extracted metadata and keywords from {file_name} {time_str} and saved to {output_file}")
            else:
                print(f"Extracted metadata from {file_name} {time_str} and saved to {output_file}")

        except Exception as e:
            pdf_end_time = time.perf_counter() # time even if error
            processing_time_pdf = pdf_end_time - pdf_start_time
            print(f"Error extracting metadata from {pdf_file} (took {processing_time_pdf:.2f}s): {e}", file=sys.stderr)

    # Save all metadata to a single JSON file
    all_metadata_file = os.path.join(output_dir, "all_metadata.json")
    save_json(all_metadata, all_metadata_file)

    print(f"Saved all metadata to {all_metadata_file}")

    return all_metadata


def print_summary(all_metadata: Dict[str, Dict[str, Any]], total_processing_time: float) -> None:
    """
    Print a summary of the extracted metadata.

    Args:
        all_metadata: Dictionary of metadata for each PDF file
        total_processing_time: Total time taken for metadata extraction
    """
    print("\nSummary of extracted metadata:")
    num_files_processed = len(all_metadata)
    print(f"Total number of PDF files processed successfully: {num_files_processed}")

    # Count files with various metadata fields
    has_author = sum(1 for metadata in all_metadata.values() if metadata.get('author'))
    has_title = sum(1 for metadata in all_metadata.values() if metadata.get('title'))
    has_subject = sum(1 for metadata in all_metadata.values() if metadata.get('subject'))
    has_keywords = sum(1 for metadata in all_metadata.values() if metadata.get('keywords'))

    print(f"Files with author metadata: {has_author}")
    print(f"Files with title metadata: {has_title}")
    print(f"Files with subject metadata: {has_subject}")
    print(f"Files with keywords metadata: {has_keywords}")

    # Calculate total number of pages
    total_pages = sum(metadata.get('num_pages', 0) for metadata in all_metadata.values())
    print(f"Total number of pages: {total_pages}")

    # Calculate average file size
    total_size = sum(metadata.get('size', 0) for metadata in all_metadata.values())
    avg_size = total_size / num_files_processed if num_files_processed else 0
    print(f"Average file size: {avg_size / 1024 / 1024:.2f} MB")

    # Print token count information if available
    has_token_count = sum(1 for metadata in all_metadata.values() if metadata.get('token_count'))
    if has_token_count > 0:
        # Calculate total tokens (cl100k_base is used by ChatGPT/GPT-4)
        total_tokens = sum(
            (metadata.get('token_count') or {}).get('cl100k_base', 0)
            for metadata in all_metadata.values()
        )
        avg_tokens = total_tokens / has_token_count if has_token_count else 0

        print(f"\nToken count information:")
        print(f"Files with token count: {has_token_count}")
        print(f"Total tokens (cl100k_base): {total_tokens:,}")
        print(f"Average tokens per file: {avg_tokens:,.0f}")

    # Print keyword extraction summary if keywords were extracted for any file
    files_with_extracted_keywords = sum(1 for m in all_metadata.values() if m.get('extracted_keywords'))
    if files_with_extracted_keywords > 0:
        print(f"\nKeyword extraction summary:")
        print(f"Files with extracted keywords: {files_with_extracted_keywords}")

    # Print processing time summary
    print(f"\nProcessing time summary:")
    print(f"Total processing time for all files: {total_processing_time:.2f} seconds")
    
    individual_processing_times = [m.get('processing_time_seconds', 0) for m in all_metadata.values() if m.get('processing_time_seconds') is not None]
    if individual_processing_times:
        avg_processing_time_per_file = sum(individual_processing_times) / len(individual_processing_times)
        print(f"Average processing time per successfully processed file: {avg_processing_time_per_file:.2f} seconds")
    elif num_files_processed > 0 : # if all files failed to record individual time but some were processed
        avg_processing_time_per_file = total_processing_time / num_files_processed
        print(f"Average processing time per successfully processed file (overall/count): {avg_processing_time_per_file:.2f} seconds")


def main() -> None:
    """Main entry point for the script."""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Extract metadata from PDF files.')
    parser.add_argument('--data-dir', '-d', default='data', help='Directory containing PDF files')
    parser.add_argument('--output-dir', '-o', default='output', help='Directory to save metadata')
    parser.add_argument('--count-tokens', '-t', action='store_true', help='Count tokens in PDF text')
    parser.add_argument('--extract-keywords', '-k', action='store_true', help='Extract keywords from PDF text')
    args = parser.parse_args()

    # Define directories
    data_dir = args.data_dir
    output_dir = args.output_dir
    count_tokens = args.count_tokens
    extract_keywords = args.extract_keywords

    # Find PDF files
    print(f"Finding PDF files in {data_dir}...")
    pdf_files = find_pdf_files(data_dir)

    if not pdf_files:
        print("No PDF files found.")
        return

    print(f"Found {len(pdf_files)} PDF files.")

    # Extract and save metadata
    if count_tokens:
        print(f"Extracting metadata with token counting and saving to {output_dir}...")
    elif extract_keywords:
        print(f"Extracting metadata with keyword extraction and saving to {output_dir}...")
    else:
        print(f"Extracting metadata and saving to {output_dir}...")

    overall_start_time = time.perf_counter()
    all_metadata = extract_and_save_metadata(pdf_files, output_dir, 
                                           count_tokens=count_tokens, 
                                           extract_keywords=extract_keywords)
    overall_end_time = time.perf_counter()
    total_processing_time = overall_end_time - overall_start_time

    # Print summary
    print_summary(all_metadata, total_processing_time)


if __name__ == "__main__":
    main()
