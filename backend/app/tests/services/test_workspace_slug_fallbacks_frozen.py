"""The last slug lists are frozen onto workspaces, and new workspaces start governed.

Migration 111 writes what every per-feature slug list answered into the
workspace rows, so the runtime can stop reading the lists. The property that
matters is that no existing workspace changes its answer, while a workspace
created afterwards gets the safe default: IAM enforced.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from app.core.config import settings
from app.services.iam.config_service import is_iam_enforced_for_workspace
from app.services.livekit_service import LiveKitService
from app.services.voice_runtime import _realtime_allowed
from app.services.workspace_features import feature_enabled

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "111_freeze_workspace_slug_fallbacks.py"
)
ENV_VARS = (
    "IAM_ENFORCED_WORKSPACE_SLUGS",
    "OPENAI_REALTIME_ENABLED_WORKSPACE_SLUGS",
    "VOICE_REALTIME_STT_WORKSPACE_SLUGS",
)


@pytest.fixture(autouse=True)
def _no_list_in_the_environment(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setattr(settings, "iam_generic_engine", False)


def _ws(slug, workspace_settings=None):
    return SimpleNamespace(id=f"id-{slug}", slug=slug, settings=workspace_settings or {})


# --- the runtime rules -------------------------------------------------------


def test_a_new_workspace_starts_governed():
    assert is_iam_enforced_for_workspace(_ws("brand-new")) is True


def test_an_explicit_opt_out_is_honoured_and_the_global_switch_still_wins(monkeypatch):
    opted_out = _ws("nawa", {"features": {"iam_enforced": False}})
    assert is_iam_enforced_for_workspace(opted_out) is False

    monkeypatch.setattr(settings, "iam_generic_engine", True)
    assert is_iam_enforced_for_workspace(opted_out) is True


# --- the migration -------------------------------------------------------------


def _load_migration(monkeypatch, bind):
    spec = importlib.util.spec_from_file_location("migration_111_unit", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    sys.modules["migration_111_unit"] = module
    spec.loader.exec_module(module)

    class _Op:
        @staticmethod
        def get_bind():
            return bind

    monkeypatch.setattr(module, "op", _Op)
    return module


def _run(monkeypatch, rows, *, downgrade=False):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    workspaces = sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("slug", sa.String(length=100)),
        sa.Column("settings", sa.JSON()),
    )
    with engine.begin() as bind:
        metadata.create_all(bind)
        bind.execute(workspaces.insert(), rows)
        module = _load_migration(monkeypatch, bind)
        module.upgrade()
        if downgrade:
            module.downgrade()
        result = {
            r._mapping["id"]: (r._mapping["slug"], r._mapping["settings"])
            for r in bind.execute(
                sa.select(workspaces.c.id, workspaces.c.slug, workspaces.c.settings)
            )
        }
    return module, result


def _listed(value, default):
    return {
        item.strip().lower()
        for item in (value if value is not None else default).split(",")
        if item.strip()
    }


def _old_answers(slug, workspace_settings, env):
    """What the removed code answered, written out from the old sources."""

    raw = (workspace_settings or {}).get("features")
    features = raw if isinstance(raw, dict) else {}

    def old_opt_in(feature, listed):
        if feature in features:
            return bool(features[feature])
        return slug in listed

    stt_list = _listed(env.get("VOICE_REALTIME_STT_WORKSPACE_SLUGS"), "")
    stt_old = bool(not stt_list or slug in stt_list)
    return {
        "iam_enforced": old_opt_in(
            "iam_enforced", _listed(env.get("IAM_ENFORCED_WORKSPACE_SLUGS"), "andritz")
        ),
        "openai_realtime": old_opt_in(
            "openai_realtime",
            _listed(env.get("OPENAI_REALTIME_ENABLED_WORKSPACE_SLUGS"), "andritz"),
        ),
        "voice_realtime_stt": stt_old,
        "model_portal_beta": old_opt_in("model_portal_beta", {"agentium-showcase"}),
        "rpa_bridge": old_opt_in("rpa_bridge", {"agentium-showcase"}),
        "sap_hana_connector": old_opt_in("sap_hana_connector", {"agentium-showcase"}),
    }


def _new_answers(slug, workspace_settings, monkeypatch):
    workspace = _ws(slug, workspace_settings)
    monkeypatch.setattr(settings, "voice_realtime_stt_enabled", True)
    return {
        "iam_enforced": is_iam_enforced_for_workspace(workspace),
        "openai_realtime": _realtime_allowed(workspace, slug),
        "voice_realtime_stt": LiveKitService().realtime_stt_enabled(workspace),
        "model_portal_beta": feature_enabled(workspace, "model_portal_beta"),
        "rpa_bridge": feature_enabled(workspace, "rpa_bridge"),
        "sap_hana_connector": feature_enabled(workspace, "sap_hana_connector"),
    }


ROWS = [
    {"id": "w-andritz", "slug": "andritz", "settings": {}},
    {"id": "w-nawa", "slug": "nawa", "settings": {"mode": "builder"}},
    {
        "id": "w-showcase",
        "slug": "agentium-showcase",
        "settings": {"features": {"rpa_bridge": False}},
    },
    {
        "id": "w-decided",
        "slug": "acme",
        "settings": {"features": {"iam_enforced": True, "openai_realtime": True}},
    },
    {"id": "w-malformed", "slug": "legacy", "settings": {"features": ["not", "an", "object"]}},
    {"id": "w-null", "slug": "empty", "settings": None},
]


@pytest.mark.parametrize(
    "env",
    [
        {},
        {
            "IAM_ENFORCED_WORKSPACE_SLUGS": "nawa,andritz",
            "OPENAI_REALTIME_ENABLED_WORKSPACE_SLUGS": "",
        },
        {"VOICE_REALTIME_STT_WORKSPACE_SLUGS": "andritz"},
    ],
    ids=["shipped-defaults", "widened-iam-and-no-realtime", "stt-allowlist"],
)
def test_no_existing_workspace_changes_its_answer(monkeypatch, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    before = {row["id"]: _old_answers(row["slug"], row["settings"], env) for row in ROWS}

    _module, after_rows = _run(monkeypatch, ROWS)

    for row_id, (slug, workspace_settings) in after_rows.items():
        assert _new_answers(slug, workspace_settings, monkeypatch) == before[row_id], row_id


def test_explicit_decisions_are_left_alone_and_other_settings_survive(monkeypatch):
    module, rows = _run(monkeypatch, ROWS)

    assert rows["w-decided"][1] == {"features": {"iam_enforced": True, "openai_realtime": True}}
    assert rows["w-showcase"][1]["features"]["rpa_bridge"] is False
    assert rows["w-showcase"][1]["features"]["sap_hana_connector"] is True
    assert rows["w-nawa"][1]["mode"] == "builder"
    assert rows["w-nawa"][1]["features"] == {"iam_enforced": False}
    assert rows["w-andritz"][1]["features"] == {"iam_enforced": True, "openai_realtime": True}
    assert module.MARKER_KEY in rows["w-nawa"][1]


def test_the_downgrade_removes_exactly_what_it_wrote(monkeypatch):
    _module, rows = _run(monkeypatch, ROWS, downgrade=True)

    for row in ROWS:
        assert rows[row["id"]][1] == (row["settings"] if row["settings"] is not None else {}), row[
            "id"
        ]
