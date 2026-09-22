"""OpenAI Realtime follows the per-workspace flag like every other capability.

It was the last per-customer capability still read from a raw global slug list,
so a workspace could not opt in or out through its own settings. The list stays
as the fallback, so nothing changes until a workspace sets the flag.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services.voice_runtime import _realtime_allowed


@pytest.fixture(autouse=True)
def _listed(monkeypatch):
    monkeypatch.setattr(settings, "openai_realtime_enabled_workspace_slugs", "andritz")


def _ws(slug, features=None):
    return SimpleNamespace(slug=slug, settings={"features": features} if features is not None else {})


def test_the_older_call_shapes_keep_their_exact_meaning():
    assert _realtime_allowed(None, None) is True  # no tenant, no tenant gate
    assert _realtime_allowed(None, "andritz") is True
    assert _realtime_allowed(None, "acme") is False


def test_without_a_flag_the_global_list_still_decides():
    assert _realtime_allowed(_ws("andritz"), "andritz") is True
    assert _realtime_allowed(_ws("acme"), "acme") is False


def test_a_workspace_can_now_opt_in_through_its_own_settings():
    assert _realtime_allowed(_ws("acme", {"openai_realtime": True}), "acme") is True


def test_and_can_opt_out_even_if_the_list_names_it():
    assert _realtime_allowed(_ws("andritz", {"openai_realtime": False}), "andritz") is False
