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





# ---------------------------------------------------------------------------
# Self-contained basic tests (run: `python src/router.py` to validate locally)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Test cases: (text, expected_result, language)
    test_cases = [
        # English trivial cases
        ("hello", True, InstructionLangs.EN),
        ("hi", True, InstructionLangs.EN),
        ("thank you", True, InstructionLangs.EN),
        ("thanks", True, InstructionLangs.EN),
        ("good morning", True, InstructionLangs.EN),
        ("bye", True, InstructionLangs.EN),
        ("", True, InstructionLangs.EN),  # Empty is trivial
        
        # English non-trivial cases  
        ("What is the weather today?", False, InstructionLangs.EN),
        ("Explain quantum mechanics", False, InstructionLangs.EN),
        ("Calculate the derivative of x^2", False, InstructionLangs.EN),
        ("hello, what is photosynthesis?", False, InstructionLangs.EN),  # Mixed case
        
        # French trivial cases
        ("bonjour", True, InstructionLangs.FR),
        ("salut", True, InstructionLangs.FR),
        ("merci", True, InstructionLangs.FR),
        ("merci beaucoup", True, InstructionLangs.FR),
        ("au revoir", True, InstructionLangs.FR),
        ("bonne journée", True, InstructionLangs.FR),
        
        # French non-trivial cases
        ("Quel temps fait-il aujourd'hui?", False, InstructionLangs.FR),
        ("Expliquez la mécanique quantique", False, InstructionLangs.FR),
        ("Calculez la dérivée de x^2", False, InstructionLangs.FR),
        ("bonjour, qu'est-ce que la photosynthèse?", False, InstructionLangs.FR),  # Mixed case
    ]
    
    print("Testing trivial question detection:")
    print("=" * 50)
    
    passed = 0
    failed = 0
    
    for text, expected, language in test_cases:
        result = is_trivial_question(text, language)
        status = "✓ PASS" if result == expected else "✗ FAIL"
        lang_code = "EN" if language == InstructionLangs.EN else "FR"
        
        print(f"[{lang_code}] {status} | '{text}' -> {result} (expected {expected})")
        
        if result == expected:
            passed += 1
        else:
            failed += 1
    
    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    print(f"Accuracy: {passed / (passed + failed) * 100:.1f}%") 