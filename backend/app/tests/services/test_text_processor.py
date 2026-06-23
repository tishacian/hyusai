"""Tests for TextProcessor.clean_text HTML-stripping behaviour.

Regression coverage for an ingestion bug where stripped HTML glued a tag to the
next word (e.g. "PUMP<b><br>URACA" -> "PUMP<b br>URACA"), so the brand token
"URACA" was never emitted standalone and the multilingual content full-text
index (which does not split on ">") missed it in the cross-project inventory
facet.
"""
import pytest

from app.services.document_parser.text_processor import TextProcessor


def _tokens(text: str) -> list[str]:
    return (text or "").lower().split()


@pytest.mark.parametrize(
    "raw",
    [
        "PUMP<b><br>URACA HP pumps for high pressure cleaning",
        "PUMP <b><br>URACA HP pumps for high pressure cleaning",
        "<p>PUMP</p><b><br>URACA HP pumps</b> for cleaning duty",
        "HP PUMP<br>URACA <br/>model <br >X serie pumps",
        "<table><tr><td>Pump</td><td>URACA</td></tr></table> high pressure",
        '<font color="red">URACA</font> HP pumps for cleaning duty',
    ],
)
def test_html_tags_do_not_glue_adjacent_tokens(raw):
    """Any <tag>word must clean to a standalone, unglued word token."""
    cleaned = TextProcessor.clean_text(raw)
    tokens = _tokens(cleaned)
    assert "uraca" in tokens, f"URACA not standalone in {cleaned!r}"
    # The remnant gluing patterns must be gone entirely.
    assert "br>uraca" not in cleaned.lower()
    assert "<b" not in cleaned.lower()
    assert "br>" not in cleaned.lower()


def test_spaced_inequalities_are_preserved():
    """'<' and '>' used as math/comparisons must survive (not treated as tags)."""
    raw = "flow rate < 5 m3/h and pressure > 100 bar at the inlet manifold"
    cleaned = TextProcessor.clean_text(raw)
    assert "< 5" in cleaned
    assert "> 100" in cleaned


def test_tags_replaced_with_separator_not_empty_string():
    """Tag removal inserts a separator so neighbouring words stay distinct."""
    cleaned = TextProcessor.clean_text("first<br>second<br>third paragraph text")
    tokens = _tokens(cleaned)
    assert {"first", "second", "third"}.issubset(set(tokens))
    assert "firstsecond" not in cleaned.lower()
