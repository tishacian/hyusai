"""The catalog levers become readable and writable, under one admin gate.

``workspace.settings.catalog`` decided how much of the registry a workspace
browsed and had no surface at all. Reading it is a member's business; changing
it is an admin's, and the boundary is `skill.admin` so it moves with the rest
of the catalog when that action is promoted out of compat.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import catalog_curation
from app.models.capability import Capability
from app.models.skill import Skill
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


def _client(db, workspace, user) -> TestClient:
    app = FastAPI()
    app.include_router(catalog_curation.router, prefix="/catalog")
    app.dependency_overrides[catalog_curation.get_current_workspace] = lambda: workspace
    app.dependency_overrides[catalog_curation.get_current_user] = lambda: user
    app.dependency_overrides[catalog_curation.get_db] = lambda: db
    return TestClient(app)


def _seed(db, *, role_template: str = "workspace_admin", settings: dict | None = None):
    workspace = Workspace(
        id="ws-curation",
        slug="curation",
        name="Curation",
        settings=settings if settings is not None else {"family": "andritz"},
    )
    user = User(id="curation-user", username="curation-user")
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="member",
        role_template=role_template,
    )
    universal_skill = Skill(
        id="skill-universal",
        slug="expert_answer_v1",
        name="Expert answer",
        category="Analysis",
    )
    government_skill = Skill(
        id="skill-government",
        slug="mission_command_v1",
        name="Mission command",
        category="Orchestration",
    )
    unclaimed_skill = Skill(
        id="skill-unclaimed",
        slug="causal_drill_v1",
        name="Causal drill",
        category="Analysis",
    )
    db.add_all(
        [
            workspace,
            user,
            member,
            universal_skill,
            government_skill,
            unclaimed_skill,
            Capability(
                id="cap-universal",
                slug="expert_capture",
                name="Expert capture",
                tier="universal",
                skill_ids=[universal_skill.id],
            ),
            Capability(
                id="cap-government",
                slug="aya_voice",
                name="Aya voice",
                tier="industry",
                industry="government",
                skill_ids=[government_skill.id],
            ),
        ]
    )
    db.commit()
    return workspace, user


def test_the_report_names_the_lever_behind_every_exclusion(db_session):
    workspace, user = _seed(db_session)

    payload = _client(db_session, workspace, user).get("/catalog/curation").json()

    assert payload["summary"] == {
        "total": 3,
        "visible": 1,
        "filtered": 2,
        # The two exclusions need different fixes and now say so.
        "filtered_reasons": {"industry_not_allowed": 1, "unclaimed": 1},
    }
    assert [(gap["lever"], gap["key"], gap["skills"]) for gap in payload["gaps"]] == [
        ("industry", "government", 1),
        ("unclaimed", "", 1),
    ]
    assert payload["policy"]["allowed_industries_source"] == "inferred"
    assert payload["editable"] is True
    by_slug = {row["slug"]: row for row in payload["capabilities"]}
    assert by_slug["aya_voice"]["reason"] == "industry_not_allowed"
    assert by_slug["expert_capture"]["visible"] is True


def test_allowing_an_industry_closes_its_gap(db_session):
    """The lever the report ranked first must actually be the lever."""

    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    payload = client.patch(
        "/catalog/curation",
        json={"allowed_industries": ["Government"]},
    ).json()

    assert payload["summary"]["visible"] == 2
    assert [gap["lever"] for gap in payload["gaps"]] == ["unclaimed"]
    assert payload["policy"]["allowed_industries"] == ["government"]
    assert payload["policy"]["allowed_industries_source"] == "configured"
    assert workspace.settings["catalog"]["allowed_industries"] == ["government"]
    # The escape hatch still reaches what no capability claims.
    assert client.patch(
        "/catalog/curation",
        json={"enabled_skills": ["causal_drill_v1"]},
    ).json()["summary"]["visible"] == 3


def test_stating_no_industry_is_persisted_rather_than_inferred_back(db_session):
    workspace, user = _seed(
        db_session,
        settings={"family": "sentinel_ci", "catalog": {"allowed_industries": ["government"]}},
    )

    payload = _client(db_session, workspace, user).patch(
        "/catalog/curation",
        json={"allowed_industries": []},
    ).json()

    assert payload["policy"]["allowed_industries"] == []
    assert payload["policy"]["allowed_industries_source"] == "configured"
    assert payload["summary"]["visible"] == 1


def test_a_write_preserves_the_settings_it_was_not_asked_to_change(db_session):
    workspace, user = _seed(
        db_session,
        settings={
            "family": "andritz",
            "apps": {"enabled": ["rpa_bridge"]},
            "catalog": {"enabled_skills": ["rpa_dispatch_v1"], "note": "kept"},
        },
    )

    _client(db_session, workspace, user).patch(
        "/catalog/curation",
        json={"hidden_skills": ["expert_answer_v1"]},
    )

    catalog = workspace.settings["catalog"]
    assert catalog["hidden_skills"] == ["expert_answer_v1"]
    assert catalog["enabled_skills"] == ["rpa_dispatch_v1"]
    assert catalog["note"] == "kept"
    assert workspace.settings["apps"] == {"enabled": ["rpa_bridge"]}


def test_a_null_lever_is_not_read_as_an_instruction_to_clear_it(db_session):
    workspace, user = _seed(
        db_session,
        settings={"catalog": {"allowed_industries": ["government"], "show_universal": True}},
    )

    payload = _client(db_session, workspace, user).patch(
        "/catalog/curation",
        json={"allowed_industries": None, "show_universal": None, "hidden_skills": ["retired_v1"]},
    ).json()

    assert payload["policy"]["allowed_industries"] == ["government"]
    assert payload["policy"]["show_universal"] is True
    assert payload["policy"]["hidden_skills"] == ["retired_v1"]


def test_a_legacy_capability_catalog_is_carried_over_not_dropped(db_session):
    """The resolver prefers ``catalog`` once it exists, so writing a fresh blob
    would silently discard the policy this surface is editing."""

    workspace, user = _seed(
        db_session,
        settings={"capability_catalog": {"enabled_capabilities": ["aya_voice"]}},
    )

    payload = _client(db_session, workspace, user).patch(
        "/catalog/curation",
        json={"show_universal": False},
    ).json()

    assert workspace.settings["catalog"]["enabled_capabilities"] == ["aya_voice"]
    assert payload["policy"]["enabled_capabilities"] == ["aya_voice"]
    assert payload["policy"]["show_universal"] is False


def test_a_workspace_app_side_effect_is_attributed_to_the_app(db_session):
    """Enabling a wired app writes into the catalog policy. Nothing told the
    admin that, so the override read as deliberate curation."""

    workspace, user = _seed(
        db_session,
        settings={
            "family": "andritz",
            "apps": {"enabled": ["rpa_bridge"]},
            "catalog": {"enabled_skills": ["rpa_dispatch_v1", "expert_answer_v1"]},
        },
    )
    db_session.add(Skill(id="skill-rpa", slug="rpa_dispatch_v1", name="RPA dispatch"))
    db_session.commit()

    payload = _client(db_session, workspace, user).get("/catalog/curation").json()

    assert [
        (item["slug"], item["status"], item["source"]) for item in payload["overrides"]
    ] == [
        # Already carried by a visible capability: the override decides nothing.
        ("expert_answer_v1", "redundant", "admin"),
        ("rpa_dispatch_v1", "effective", "app:rpa_bridge"),
    ]

    # Same slug, app switched off: curation is now the only explanation for it,
    # and attributing it to the app would invite removing it from the wrong screen.
    workspace.settings = {**workspace.settings, "apps": {"enabled": []}}
    db_session.commit()
    sources = {
        item["slug"]: item["source"]
        for item in _client(db_session, workspace, user).get("/catalog/curation").json()["overrides"]
    }
    assert sources["rpa_dispatch_v1"] == "admin"


def test_a_member_reads_the_report_but_cannot_change_it(db_session):
    workspace, user = _seed(db_session, role_template="workspace_contributor")
    client = _client(db_session, workspace, user)

    report = client.get("/catalog/curation")
    write = client.patch("/catalog/curation", json={"show_universal": False})

    assert report.status_code == 200
    assert report.json()["editable"] is False
    assert write.status_code == 403
    assert write.json()["detail"]["code"] == "WORKSPACE_PERMISSION_DENIED"
    assert workspace.settings.get("catalog") is None
