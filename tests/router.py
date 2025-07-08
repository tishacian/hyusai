import pytest

from src.router import is_trivial_question
from src.reasoning_instructions import InstructionLangs


# Replicates the example test cases originally found in `src/router.py`.
@pytest.mark.parametrize(
    "input_text, expected, language",
    [
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
        ("bonjour, qu'est-ce que la photosynthèse?", False, InstructionLangs.FR),
    ],
)

def test_is_trivial_question(input_text: str, expected: bool, language: InstructionLangs):
    """Validate `is_trivial_question` across multiple languages and scenarios."""
    assert is_trivial_question(input_text, language) == expected 