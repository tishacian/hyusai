import os
import string
from typing import Set
import pathlib, csv
import re

# -----------------------------
# Trivial-input detection logic
# -----------------------------
# A message is considered *trivial* when both conditions are met:
#   1. Its length (after stripping whitespace) is at most `TRIVIAL_LEN`.
#   2. It contains at least one token/phrase from `TRIVIAL_ENGLISH_VOCABULARY` (case-insensitive).
#
# These heuristics come from the NP-419 mitigation plan (see bug-np-419.md).

TRIVIAL_LEN: int = 30

TRIVIAL_ENGLISH_VOCABULARY: Set[str] = {
    "hello",
    "hi",
    "hey",
    "yo",
    "sup",
    "good morning",
    "good afternoon",
    "good evening",
    "howdy",
    "greetings",
    "how are you",
    "how are ya",
    "thanks",
    "thank you",
    "thx",
    "ty",
    "merci",
    "gracias",
    "cool, thanks",
    "ok, thanks",
    "great, thanks",
    "morning",
    "evening",
    "good noon",
    "good eve",
    "gm",
    "gn",
    "thank u",
    "thanx",
    "thnx",
    "thanks a lot",
    "thank you so much",
    "appreciate it",
    "much obliged",
    "cheers",
    "cheers mate",
    "ta",
    "hiya",
    "wassup",
    "thanks a ton",
    "how are you doing today",
    "good night",
    "night",
    "nite",
    "sleep well",
    "sweet dreams",
    "see ya",
    "see you",
    "bye",
    "goodbye",
    "farewell",
    "catch ya later",
    "later",
    "peace",
    "peace out",
    "take care",
    "have a good one",
    "until next time",
    "ttyl",
    "brb",
    "be right back",
    "one sec",
    "hold on",
    "wait up",
    "just a minute",
    "give me a sec",
    "hang tight",
    "bear with me",
    "sorry",
    "my bad",
    "oops",
    "whoops",
    "my apologies",
    "excuse me",
    "pardon",
    "forgive me",
    "apologies",
    "no worries",
    "no problem",
    "dont mention it",
    "you're welcome",
    "anytime",
    "my pleasure",
    "glad to help",
    "happy to help",
    "sure thing",
    "of course",
    "absolutely",
    "definitely",
    "for sure",
    "yep",
    "yeah",
    "yes",
    "yup",
    "uh huh",
    "right on",
    "sounds good",
    "cool",
    "awesome",
    "great",
    "perfect",
    "excellent",
    "fantastic",
    "wonderful",
    "amazing",
    "brilliant",
    "nice",
    "sweet",
    "rad",
    "sick",
    "dope",
    "lit",
    "fire",
    "okay",
    "ok",
    "alright",
    "fine",
    "not bad",
    "decent",
    "fair enough",
    "i see",
    "got it",
    "understood",
    "makes sense",
    "right",
    "correct",
    "exactly",
    "precisely",
    "bingo",
    "that's it",
    "you got it",
    "spot on",
    "on point",
    "nailed it",
    "well done",
    "good job",
    "nice work",
    "keep it up",
    "way to go",
    "congrats",
    "congratulations",
    "well played",
    "impressive",
    "goodnight",
    "adios",
    "ciao",
    "au revoir",
    "sayonara",
    "cheerio",
    "toodles",
    "so long",
    "talk soon",
    "solid",
    "tight",
    "clean",
    "smooth",
    "slick",
    "fresh",
    "crisp",
    "sharp",
    "on fleek",
    "legit",
    "real",
    "true",
    "facts",
    "word",
    "preach",
    "tell me about it",
    "you said it",
    "couldnt agree more",
    "totally",
    "completely",
    "entirely",
    "wholly",
    "utterly",
    "fully",
    "100%",
    "all the way",
    "through and through",
    "to the core",
    "without a doubt",
    "no question",
    "hands down",
    "by far",
    "easily",
    "clearly",
    "obviously",
    "certainly",
    "surely",
    "undoubtedly",
    "unquestionably",
    "indubitably",
    "beyond doubt",
    "without question",
    "no doubt about it",
    "thats for sure",
    "you bet",
    "you betcha",
    "indeed",
    "quite so",
    "rather",
    "quite",
    "fairly",
    "pretty",
    "somewhat",
    "kind of",
    "sort of",
    "more or less",
    "roughly",
    "approximately",
    "about",
    "around",
    "nearly",
    "almost",
    "close to",
    "just about",
    "practically",
    "virtually",
    "essentially",
    "basically",
    "fundamentally",
    "primarily",
    "mainly",
    "mostly",
    "largely",
    "generally",
    "typically",
    "usually",
    "normally",
    "ordinarily",
    "good",
    "not bad at all",
    "couldnt agree more",
    "100%",
    "thats for sure",
    "commonly",
    "frequently",
    "often",
    "regularly",
    "consistently",
    "constantly",
    "continually",
    "always",
    "forever",
    "eternally",
    "indefinitely",
    "permanently",
    "endlessly",
    "never",
    "not ever",
    "at no time",
    "under no circumstances",
    "by no means",
    "not at all",
    "not in the least",
    "not one bit",
    "not a chance",
    "no way",
    "forget it",
    "dream on",
    "in your dreams",
    "fat chance",
    "when pigs fly",
    "over my dead body",
    "not if i can help it",
    "not on my watch",
    "not happening",
    "aint gonna happen",
    "nope",
    "nah",
    "negative",
    "nada",
    "zilch",
    "zero",
    "nothing",
    "none",
    "neither",
    "nor",
    "however",
    "nevertheless",
    "nonetheless",
    "still",
    "yet",
    "though",
    "although",
    "even though",
    "despite",
    "in spite of",
    "regardless",
    "anyway",
    "anyhow",
    "in any case",
    "at any rate",
    "either way",
    "one way or another",
    "somehow",
    "someway",
    "whatever",
    "whenever",
    "wherever",
    "whoever",
    "whomever",
    "whichever",
    "why not",
    "sure why not",
    "why not indeed",
    "indeed why not",
    "what the heck",
    "what the hell",
    "why the hell not",
    "might as well",
    "could be worse",
    "better than nothing",
    "something is better than nothing",
    "half a loaf is better than none",
    "beggars cant be choosers",
    "take what you can get",
    "it is what it is",
    "such is life",
    "thats life",
    "life goes on",
    "cest la vie",
    "what can you do",
    "what are you gonna do",
    "whatcha gonna do",
    "whaddya gonna do",
    "what else is new",
    "same old same old",
    "nothing new under the sun",
    "been there done that",
    "story of my life",
    "tell me something i dont know",
    "no kidding",
    "you dont say",
    "really",
    "seriously",
    "are you serious",
    "are you kidding me",
    "youve got to be kidding",
    "you must be joking",
    "pull the other one",
    "get out of here",
    "get outta here",
    "no way jose",
    "come on",
    "come off it",
    "give me a break",
    "cut it out",
    "knock it off",
    "stop it",
    "quit it",
    "enough",
    "thats enough",
    "im done",
    "im out",
    "i gotta go",
    "gotta run",
}


# Pre-compile regex patterns for efficiency (whole-word matching, case-insensitive)
RE_BOUNDARY = {
    kw: re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in TRIVIAL_ENGLISH_VOCABULARY
}

def _normalize(text: str) -> str:
    """Lower-case and strip punctuation for keyword matching."""
    lowered = text.lower().strip()
    # Remove leading/trailing punctuation (commas, dots, etc.) to reduce noise
    return lowered.strip(string.punctuation + "\t\n\r ")


def is_trivial(message: str) -> bool:
    """Return True if *message* should bypass retrieval according to heuristics."""

    if not message:
        return True  # Empty input is definitely trivial

    norm = _normalize(message)

    # Length gate first
    if len(norm) > TRIVIAL_LEN:
        return False

    # Full-phrase match (covers multi-word greetings like "thank you")
    if norm in TRIVIAL_ENGLISH_VOCABULARY:
        return True

    # Whole-word greeting detection (at least one keyword present)
    if not any(pat.search(norm) for pat in RE_BOUNDARY.values()):
        return False  # no greeting words at all

    # Remove greeting tokens and see what's left
    words = norm.split()
    leftover = [w for w in words if w not in TRIVIAL_ENGLISH_VOCABULARY]

    # If there's a question mark or at least 2 non-greeting words, it's likely a real query
    if "?" in norm or len(leftover) >= 2:
        return False

    return True


# ---------------------------------------------------------------------------
# Self-contained basic tests (run: `python src/router.py` to validate locally)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
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