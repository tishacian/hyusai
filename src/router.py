import string
import pathlib, csv
import re
from globalvariables import TRIVIAL_ENGLISH_VOCABULARY, TRIVIAL_LEN
# -----------------------------
# Trivial-input detection logic
# -----------------------------
# A message is considered *trivial* when both conditions are met:
#   1. Its length (after stripping whitespace) is at most `TRIVIAL_LEN`.
#   2. It contains at least one token/phrase from `TRIVIAL_ENGLISH_VOCABULARY` (case-insensitive).



# Pre-compile regex patterns for efficiency (whole-word matching, case-insensitive)
RE_BOUNDARY = {
    kw: re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in TRIVIAL_ENGLISH_VOCABULARY
}

PUNCT_TABLE = str.maketrans({ch: " " for ch in string.punctuation})

def _normalize(text: str) -> str:
    """Lower-case, remove all punctuation, and collapse whitespace."""
    text = text.lower().translate(PUNCT_TABLE)
    # Collapse multiple spaces into one and strip leading/trailing whitespace
    return " ".join(text.split())


def is_trivial_question(message: str) -> bool:
    """Return True if a message is considered *trivial*.

    A message is trivial when it is short and mainly composed of greeting or
    courtesy keywords.  The decision flow is expressed as a single
    if/elif/else chain to keep the cognitive-complexity of the function low
    while preserving the original semantics.
    """

    if not message:
        # Empty input is definitely trivial
        return True

    norm = _normalize(message)
    words = norm.split()

    if len(norm) > TRIVIAL_LEN:
        # Too long to be considered a quick greeting
        return False
    elif len(words) < 2:
        # Single-word messages like "hi"/"ok" are trivial
        return True
    elif norm in TRIVIAL_ENGLISH_VOCABULARY:
        # Exact keyword/phrase match (e.g. "thank you")
        return True
    elif not any(pat.search(norm) for pat in RE_BOUNDARY.values()):
        # No greeting tokens at all → not trivial
        return False
    else:
        # Remove greeting tokens and inspect the leftover
        leftover = [w for w in words if w not in TRIVIAL_ENGLISH_VOCABULARY]
        # Fewer than two non-greeting words → treat as trivial
        return len(leftover) < 2


# ---------------------------------------------------------------------------
# Self-contained basic tests (run: `python src/router.py` to validate locally)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # print(is_trivial("you're welcome"))
    # exit()
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
        result = is_trivial(text)
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