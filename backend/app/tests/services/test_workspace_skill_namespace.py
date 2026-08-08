"""The slug namespace that makes a workspace Skill unable to shadow a seeded one.

Two things share the ``skills.slug`` column: 85 seeded slugs that are the runtime
dispatch key of every published Flow, and whatever a workspace authors. The
namespace makes them disjoint alphabets rather than two lists someone has to keep
comparing, so the guarantee survives a seeder that grows.
"""
from __future__ import annotations

import pytest

from app.models.capability import Capability
from app.models.skill import Skill
from app.services.skills_registry.binding import (
    NAMESPACE_SEPARATOR,
    WORKSPACE_SLUG_PREFIX,
    SkillBindingError,
    is_workspace_skill_slug,
    parse_workspace_skill_slug,
    workspace_skill_slug,
)
from app.services.skills_registry.seed import SEED_SKILLS, seed_skills_and_capabilities


def test_the_two_vocabularies_cannot_intersect():
    """Not "no seeded slug currently collides" — no seeded slug *can*."""

    seeded = [str(entry["slug"]) for entry in SEED_SKILLS]

    assert seeded
    for slug in seeded:
        assert NAMESPACE_SEPARATOR not in slug, slug
        assert not is_workspace_skill_slug(slug), slug
        assert parse_workspace_skill_slug(slug) is None, slug

    authored = workspace_skill_slug(workspace_id="ws-1", local_name="reset_ticket").slug
    assert authored.startswith(WORKSPACE_SLUG_PREFIX)
    assert authored not in seeded


def test_the_owner_segment_is_the_workspace_id_and_not_supplied_by_the_caller():
    """A local name that spells another namespace is still confined to its own.

    This is the cross-tenant squat: if the caller could contribute the owner
    segment, an admin of one workspace could author into another's namespace and
    have its runs resolve to a Skill it never defined.
    """

    minted = workspace_skill_slug(workspace_id="ws-attacker", local_name="anything")
    assert minted.workspace_id == "ws-attacker"

    with pytest.raises(SkillBindingError) as refused:
        workspace_skill_slug(workspace_id="ws-attacker", local_name="ws.ws-victim.thing")
    assert refused.value.code == "skill_local_name_invalid"


@pytest.mark.parametrize(
    "local_name",
    [
        "ab",  # too short to be a name
        "9lives",  # must start with a letter
        "reset-ticket",  # hyphen belongs to the owner segment's alphabet
        "reset ticket",
        "semantic_search_v1/../..",
        "x" * 65,
        "",
    ],
)
def test_a_local_name_outside_the_alphabet_is_refused(local_name):
    with pytest.raises(SkillBindingError):
        workspace_skill_slug(workspace_id="ws-1", local_name=local_name)


def test_a_workspace_id_carrying_the_separator_cannot_mint_at_all():
    """An ambiguous slug is unparseable, so it is refused rather than escaped."""

    with pytest.raises(SkillBindingError) as refused:
        workspace_skill_slug(workspace_id="ws.evil", local_name="thing")
    assert refused.value.code == "skill_namespace_unavailable"


def test_a_namespaced_slug_round_trips():
    identity = workspace_skill_slug(workspace_id="ws-1", local_name="reset_ticket")
    parsed = parse_workspace_skill_slug(identity.slug)

    assert parsed == identity
    assert identity.slug == "ws.ws-1.reset_ticket"


def test_case_and_padding_are_normalised_rather_than_refused():
    """Two names that read identically must not become two dispatch keys."""

    assert (
        workspace_skill_slug(workspace_id="ws-1", local_name="  Reset_Ticket ").slug
        == workspace_skill_slug(workspace_id="ws-1", local_name="reset_ticket").slug
    )


def test_a_reseed_cannot_capture_an_authored_row(db_session):
    """The accident the namespace prevents, exercised rather than asserted.

    ``seed_skills_and_capabilities`` upserts on ``slug`` alone, with no
    workspace filter. A workspace row holding a seeded slug would be adopted on
    the next boot: stamped ``is_seeded='Y'``, its contract overwritten, and left
    owned by one workspace while every other workspace lost the catalog entry.
    """

    authored = Skill(
        id="authored-survivor",
        workspace_id="ws-1",
        slug=workspace_skill_slug(workspace_id="ws-1", local_name="reset_ticket").slug,
        name="Reset ticket",
        description="authored",
        type="generic",
        category="Automation",
        input_schema={"type": "object"},
        executor={"kind": "registry_call", "params": {"skill_slug": "audit_log_v1"}},
        is_seeded="N",
    )
    db_session.add(authored)
    db_session.commit()

    seed_skills_and_capabilities(db_session)
    db_session.refresh(authored)

    assert authored.is_seeded == "N"
    assert authored.workspace_id == "ws-1"
    assert authored.description == "authored"
    assert authored.executor == {
        "kind": "registry_call",
        "params": {"skill_slug": "audit_log_v1"},
    }
    # And the seeder still owns the whole global catalog beside it.
    seeded = (
        db_session.query(Skill)
        .filter(Skill.workspace_id.is_(None), Skill.is_seeded == "Y")
        .count()
    )
    assert seeded == len(SEED_SKILLS)
    # Nothing the seeder wrote claims the authored row either.
    for capability in db_session.query(Capability).all():
        assert authored.id not in (capability.skill_ids or [])
