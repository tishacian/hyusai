import string
import pathlib, csv
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
    # Test both languages
    print("Testing English trivial detection:")
    print(f"'hello' -> {is_trivial_question('hello', InstructionLangs.EN)}")
    print(f"'thank you' -> {is_trivial_question('thank you', InstructionLangs.EN)}")
    print(f"'What is the weather today?' -> {is_trivial_question('What is the weather today?', InstructionLangs.EN)}")
    
    print("\nTesting French trivial detection:")
    print(f"'bonjour' -> {is_trivial_question('bonjour', InstructionLangs.FR)}")
    print(f"'merci beaucoup' -> {is_trivial_question('merci beaucoup', InstructionLangs.FR)}")
    french_question = "Quel temps fait-il aujourd'hui?"
    print(f"'{french_question}' -> {is_trivial_question(french_question, InstructionLangs.FR)}")
    
    # Continue with existing test logic...
    csv_path = pathlib.Path(__file__).parent / "test_questions_router_2.csv"

    tests = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            if len(row) == 1:
                # no expected label provided -> skip accuracy
                tests.append((row[0], None))
            else:
                question, label = row[0].strip(), row[1].strip()
                expected = label.lower() in {"t", "true", "1", "false", "f"}
                expected_bool = label.lower() in {"t", "true", "1"}
                tests.append((question, expected_bool))

    total = len(tests)
    failures = 0
    false_negatives = 0  # expected True, predicted False
    false_positives = 0  # expected False, predicted True
    misclassified = []
    unlabeled = 0
    for text, expected in tests:
        result = is_trivial_question(text, InstructionLangs.EN)  # Default to English for existing tests
        if expected is None:
            # just print prediction for unlabeled case
            print(f"{result}\t{text}")
            unlabeled += 1
            continue
        if result != expected:
            failures += 1
            misclassified.append((text, result, expected))
            if expected and not result:
                false_negatives += 1
            elif (not expected) and result:
                false_positives += 1

    labeled_total = total - unlabeled
    passed = labeled_total - failures
    accuracy = passed / labeled_total * 100 if labeled_total else 0.0

    true_cases = sum(1 for _, exp in tests if exp)
    false_cases = sum(1 for _, exp in tests if exp is not None and not exp)
    fn_percent = (false_negatives / true_cases * 100) if true_cases else 0.0
    fp_percent = (false_positives / false_cases * 100) if false_cases else 0.0

    print("\n----------------------")
    print(f"Total cases     : {total}")
    print(f"Labeled cases   : {labeled_total}")
    print(f"Passed          : {passed}")
    print(f"Failed          : {failures}")
    print(f"Accuracy        : {accuracy:.2f}%")
    print(f"False Negatives : {false_negatives}  ({fn_percent:.2f}% of TRUE cases)")
    print(f"False Positives : {false_positives}  ({fp_percent:.2f}% of FALSE cases)")

    if misclassified:
        print("\nMisclassified examples (input → predicted | expected):")
        for text, predicted, expected in misclassified:
            print(f"  - {text!r} → {predicted} | {expected}") 