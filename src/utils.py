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
from functools import lru_cache
from pathlib import Path

import torch

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

try:
    from nltk.corpus import stopwords

    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False

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


def download_nltk_data():
    """Download NLTK data if not already available."""
    import nltk

    nltk.download("punkt", quiet=True)
    nltk.download("punkt_tab", quiet=True)
    nltk.download("wordnet", quiet=True)
    nltk.download("stopwords", quiet=True)
    nltk.download("averaged_perceptron_tagger", quiet=True)


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
