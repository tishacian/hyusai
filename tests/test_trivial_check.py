import pytest

from src.system_prompts import SystemPromptLangs
from src.trivial_check import is_trivial_question


# Replicates the example test cases originally found in `src/router.py`.
@pytest.mark.parametrize(
    "input_text, expected, language",
    [
        # English trivial cases
        ("hello", True, SystemPromptLangs.EN),
        ("hi", True, SystemPromptLangs.EN),
        ("thank you", True, SystemPromptLangs.EN),
        ("thanks", True, SystemPromptLangs.EN),
        ("good morning", True, SystemPromptLangs.EN),
        ("bye", True, SystemPromptLangs.EN),
        ("", True, SystemPromptLangs.EN),  # Empty is trivial
        # English non-trivial cases
        ("What is the weather today?", False, SystemPromptLangs.EN),
        ("Explain quantum mechanics", False, SystemPromptLangs.EN),
        ("Calculate the derivative of x^2", False, SystemPromptLangs.EN),
        ("hello, what is photosynthesis?", False, SystemPromptLangs.EN),  # Mixed case
        # French trivial cases
        ("bonjour", True, SystemPromptLangs.FR),
        ("salut", True, SystemPromptLangs.FR),
        ("merci", True, SystemPromptLangs.FR),
        ("merci beaucoup", True, SystemPromptLangs.FR),
        ("au revoir", True, SystemPromptLangs.FR),
        ("bonne journée", True, SystemPromptLangs.FR),
        # French non-trivial cases
        ("Quel temps fait-il aujourd'hui?", False, SystemPromptLangs.FR),
        ("Expliquez la mécanique quantique", False, SystemPromptLangs.FR),
        ("Calculez la dérivée de x^2", False, SystemPromptLangs.FR),
        ("bonjour, qu'est-ce que la photosynthèse?", False, SystemPromptLangs.FR),
    ],
)
def test_is_trivial_question(
    input_text: str, expected: bool, language: SystemPromptLangs
):
    """Validate `is_trivial_question` across multiple languages and scenarios."""
    assert is_trivial_question(input_text, language) == expected
