"""Workspace settings for fixtures that model a workspace open before migration 111.

``iam_enforced`` is a code default since migration 111: a workspace without the
key is governed by the role manifests. The migration wrote an explicit
``false`` on every workspace that was open before it. A fixture whose subject
is not IAM, and which acts through users it never made members (the suite
overrides the membership check that production applies first), models one of
those workspaces and says so with this value.
"""

from __future__ import annotations

from typing import Any

#: Merge into ``settings["features"]`` of a fixture workspace.
OPEN_IAM_FEATURES: dict[str, Any] = {"iam_enforced": False}
