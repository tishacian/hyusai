"""L22 — invite accepts role_template alone and keeps owner transfer-only."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.auth import _resolve_member_role_template
from app.core.iam.roles import (
    WORKSPACE_ADMIN,
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_OWNER,
    WORKSPACE_REVIEWER,
    WORKSPACE_VIEWER,
)


@pytest.mark.parametrize(
    ("role", "role_template", "expected"),
    [
        (None, WORKSPACE_VIEWER, WORKSPACE_VIEWER),
        (None, WORKSPACE_REVIEWER, WORKSPACE_REVIEWER),
        (None, WORKSPACE_CONTRIBUTOR, WORKSPACE_CONTRIBUTOR),
        (None, WORKSPACE_ADMIN, WORKSPACE_ADMIN),
        ("member", None, WORKSPACE_CONTRIBUTOR),
        ("admin", None, WORKSPACE_ADMIN),
    ],
)
def test_resolve_member_role_template_accepts_template_or_legacy(
    role: str | None,
    role_template: str | None,
    expected: str,
) -> None:
    assert (
        _resolve_member_role_template(role=role, role_template=role_template)
        == expected
    )


def test_resolve_member_role_template_rejects_owner_and_unknown() -> None:
    with pytest.raises(HTTPException) as owner:
        _resolve_member_role_template(role=None, role_template=WORKSPACE_OWNER)
    assert owner.value.status_code == 400

    with pytest.raises(HTTPException) as unknown:
        _resolve_member_role_template(role=None, role_template="not_a_role")
    assert unknown.value.status_code == 400

    with pytest.raises(HTTPException) as missing:
        _resolve_member_role_template(role=None, role_template=None)
    assert missing.value.status_code == 400
