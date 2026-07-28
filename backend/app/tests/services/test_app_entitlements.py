from __future__ import annotations

import pytest

from app.models.user import User
from app.models.workspace import (
    Workspace,
    WorkspaceMember,
    WorkspaceMemberAppEntitlement,
)
from app.services.iam.app_entitlements import (
    APP_ENTITLEMENTS_FEATURE,
    BUSINESS_APP_KEYS,
    CHAT_APP,
    CLIENT360_APP,
    FSE_REPORTS_APP,
    KNOWLEDGE_CAPTURE_APP,
    WorkspaceEntitlementMutationConflictError,
    app_entitlements_enabled,
    list_member_app_entitlements,
    lock_workspace_for_app_entitlement_mutation,
    member_has_app_entitlement,
    normalize_app_entitlements,
    replace_member_app_entitlements,
)


class _LockQuery:
    def __init__(self, events: list[str], workspace: Workspace | None):
        self.events = events
        self.workspace = workspace

    def filter(self, *_criteria):
        self.events.append("filter")
        return self

    def with_for_update(self):
        self.events.append("for_update")
        return self

    def populate_existing(self):
        self.events.append("populate_existing")
        return self

    def one_or_none(self):
        self.events.append("one_or_none")
        return self.workspace


class _LockDB:
    def __init__(self, workspace: Workspace | None):
        self.workspace = workspace
        self.events: list[str] = []

    def query(self, model):
        assert model is Workspace
        self.events.append("query")
        return _LockQuery(self.events, self.workspace)

    def refresh(self, workspace, *, attribute_names):
        assert workspace is self.workspace
        assert attribute_names == ["settings"]
        self.events.append("refresh_settings")
        workspace.settings = {
            "features": {APP_ENTITLEMENTS_FEATURE: True},
        }


def _seed_membership(db_session) -> tuple[Workspace, User, WorkspaceMember]:
    workspace = Workspace(
        id="workspace-app-entitlements",
        name="App Entitlements",
        slug="app-entitlements",
        settings={"features": {APP_ENTITLEMENTS_FEATURE: True}},
    )
    user = User(
        id="user-app-entitlements",
        username="app-entitlements",
        email="app-entitlements@example.test",
        role="user",
    )
    membership = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="member",
        role_template="workspace_contributor",
    )
    db_session.add_all([workspace, user, membership])
    db_session.commit()
    return workspace, user, membership


def test_normalize_app_entitlements_is_strict_deduplicated_and_canonical() -> None:
    # Fed every known key in reverse, with duplicates: canonical order out.
    # Derived from BUSINESS_APP_KEYS so registering a new app cannot rot this.
    assert normalize_app_entitlements(
        [KNOWLEDGE_CAPTURE_APP, CHAT_APP, CHAT_APP, CLIENT360_APP, FSE_REPORTS_APP]
        + list(reversed(BUSINESS_APP_KEYS))
    ) == list(BUSINESS_APP_KEYS)
    assert normalize_app_entitlements(None) == []
    assert normalize_app_entitlements([KNOWLEDGE_CAPTURE_APP, CHAT_APP, CLIENT360_APP]) == [
        CHAT_APP,
        CLIENT360_APP,
        KNOWLEDGE_CAPTURE_APP,
    ]

    with pytest.raises(ValueError, match="Unknown application entitlement"):
        normalize_app_entitlements(["mission-room"])
    with pytest.raises(ValueError, match="must be strings"):
        normalize_app_entitlements([CHAT_APP, 42])  # type: ignore[list-item]


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (True, True),
        (False, False),
        (None, False),
        ("true", False),
        ("false", False),
        (1, False),
        (0, False),
    ),
)
def test_feature_flag_requires_literal_true(db_session, value, expected: bool) -> None:
    workspace, _, _ = _seed_membership(db_session)
    workspace.settings = {"features": {APP_ENTITLEMENTS_FEATURE: value}}
    assert app_entitlements_enabled(workspace) is expected


def test_feature_flag_defaults_to_legacy_off(db_session) -> None:
    workspace, _, _ = _seed_membership(db_session)
    workspace.settings = {}
    assert app_entitlements_enabled(workspace) is False


def test_replace_member_app_entitlements_replaces_rows_in_canonical_order(db_session) -> None:
    _, grantor, membership = _seed_membership(db_session)

    granted = replace_member_app_entitlements(
        db_session,
        membership,
        [KNOWLEDGE_CAPTURE_APP, CHAT_APP, CHAT_APP],
        granted_by_user_id=grantor.id,
        grant_source="unit-test",
    )
    db_session.commit()

    assert granted == [CHAT_APP, KNOWLEDGE_CAPTURE_APP]
    assert list_member_app_entitlements(db_session, membership) == granted
    rows = (
        db_session.query(WorkspaceMemberAppEntitlement)
        .filter_by(workspace_member_id=membership.id)
        .all()
    )
    assert {row.app_key for row in rows} == set(granted)
    assert {row.granted_by_user_id for row in rows} == {grantor.id}
    assert {row.grant_source for row in rows} == {"unit-test"}

    replaced = replace_member_app_entitlements(
        db_session,
        membership,
        [CLIENT360_APP],
        granted_by_user_id=None,
        grant_source="unit-test-replace",
    )
    db_session.commit()

    assert replaced == [CLIENT360_APP]
    assert list_member_app_entitlements(db_session, membership) == [CLIENT360_APP]
    assert member_has_app_entitlement(db_session, membership, CLIENT360_APP) is True
    assert member_has_app_entitlement(db_session, membership, CHAT_APP) is False


def test_workspace_mutation_lock_refreshes_settings_after_for_update() -> None:
    stale = Workspace(
        id="workspace-lock-order",
        name="Lock order",
        slug="lock-order",
        settings={"features": {APP_ENTITLEMENTS_FEATURE: False}},
    )
    db = _LockDB(stale)

    locked = lock_workspace_for_app_entitlement_mutation(db, stale.id)  # type: ignore[arg-type]

    assert locked is stale
    assert db.events == [
        "query",
        "filter",
        "for_update",
        "populate_existing",
        "one_or_none",
        "refresh_settings",
    ]
    assert app_entitlements_enabled(locked) is True


def test_workspace_mutation_lock_fails_closed_when_workspace_disappears() -> None:
    db = _LockDB(None)

    with pytest.raises(WorkspaceEntitlementMutationConflictError, match="Workspace disappeared"):
        lock_workspace_for_app_entitlement_mutation(db, "missing")  # type: ignore[arg-type]

    assert db.events == [
        "query",
        "filter",
        "for_update",
        "populate_existing",
        "one_or_none",
    ]
