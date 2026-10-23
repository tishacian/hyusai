from app.services.decision_titles import display_title


def test_the_engine_prefix_is_not_shown_to_readers():
    assert display_title("HITL approval — Valider la résolution") == "Valider la résolution"
    assert display_title("Valider la résolution") == "Valider la résolution"
    # A title that would become empty stays as recorded.
    assert display_title("HITL approval — ") == "HITL approval — "
    assert display_title(None) is None
