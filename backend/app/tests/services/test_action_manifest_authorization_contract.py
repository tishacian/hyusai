"""Static contract between Action Packs and their IAM manifests.

Lot 7 may promote ``action.execute`` from shadow to enforce per workspace.
Every published action must therefore name a real IAM manifest containing the
exact permission it requests; relying on the legacy manifest fallback would
turn a harmless shadow mismatch into a production denial.
"""

from app.services.actions.registry import all_action_manifests
from app.services.iam.manifest import MANIFESTS


def test_every_action_manifest_permission_is_declared_by_its_iam_manifest():
    missing: list[str] = []

    for action in all_action_manifests():
        iam_manifest = MANIFESTS.get(action.capability_template or "agentium_actions")
        if iam_manifest is None:
            missing.append(
                f"{action.action_id}: unknown IAM manifest "
                f"{action.capability_template!r}"
            )
            continue

        try:
            resource_kind, permission = action.required_permission.split(".", 1)
        except ValueError:
            missing.append(
                f"{action.action_id}: malformed permission "
                f"{action.required_permission!r}"
            )
            continue

        if not any(
            rule.resource_kind == resource_kind and rule.action == permission
            for rule in iam_manifest.permissions
        ):
            missing.append(
                f"{action.action_id}: {iam_manifest.capability_id} does not declare "
                f"{action.required_permission}"
            )

    assert missing == []
