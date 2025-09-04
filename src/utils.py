#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Mar 26 15:32:40 2025

@author: kennethezukwoke
"""

import functools
import importlib.util
import logging
import os
import pickle
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
import torch
from functools import cache, lru_cache
from src.globalvariables import (
    CPU_MODEL_SET,
    GPU_MODEL_SET,
    LARGE_MODELS,
    CPUModels,
    Models,
)
from src.system_prompts import (
    ALL_SYSTEM_PROMPT_PHRASES_TO_REMOVE,
    ALL_SYSTEM_PROMPT_SECTIONS_TO_REMOVE,
    DEFAULT_SYSTEM_PROMPT_LANG,
    SystemPromptLangs,
)


# Import nltk stopwords directly (assume availability)
from nltk.corpus import stopwords
NLTK_AVAILABLE = True

from collections.abc import Iterable
from collections import defaultdict
# Import all metadata TypedDicts 
from src.metadata_extraction.docmeta.core.types import (
    FileMetaData,
    PDFMetaData,
    ImageMetaData,
    OfficeMetaData,
    OpenDocumentMetaData,
    TextMetaData,
    MarkupMetaData,
    StructuredDataMetaData,
)

user_tessdata = os.path.expanduser("~/.local/share/tessdata")
if os.path.isdir(user_tessdata) and any(
    f.endswith(".traineddata") for f in os.listdir(user_tessdata)
):
    os.environ["TESSDATA_PREFIX"] = user_tessdata
else:
    # alternative destination for tessdata
    os.environ["TESSDATA_PREFIX"] = "/usr/share/tesseract-ocr/5/tessdata/"


logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

device = "cuda" if torch.cuda.is_available() else "cpu"


# %% time monitoring


def measure_time(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        result = await func(*args, **kwargs)
        end_time = time.time()
        elapsed = end_time - start_time
        logging.info(f"Function {func.__name__} took {elapsed:.4f} seconds")
        return result

    return wrapper


def measure_time_sync(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        elapsed = end_time - start_time
        logging.info(f"Function {func.__name__} took {elapsed:.4f} seconds")
        return result

    return wrapper


# %%  tesseract utils


@lru_cache(maxsize=None)
def configure_tesseract():
    """Configure Tesseract OCR and determine if its available.

    Returns:
        tuple: (tesseract_path, TESSERACT_AVAILABLE) where TESSERACT_AVAILABLE is a boolean
    """
    tesseract_path = get_tesseract_path()
    tesseract_available = tesseract_path is not None

    if tesseract_available:
        try:
            import pytesseract

            pytesseract.pytesseract.tesseract_cmd = tesseract_path
            logging.info(f"Using Tesseract OCR at: {tesseract_path}")
        except ImportError:
            logging.info("pytesseract is not installed.")
            logging.info("Installing pytesseract is required for OCR functionality.")
            tesseract_available = False
    else:
        logging.info(
            "Tesseract OCR binary not found. OCR functionality will be disabled."
        )

    TESSERACT_AVAILABLE = tesseract_available

    return tesseract_path, TESSERACT_AVAILABLE


def get_tesseract_path():
    """Detect the system and set Tesseract path."""
    try:
        # -- search for pytesseract
        pytesseract_spec = importlib.util.find_spec("pytesseract")
        if pytesseract_spec is None:
            logging.info("pytesseract is not installed.")
        else:
            import pytesseract

            current_cmd = pytesseract.pytesseract.tesseract_cmd
            if current_cmd != "tesseract" and os.path.exists(current_cmd):
                return current_cmd
    except Exception as e:
        logging.error(f"🚩 Error checking for pytesseract: {e}")

    try:
        path = shutil.which("tesseract")
        if path:
            logging.info(f"Found tesseract using 'which': {path}")
            return path

        result = subprocess.run(
            ["tesseract", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            logging.info("Tesseract is available in system PATH")
            return "tesseract"
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    # check custom locations
    possible_paths = [
        "/workspace/tesseract/bin/tesseract",  # OVH Custom location
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/opt/tesseract/bin/tesseract",
        "/workspace/bin/tesseract",
        "/workspace/.local/bin/tesseract",
        "/snap/bin/tesseract",
        os.path.expanduser("~/.local/bin/tesseract"),
        os.path.expanduser("~/tesseract/bin/tesseract"),
    ]

    for path in possible_paths:
        if os.path.exists(path):
            logging.info(f"Found tesseract at: {path}")
            return path

    logging.info("No tesseract binary found in standard locations")
    return None


# %% model utils


def gpu_arc_type(device):
    """
    Detect GPU type (A100, H100, L40S)

    Returns
    -------
    str
        'A100', 'H100', 'L40S', or 'other'
    """
    try:
        if not device == "cuda":
            return "other"

        device_props = torch.cuda.get_device_properties(0)
        device_name = device_props.name

        if "H100" in device_name:
            return "H100"
        elif "A100" in device_name:
            return "A100"
        elif "L40S" in device_name:
            return "L40S"
        else:
            total_memory_gb = device_props.total_memory / (1024**3)

            if total_memory_gb >= 80:
                return "H100" if "H100" in device_name else "A100"
            elif total_memory_gb >= 48:
                return "L40S"
            else:
                return "other"
    except Exception as e:
        logging.warning(f"Error detecting GPU type: {e}")
        return "other"


def get_max_model_len(model_name, max_model_len: int = None) -> int:
    """Get maximum context length for each model

    Automatically detects GPU type (A100, H100, L40S) and adjusts context lengths
    for optimal performance and stability.

    Parameters
    -----------
    model_name (str): model name
    max_model_len (int): maximum model length.
                        Default is None.

    Returns
    -------
    int
        Maximum context length in tokens

    Raises
    ------
    ValueError
        If the model name is unknown
    """
    if not max_model_len:
        if model_name in GPU_MODEL_SET:
            gpu_type = gpu_arc_type(device)
            if model_name in LARGE_MODELS:
                return 128 * 1024 if gpu_type in ["A100", "H100"] else 128 * 1024
            elif model_name in [Models.LLAMA3_8B, Models.LLAMA3_70B]:
                return 128 * 1024 if gpu_type in ["A100", "H100"] else 128 * 1024
            elif model_name in [Models.LLAMA2_7B, Models.LLAMA2_13B]:
                return 4 * 1024 if gpu_type in ["A100", "H100"] else 4 * 1024
            elif model_name == Models.TINYLLAMA:
                return 2 * 1024 if gpu_type in ["A100", "H100"] else 2 * 1024
            elif model_name == Models.GEMMA2:
                return 32 * 1024 if gpu_type in ["A100", "H100"] else 32 * 1024
            elif model_name in [Models.MISTRAL_SMALL, Models.MISTRAL_LARGE]:
                return 32 * 1024 if gpu_type in ["A100", "H100"] else 32 * 1024
        elif model_name in CPU_MODEL_SET:
            if model_name == CPUModels.LLAMA32_3B_INSTRUCT:
                return 128 * 1024
            return 1024
        else:
            raise ValueError(f"Error: Unknown model name {model_name}")
    else:
        return max_model_len * 1024


# %% stopwords


def create_stopwords_mlin(data_dir: str = "data"):
    """Create multilingual stopwords

    Parameters
    ----------
    data_dir : str, optional
        Directory to store cache file, by default "data"

    Returns
    -------
    Optional[Set[str]]
        Combined stopwords set, or None if failed
    """
    data_path = Path(data_dir)
    data_path.mkdir(exist_ok=True)
    save_file = data_path / "multilingual_stopwords.pkl"
    languages = ["english", "french", "german", "italian", "russian"]

    if not NLTK_AVAILABLE:
        logging.error("NLTK not available - cannot create stopwords")
        return None

    try:
        combined_stopwords = set()
        for lang in languages:
            lang_stopwords = set(stopwords.words(lang))
            combined_stopwords.update(lang_stopwords)

        if not combined_stopwords:
            logging.error("No stopwords could be loaded from any language")
            return None

        with open(save_file, "wb") as f:
            pickle.dump(combined_stopwords, f, protocol=pickle.HIGHEST_PROTOCOL)

        return combined_stopwords
    except Exception as e:
        logging.error(f"Error creating multilingual stopwords: {e}")
        return None


def load_stopwords(data_dir: str = "data"):
    """Load stopwords, create if not exists

    Parameters
    ----------
    data_dir : str, optional
        Directory containing cache file, by default "data"

    Returns
    -------
    Set[str]
        Combined stopwords set (empty set if all methods fail)
    """
    saved_file = Path(data_dir) / "multilingual_stopwords.pkl"

    if saved_file.exists():
        with open(saved_file, "rb") as f:
            stopwords_set = pickle.load(f)
        return stopwords_set

    stopwords_set = create_stopwords_mlin(data_dir)

    if stopwords_set is None:
        logging.error("Failed to create stopwords - returning empty set")
        return set()

    return stopwords_set


def format_llm_response(
    response: str, language: SystemPromptLangs = DEFAULT_SYSTEM_PROMPT_LANG
) -> str:
    """Format LLM response while preserving tables and structured data.
    Only removes template artifacts and prompt phrases.

    Parameters
    ----------
    response : str
        Raw response from the LLM
    language : SystemPromptLangs, optional
        Language of the reasoning instructions to remove,
        by default DEFAULT_SYSTEM_PROMPT_LANG

    Returns
    -------
    str
        Cleaned response with preserved formatting
    """
    instruction_blocks = [r"\[INST\].*?\[/INST\]", r"\[INST\]", r"\[/INST\]"]
    prompt_sections = ALL_SYSTEM_PROMPT_SECTIONS_TO_REMOVE[language]
    prompt_phrases = ALL_SYSTEM_PROMPT_PHRASES_TO_REMOVE[language]
    try:
        for block in instruction_blocks:
            response = re.sub(block, "", response, flags=re.DOTALL).strip()
        # remove standard prompt sections/phrases
        for section in prompt_sections:
            response = re.sub(
                section, "", response, flags=re.IGNORECASE | re.DOTALL
            ).strip()
        for phrase in prompt_phrases:
            response = re.sub(phrase, "", response, flags=re.MULTILINE).strip()
        return response
    except Exception as e:
        logging.error(f"🚩 An error occurred during response formatting: {str(e)}")
        return "No sufficient context to respond to the question."




@lru_cache(maxsize=1)
def _build_field_type_map() -> dict[str, set[type]]:
    """Build a mapping of metadata field name -> expected python types.

    This inspects the TypedDict annotations defined in the metadata types module
    so the filter logic can perform basic type-aware normalisation when
    comparing metadata values against the user-supplied filter values.
    
    Returns
    -------
    dict[str, set[type]]
        A dictionary mapping metadata field names to sets of expected Python types.
        Keys are field names (strings) and values are sets containing the type
        annotations found across all metadata TypedDict classes.
    """
    field_map: dict[str, set[type]] = {}
    for _cls in (
        FileMetaData,
        PDFMetaData,
        ImageMetaData,
        OfficeMetaData,
        OpenDocumentMetaData,
        TextMetaData,
        MarkupMetaData,
        StructuredDataMetaData,
    ):
        for key, _typ in getattr(_cls, "__annotations__", {}).items():
            field_map.setdefault(key, set()).add(_typ)
    return field_map


def _safe_cast(value: object, target_types: set[type]):
    """Attempt to cast *value* to one of *target_types* (best-effort).

    Only simple numeric / bool / datetime / str conversions are handled. If no
    conversion succeeds, the original *value* is returned.
    
    Parameters
    ----------
    value : object
        The value to attempt casting on.
    target_types : set[type]
        Set of target types to attempt casting to.
        
    Returns
    -------
    object
        The successfully cast value if conversion succeeds, otherwise the
        original value unchanged. Supported conversions include int, float,
        bool, and str types.
    """
    if not target_types:
        return value  # Nothing to do

    # Normalise set for quick lookup
    simple_types = {int, float, bool, str}
    targets = target_types & simple_types

    # Helper lambdas
    def _try_int(v):
        return int(v) if isinstance(v, str) and v.isdigit() else v

    def _try_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return v

    def _try_bool(v):
        if isinstance(v, str):
            if v.lower() in {"true", "false"}:
                return v.lower() == "true"
        return v

    for t in targets:
        if t is int:
            casted = _try_int(value)
            if isinstance(casted, int):
                return casted
        elif t is float:
            casted = _try_float(value)
            if isinstance(casted, float):
                return casted
        elif t is bool:
            casted = _try_bool(value)
            if isinstance(casted, bool):
                return casted
        elif t is str:
            # Always possible
            return str(value)

    return value  # Fallback


def _values_match(meta_val, filter_val) -> bool:
    """Return True if *meta_val* satisfies *filter_val* condition.
    
    Parameters
    ----------
    meta_val : object
        The metadata value to check.
    filter_val : object
        The filter condition to match against. Can be a single value or
        an iterable of values for membership testing.
        
    Returns
    -------
    bool
        True if meta_val matches the filter_val condition, False otherwise.
        For iterable filter_val (except str/bytes), returns True if meta_val
        matches any element. Otherwise performs direct equality or string
        comparison.
    """
    # If filter_val is iterable (but not str/bytes) treat as membership set
    if isinstance(filter_val, (list, tuple, set)):
        return any(_values_match(meta_val, fv) for fv in filter_val)

    # Direct equality if same type
    if type(meta_val) is type(filter_val):
        return meta_val == filter_val

    # Fallback to string comparison
    return str(meta_val) == str(filter_val)


def filter_by_metadata(items, meta_filter=None):
    """Filter a collection of items by metadata.

    Parameters
    ----------
    items : Iterable
        Iterable of elements. Each element can be:
          * (text, metadata) tuple
          * object with a ``metadata`` attribute
          * plain dict of metadata
          * raw string (kept irrespective of filter)
    meta_filter : Mapping | None
        Mapping of key -> value OR key -> iterable(values). Logical *AND*
        across keys.

    Returns
    -------
    list
        Items that satisfy *meta_filter*.
    """

    if not meta_filter:
        return list(items)

    field_type_map = _build_field_type_map()
    filtered = []

    for item in items:
        # Extract metadata dict depending on representation
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], dict):
            meta = item[1]
        elif hasattr(item, "metadata") and isinstance(item.metadata, dict):
            meta = item.metadata
        elif isinstance(item, dict):
            meta = item
        else:
            # For strings or unknown types, keep by default (not filtered out)
            filtered.append(item)
            continue

        # Evaluate all filter conditions
        keep = True
        for key, desired in meta_filter.items():
            if key not in meta:
                keep = False
                break

            meta_val = meta[key]
            expected_types = field_type_map.get(key, set())

            # Best-effort cast of *desired* to expected type(s)
            if isinstance(desired, Iterable) and not isinstance(desired, (str, bytes)):
                casted_desired = [
                    _safe_cast(v, expected_types) for v in desired
                ]
            else:
                casted_desired = _safe_cast(desired, expected_types)

            if not _values_match(meta_val, casted_desired):
                keep = False
                break

        if keep:
            filtered.append(item)

    return filtered


def collect_metadata_stats(metadatas):
    """Aggregate unique metadata values for facet filtering.

    Parameters
    ----------
    metadatas : list[dict]
        List of metadata dictionaries (one per text chunk).

    Returns
    -------
    dict[str, list]
        Mapping of metadata key to **sorted** list of unique values (as strings).  
        Only keys discovered in the provided metadata are included. Returns an
        empty dict when no metadata is provided so downstream UI can omit facets.
    """
    if not metadatas:
        return {}

    # Prepare accumulator
    acc: defaultdict[str, set] = defaultdict(set)

    # Iterate over provided metadata dictionaries
    for meta in metadatas:
        if not isinstance(meta, dict):
            continue
        for key, value in meta.items():
            if value is None:
                continue
            # Normalise to a set of hashable representations
            if isinstance(value, (list, set, tuple)):
                for v in value:
                    if v is not None:
                        acc[key].add(str(v))
            else:
                try:
                    acc[key].add(str(value))
                except Exception:
                    acc[key].add(repr(value))

    # Convert sets to sorted lists for deterministic ordering
    return {k: sorted(values) for k, values in acc.items()}


def humanize_datetime(dt: datetime) -> str:
    """
    Converts a datetime object to a human-readable string.

    Example:
        2025-06-17T15:42:00Z -> "June 17, 2025 at 15:42 UTC"

    Parameters
    ----------
    dt : datetime
        The datetime object to format.

    Returns
    -------
    str
        A human-readable string representation.
    """
    if not dt:
        return "N/A"
    return dt.strftime("%B %d, %Y at %H:%M")


def add_leading_space_if_needed(s: str) -> str:
    """Add a leading space to a non-empty string if it does not already start with one.

    Parameters
    ----------
    s : str
        The input string to check.

    Returns
    -------
    str
        The original string with a leading space added if it did not already have one.
    """
    if s and not s[0].isspace():
        return " " + s
    return s


# ---------------------------------------------------------------------------
# Metadata helper: preserve original upload attributes that are lost when we
# copy the file to a temporary location.  This augments the metadata produced
# by `extract_metadata()` so facets like `file_path` and timestamps still
# reflect the user-provided file rather than the temp file on disk.
# ---------------------------------------------------------------------------


def _patch_uploaded_metadata(original_meta: dict | None, uploaded_file) -> dict:
    """Return a copy of *original_meta* extended with fields from *uploaded_file*.

    Parameters
    ----------
    original_meta : dict | None
        Metadata returned by `extract_metadata()` (may be empty).
    uploaded_file : streamlit.runtime.uploaded_file_manager.UploadedFile
        The object returned by `st.file_uploader`.
        
    Returns
    -------
    dict
        Enhanced metadata dictionary containing original metadata plus additional
        fields extracted from the uploaded file including file_path, file_name,
        file_extension, size, mime_type, and timestamp fields (last_modified_time,
        creation_time, last_accessed_time). Preserves original upload attributes
        that would otherwise be lost when copying to temporary locations.
    """
    from datetime import datetime

    meta = original_meta.copy() if isinstance(original_meta, dict) else {}

    # Basic path/name information from the browser upload
    meta["file_path"] = uploaded_file.name  # original filename as path substitute
    meta["file_name"] = os.path.basename(uploaded_file.name)
    meta["file_extension"] = os.path.splitext(uploaded_file.name)[1]

    # Size (bytes) & MIME type if available
    if getattr(uploaded_file, "size", None) is not None:
        meta["size"] = uploaded_file.size

    if getattr(uploaded_file, "type", None):
        meta["mime_type"] = uploaded_file.type

    # Always overwrite time-related fields to avoid temp-file timestamps.
    ts_ms = getattr(uploaded_file, "last_modified", None)
    if ts_ms is not None:
        dt = datetime.fromtimestamp(ts_ms / 1000)
    else:
        dt = None  # original timestamp unavailable

    meta["last_modified_time"] = dt
    meta["creation_time"] = dt
    meta["last_accessed_time"] = dt

    return meta
