import string
import re
from src.globalvariables import TRIVIAL_ENGLISH_VOCABULARY, TRIVIAL_FRENCH_VOCABULARY, TRIVIAL_LEN
from src.reasoning_instructions import InstructionLangs, DEFAULT_INSTRUCTION_LANG
# -----------------------------
# Trivial-input detection logic
# -----------------------------
# A message is considered *trivial* when both conditions are met:
#   1. Its length (after stripping whitespace) is at most `TRIVIAL_LEN`.
#   2. It contains at least one token/phrase from the appropriate vocabulary (case-insensitive).

# Language-specific vocabularies
TRIVIAL_VOCABULARIES = {
    InstructionLangs.EN: TRIVIAL_ENGLISH_VOCABULARY,
    InstructionLangs.FR: TRIVIAL_FRENCH_VOCABULARY,
}

# Pre-compile regex patterns for efficiency (whole-word matching, case-insensitive)
# We'll build this dynamically based on the language
RE_BOUNDARY_CACHE = {}

def _get_regex_patterns(language: InstructionLangs):
    """Get or create regex patterns for the specified language"""
    if language not in RE_BOUNDARY_CACHE:
        vocabulary = TRIVIAL_VOCABULARIES[language]
        RE_BOUNDARY_CACHE[language] = {
            kw: re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in vocabulary
        }
    return RE_BOUNDARY_CACHE[language]

PUNCT_TABLE = str.maketrans({ch: " " for ch in string.punctuation})

def _normalize(text: str) -> str:
    """Lower-case, remove all punctuation, and collapse whitespace."""
    text = text.lower().translate(PUNCT_TABLE)
    # Collapse multiple spaces into one and strip leading/trailing whitespace
    return " ".join(text.split())


def is_trivial_question(message: str, language: InstructionLangs = DEFAULT_INSTRUCTION_LANG) -> bool:
    """Return True if a message is considered *trivial*.

    A message is trivial when it is short and mainly composed of greeting or
    courtesy keywords in the specified language.

    Parameters
    ----------
    message : str
        The message to analyze
    language : InstructionLangs, optional
        The language to use for trivial detection, by default DEFAULT_INSTRUCTION_LANG

    Returns
    -------
    bool
        True if the message is considered trivial
    """

    if not message:
        # Empty input is definitely trivial
        return True

    norm = _normalize(message)
    words = norm.split()
    
    # Get vocabulary and regex patterns for the specified language
    vocabulary = TRIVIAL_VOCABULARIES[language]
    re_patterns = _get_regex_patterns(language)

    if len(norm) > TRIVIAL_LEN:
        # Too long to be considered a quick greeting
        return False
    elif len(words) < 2:
        # Single-word messages like "hi"/"salut" are trivial
        return True
    elif norm in vocabulary:
        # Exact keyword/phrase match (e.g. "thank you"/"merci")
        return True
    elif not any(pat.search(norm) for pat in re_patterns.values()):
        # No greeting tokens at all → not trivial
        return False
    else:
        # Remove greeting tokens and inspect the leftover
        leftover = [w for w in words if w not in vocabulary]
        # Fewer than two non-greeting words → treat as trivial
        return len(leftover) < 2



