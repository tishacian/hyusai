import logging
import os
import pickle
from pathlib import Path

import nltk
from nltk.corpus import stopwords

from configurations.config import Config


def download_nltk_data(download_dir: str | None = None, quiet: bool = True):
    nltk.download("punkt_tab", download_dir=download_dir, quiet=quiet)
    nltk.download("wordnet", download_dir=download_dir, quiet=quiet)
    nltk.download("stopwords", download_dir=download_dir, quiet=quiet)
    nltk.download("averaged_perceptron_tagger", download_dir=download_dir, quiet=quiet)


def locate_and_set_tessdata_prefix():
    """Locate tessdata directory and set TESSDATA_PREFIX environment variable."""
    possible_paths = [
        Config.get().ressources.tessdata,
        os.path.expanduser("~/.local/share/tessdata"),
        "/usr/share/tesseract-ocr/5/tessdata/",
    ]
    for path in possible_paths:
        if os.path.isdir(path) and any(
            f.endswith(".traineddata") for f in os.listdir(path)
        ):
            os.environ["TESSDATA_PREFIX"] = path
            logging.info(f"Set TESSDATA_PREFIX to: {path}")
            return
    logging.warning("No valid tessdata directory found.")


def build_multilang_stopwords(
    target_dir: str, languages: list[str] | None = None
) -> set[str]:
    """Build a multilingual stopwords set and cache it to disk.

    Parameters
    ----------
    target_dir : str
        Directory to store the multilingual stopwords set.
    languages : list[str] | None
        List of languages to include, defaults to common languages.

    Returns
    -------
    set[str]
        The combined stopwords set, or None if creation fails.
    """
    if languages is None:
        languages = ["english", "french", "german", "italian", "russian"]

    target_path = Path(target_dir)
    target_path.mkdir(parents=True, exist_ok=True)
    file_path = target_path / "multilang_stopwords.pkl"

    combined_stopwords = set()
    for lang in languages:
        combined_stopwords.update(stopwords.words(lang))

    with open(file_path, "wb") as f:
        pickle.dump(combined_stopwords, f, protocol=pickle.HIGHEST_PROTOCOL)

    return combined_stopwords
