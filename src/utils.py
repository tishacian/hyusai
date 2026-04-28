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
from src.init_utils import build_multilang_stopwords
from src.system_prompts import (
    ALL_SYSTEM_PROMPT_PHRASES_TO_REMOVE,
    ALL_SYSTEM_PROMPT_SECTIONS_TO_REMOVE,
    DEFAULT_SYSTEM_PROMPT_LANG,
    SystemPromptLangs,
)

try:
    # import as to avoid unused import warning
    from nltk.corpus import stopwords as stopwords

    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False

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
        "/data/assets/",
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
            # Unknown model (e.g. OpenAI API models) — assume a large context window.
            logging.warning(
                "Unknown model name %r — defaulting max_model_len to 128k.", model_name
            )
            return 128 * 1024
    else:
        return max_model_len * 1024


# %% stopwords


def load_multilang_stopwords(target_dir: str) -> set[str]:
    """Load the multilingual stopwords set, or build it if missing.

    Parameters
    ----------
    target_dir : str
        Directory where the multilingual stopwords set is stored.

    Returns
    -------
    set[str]
        The loaded multilingual stopwords set.
    """
    file_path = Path(target_dir) / "multilang_stopwords.pkl"

    if file_path.exists():
        with file_path.open("rb") as f:
            return pickle.load(f)
    else:
        logging.info("Multilingual stopwords file not found, building new one.")
        return build_multilang_stopwords(target_dir)


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
