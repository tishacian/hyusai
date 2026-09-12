"""Publication and run ingress refuse Skills without a real runtime."""

from types import SimpleNamespace

import pytest

from app.services.systems import flow_publication


def _bindings(*skills):
    return SimpleNamespace(
        skills=skills,
        effective_skill_ids=tuple(skill.id for skill in skills),
    )


def test_seeded_stub_blocks_publication(monkeypatch):
    skill = SimpleNamespace(
        id="skill-stub",
        slug="placeholder_v1",
        workspace_id=None,
    )
    monkeypatch.setattr(
        flow_publication,
        "resolve_persisted_system_catalog_bindings",
        lambda *_args, **_kwargs: _bindings(skill),
    )
    monkeypatch.setattr(flow_publication, "runtime_status", lambda _slug: "stub")

    with pytest.raises(flow_publication.FlowPublicationError) as refused:
        flow_publication.assert_system_skills_ready(
            object(),
            system=SimpleNamespace(),
            workspace=SimpleNamespace(),
        )

    assert refused.value.code == "SKILL_RUNTIME_NOT_READY"
    assert refused.value.status_code == 422
    assert refused.value.details == {
        "skill_id": "skill-stub",
        "skill_slug": "placeholder_v1",
        "runtime_status": "stub",
    }


def test_workspace_skill_inherits_underlying_runtime_status(monkeypatch):
    skill = SimpleNamespace(
        id="skill-authored",
        slug="ws.demo.authored",
        workspace_id="workspace-id",
        executor={"kind": "registry_call", "params": {"skill_slug": "placeholder_v1"}},
    )
    monkeypatch.setattr(
        flow_publication,
        "resolve_persisted_system_catalog_bindings",
        lambda *_args, **_kwargs: _bindings(skill),
    )
    monkeypatch.setattr(flow_publication, "executor_runtime_status", lambda _binding: "stub")

    with pytest.raises(flow_publication.FlowPublicationError) as refused:
        flow_publication.assert_system_skills_ready(
            object(),
            system=SimpleNamespace(),
            workspace=SimpleNamespace(),
        )

    assert refused.value.code == "SKILL_RUNTIME_NOT_READY"
    assert refused.value.details["runtime_status"] == "stub"


def test_bound_skills_return_the_effective_allowlist(monkeypatch):
    seeded = SimpleNamespace(id="seeded", slug="audit_log_v1", workspace_id=None)
    authored = SimpleNamespace(
        id="authored",
        slug="ws.demo.authored",
        workspace_id="workspace-id",
        executor={"kind": "registry_call", "params": {"skill_slug": "audit_log_v1"}},
    )
    monkeypatch.setattr(
        flow_publication,
        "resolve_persisted_system_catalog_bindings",
        lambda *_args, **_kwargs: _bindings(seeded, authored),
    )
    monkeypatch.setattr(flow_publication, "runtime_status", lambda _slug: "bound")
    monkeypatch.setattr(flow_publication, "executor_runtime_status", lambda _binding: "bound")

    allowed = flow_publication.assert_system_skills_ready(
        object(),
        system=SimpleNamespace(),
        workspace=SimpleNamespace(),
    )

    assert allowed == {"seeded", "authored"}
