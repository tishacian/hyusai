from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.admin import _require_sentinel_workspace_contract


def _workspace(*, slug: str, family: object = None):
    settings = {} if family is None else {"family": family}
    return SimpleNamespace(slug=slug, name=slug, settings=settings)


def test_sentinel_admin_guard_uses_canonical_family_not_slug() -> None:
    with pytest.raises(HTTPException) as legacy_error:
        _require_sentinel_workspace_contract(
            _workspace(slug="sentinel-ci"),
        )
    assert legacy_error.value.status_code == 400

    _require_sentinel_workspace_contract(
        _workspace(slug="institutional-operations", family="sentinel_ci"),
    )


@pytest.mark.parametrize("family", ["generic", "sentinel", True, 1])
def test_sentinel_admin_guard_fails_closed_on_noncanonical_family(family: object) -> None:
    with pytest.raises(HTTPException) as error:
        _require_sentinel_workspace_contract(
            _workspace(slug="sentinel-ci", family=family),
        )
    assert error.value.status_code == 400
