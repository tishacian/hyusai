"""The Skill catalog must state its taxonomy and explain its own filtering.

The palette used to re-derive a product taxonomy from slugs with a frontend
regex, and a workspace routinely browsed half of the registry with no stated
reason. Both are catalog responsibilities: `category` is served, and every
row carries the rule that kept or dropped it.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import skills
from app.models.capability import Capability
from app.models.skill import Skill
from app.models.tabular import MLModel
from app.models.user import User
from app.models.workspace import Workspace
from app.services.skills_registry.seed import SEED_SKILLS, SKILL_CATEGORIES
from app.services.skills_registry.wrappers import _REGISTRY


def _client(db, workspace, user) -> TestClient:
    app = FastAPI()
    app.include_router(skills.router, prefix="/skills")
    app.dependency_overrides[skills.get_current_workspace] = lambda: workspace
    app.dependency_overrides[skills.get_current_user] = lambda: user
    app.dependency_overrides[skills.get_db] = lambda: db
    return TestClient(app)


def _seed(db):
    workspace = Workspace(id="ws-catalog", slug="catalog", name="Catalog", settings={})
    user = User(id="catalog-user", username="catalog-user")
    carried = Skill(
        id="skill-carried",
        slug="carried_v1",
        name="Carried",
        type="retrieval",
        category="Retrieval",
    )
    orphaned = Skill(
        id="skill-orphaned",
        slug="orphaned_v1",
        name="Orphaned",
        type="analysis",
        category="Analysis",
    )
    capability = Capability(
        id="cap-catalog",
        workspace_id=workspace.id,
        slug="catalog_capability",
        name="Catalog capability",
        skill_ids=[carried.id],
    )
    db.add_all([workspace, user, carried, orphaned, capability])
    db.commit()
    return workspace, user


def test_catalog_serves_its_taxonomy_and_the_reason_each_row_is_visible(db_session):
    workspace, user = _seed(db_session)

    payload = _client(db_session, workspace, user).get("/skills").json()

    assert [row["slug"] for row in payload["skills"]] == ["carried_v1"]
    row = payload["skills"][0]
    assert row["category"] == "Retrieval"
    assert row["visibility"] == {
        "visible": True,
        "reason": "capability",
        "capabilities": ["catalog_capability"],
        "key": "",
    }
    assert payload["catalog"]["total"] == 2
    assert payload["catalog"]["visible"] == 1
    assert payload["catalog"]["filtered"] == 1
    assert payload["catalog"]["filtered_reasons"] == {"unclaimed": 1}
    assert payload["catalog"]["policy"]["show_universal"] is True
    # A client cannot tell a decision from a default without this, and every
    # production workspace is still on the inferred side of it.
    assert payload["catalog"]["policy"]["allowed_industries_source"] == "inferred"


def test_filtered_rows_are_opt_in_and_carry_the_rule_that_dropped_them(db_session):
    workspace, user = _seed(db_session)

    payload = (
        _client(db_session, workspace, user)
        .get("/skills", params={"include_filtered": True})
        .json()
    )

    by_slug = {row["slug"]: row for row in payload["skills"]}
    assert set(by_slug) == {"carried_v1", "orphaned_v1"}
    assert by_slug["orphaned_v1"]["visibility"] == {
        "visible": False,
        "reason": "unclaimed",
        "capabilities": [],
        "key": "",
    }
    # The summary describes the catalog, not the requested page.
    assert payload["catalog"]["visible"] == 1


def test_an_excluded_row_names_the_industry_that_would_release_it(db_session):
    """The palette turns this into one sentence, so the row has to carry the
    lever and not merely the fact that something is missing."""

    workspace, user = _seed(db_session)
    db_session.add(
        Capability(
            id="cap-government",
            slug="mission_command",
            name="Mission command",
            tier="industry",
            industry="government",
            skill_ids=["skill-orphaned"],
        )
    )
    db_session.commit()

    payload = (
        _client(db_session, workspace, user)
        .get("/skills", params={"include_filtered": True})
        .json()
    )

    by_slug = {row["slug"]: row for row in payload["skills"]}
    assert by_slug["orphaned_v1"]["visibility"] == {
        "visible": False,
        "reason": "industry_not_allowed",
        "capabilities": [],
        "key": "government",
    }


def test_category_filter_narrows_the_catalog(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    assert [
        row["slug"]
        for row in client.get(
            "/skills", params={"include_filtered": True, "category": "Analysis"}
        ).json()["skills"]
    ] == ["orphaned_v1"]


def test_a_skill_published_from_a_model_carries_its_provenance(db_session):
    """The chip's data reaches the catalog, and only where it is true.

    A published Skill sits in the same list as forty hand-written ones, and what
    distinguishes it is that its answer has a measured source. The row has to
    carry that, or the catalog is the one surface in the product where a model's
    provenance is lost.
    """

    workspace, user = _seed(db_session)
    published = Skill(
        id="skill-published",
        workspace_id=workspace.id,
        slug=f"ws.{workspace.id}.predict_churn_risk",
        name="Predict · Churn risk",
        type="workflow",
        category="Retrieval",
        executor={
            "kind": "registry_call",
            "params": {
                "skill_slug": "ml_predict_v1",
                "frozen_input": {
                    "_predict": {
                        "model_id": "model-2",
                        "model_slug": "churn-risk",
                        "workspace_id": workspace.id,
                    }
                },
            },
        },
    )
    db_session.add(published)
    db_session.add_all(
        MLModel(
            id=f"model-{version}",
            workspace_id=workspace.id,
            name="Churn risk",
            slug="churn-risk",
            version=version,
            task="classification",
            algo="gradient_boosting",
            target="churn",
            status="ready",
            is_champion=version == 2,
            metrics_json={"primary": {"key": "roc_auc", "value": 0.85 + version / 100}},
        )
        for version in (1, 2)
    )
    db_session.commit()

    rows = {
        row["slug"]: row
        for row in _client(db_session, workspace, user)
        .get("/skills", params={"include_filtered": True})
        .json()["skills"]
    }

    provenance = rows[published.slug]["provenance"]
    assert provenance["model_id"] == "model-2", "the champion answers, not the newest"
    assert provenance["version"] == 2
    assert provenance["name"] == "Churn risk"
    assert provenance["metric"] == {"key": "roc_auc", "value": 0.87}
    # Absent rather than null on every other row: a hand-written Skill has
    # nothing to attribute, and an empty block would render an empty chip.
    assert "provenance" not in rows["carried_v1"]


def test_every_seeded_slug_has_a_wrapper_and_a_category():
    """A wrapper without a catalog row is invisible; a row without a category
    lands in `Other` and the palette stops answering "what goes here"."""

    slugs = {entry["slug"] for entry in SEED_SKILLS}
    assert slugs - set(_REGISTRY) == set(), "catalog rows with no runtime wrapper"
    assert set(_REGISTRY) - slugs == set(), "wrappers with no catalog row"
    assert slugs - set(SKILL_CATEGORIES) == set(), "catalog rows with no category"
    assert set(SKILL_CATEGORIES) - slugs == set(), "categories for unknown slugs"


def test_no_category_absorbs_more_than_a_fifth_of_the_catalog():
    """The frontend heuristic this replaced put a quarter of the registry in
    one bucket, which is a list, not a taxonomy."""

    counts: dict[str, int] = {}
    for category in SKILL_CATEGORIES.values():
        counts[category] = counts.get(category, 0) + 1
    largest, size = max(counts.items(), key=lambda item: item[1])
    assert size <= len(SKILL_CATEGORIES) // 5, (
        f"{largest} holds {size} of {len(SKILL_CATEGORIES)} skills"
    )
