"""
Test script to extract metadata from a single PDF file.
"""

import os
import sys
import json
from datetime import datetime

# Try to import PyPDF2
try:
    from PyPDF2 import PdfReader
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False
    print("PyPDF2 not available")

# Try to import PyMuPDF
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    print("PyMuPDF not available")


class DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime objects."""
    
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def extract_pdf_metadata_with_pypdf2(path):
    """Extract metadata from a PDF file using PyPDF2."""
    if not PYPDF2_AVAILABLE:
        print("PyPDF2 not available")
        return {}
    
    print(f"Extracting metadata from {path} using PyPDF2")
    
    try:
        with open(path, 'rb') as file:
            reader = PdfReader(file)
            
            # Get basic info
            metadata = {
                "num_pages": len(reader.pages),
                "encrypted": reader.is_encrypted,
            }
            
            # Get page size
            if reader.pages and len(reader.pages) > 0:
                page = reader.pages[0]
                if hasattr(page, 'mediabox'):
                    width = float(page.mediabox.width)
                    height = float(page.mediabox.height)
                    metadata["page_size"] = {"width": width, "height": height}
            
            # Get document info
            print(f"reader.metadata: {reader.metadata}")
            print(f"reader.metadata type: {type(reader.metadata)}")
            
            if reader.metadata:
                info = reader.metadata
                print(f"info: {info}")
                print(f"info type: {type(info)}")
                print(f"info dir: {dir(info)}")
                
                # Try to get attributes
                for attr in ['author', 'creator', 'producer', 'subject', 'title', 'keywords']:
                    if hasattr(info, attr):
                        value = getattr(info, attr)
                        if value:
                            print(f"{attr}: {value}")
                            metadata[attr] = value
                
                # Try to get dictionary items
                for key in ['/Author', '/Creator', '/Producer', '/Subject', '/Title', '/Keywords']:
                    try:
                        if key in info:
                            value = info[key]
                            if value:
                                print(f"{key}: {value}")
                                metadata[key.lstrip('/')] = value
                    except:
                        pass
            
            return metadata
    
    except Exception as e:
        print(f"Error extracting metadata with PyPDF2: {e}")
        return {}


def extract_pdf_metadata_with_pymupdf(path):
    """Extract metadata from a PDF file using PyMuPDF."""
    if not PYMUPDF_AVAILABLE:
        print("PyMuPDF not available")
        return {}
    
    print(f"Extracting metadata from {path} using PyMuPDF")
    
    try:
        doc = fitz.open(path)
        
        # Get basic info
        metadata = {
            "num_pages": doc.page_count,
        }
        
        # Get page size
        if doc.page_count > 0:
            page = doc[0]
            rect = page.rect
            metadata["page_size"] = {"width": rect.width, "height": rect.height}
        
        # Get document info
        doc_info = doc.metadata
        print(f"doc_info: {doc_info}")
        
        # Extract metadata
        for key, pdf_key in [
            ('author', 'author'),
            ('creator', 'creator'),
            ('producer', 'producer'),
            ('subject', 'subject'),
            ('title', 'title'),
            ('keywords', 'keywords'),
        ]:
            if key in doc_info and doc_info[key]:
                print(f"{key}: {doc_info[key]}")
                metadata[pdf_key] = doc_info[key]
        
        doc.close()
        return metadata
    
    except Exception as e:
        print(f"Error extracting metadata with PyMuPDF: {e}")
        return {}


def main():
    """Main entry point for the script."""
    # Check if a file path is provided
    if len(sys.argv) < 2:
        print("Usage: python test_pdf.py <path_to_pdf>")
        return
    
    # Get the file path
    path = sys.argv[1]
    
    # Check if the file exists
    if not os.path.exists(path):
        print(f"Error: File not found: {path}")
        return
    
    # Extract metadata using PyPDF2
    pypdf2_metadata = extract_pdf_metadata_with_pypdf2(path)
    print("\nPyPDF2 metadata:")
    print(json.dumps(pypdf2_metadata, indent=2, cls=DateTimeEncoder))
    
    # Extract metadata using PyMuPDF
    pymupdf_metadata = extract_pdf_metadata_with_pymupdf(path)
    print("\nPyMuPDF metadata:")
    print(json.dumps(pymupdf_metadata, indent=2, cls=DateTimeEncoder))


if __name__ == "__main__":
    main()
