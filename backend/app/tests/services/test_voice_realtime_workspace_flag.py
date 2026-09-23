"""OpenAI Realtime follows the per-workspace flag, and nothing else.

It was the last per-customer capability read from a raw global slug list.
Migration 111 froze that list onto the workspaces it named, so the workspace's
own ``features.openai_realtime`` is now the only answer.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.voice_runtime import _realtime_allowed


def _ws(slug, features=None):
    return SimpleNamespace(slug=slug, settings={"features": features} if features is not None else {})


def test_no_tenant_is_still_not_gated():
    assert _realtime_allowed(None, None) is True


def test_a_bare_slug_no_longer_answers():
    """Without the workspace there is no flag to read, so it is refused."""

    assert _realtime_allowed(None, "andritz") is False
    assert _realtime_allowed(None, "acme") is False


def test_the_slug_that_used_to_be_listed_is_not_special():
    assert _realtime_allowed(_ws("andritz"), "andritz") is False


def test_a_workspace_opts_in_and_out_through_its_own_settings():
    assert _realtime_allowed(_ws("acme", {"openai_realtime": True}), "acme") is True
    assert _realtime_allowed(_ws("andritz", {"openai_realtime": False}), "andritz") is False
