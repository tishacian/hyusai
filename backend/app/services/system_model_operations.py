"""Read-only placement of model operations in the Systems portfolio.

This is navigation provenance, never an ownership or cost-allocation rule.
Several published business Flows may reference the same model lineage. Drafts,
runtime-only model choices and historical Runs are deliberately not inferred.
"""

from collections.abc import Mapping

from app.models.system_version import SystemVersion

PREDICTION_SKILLS = {"ml_predict_v1", "ml_batch_score_v1", "ml_forecast_v1"}


def model_operation(system):
    settings = system.settings if isinstance(system.settings, Mapping) else {}
    # The original marker stays authoritative for existing scheduled Flows;
    # new metadata is additive, so no migration or schedule rewrite is needed.
    model_id = settings.get("ml_monitoring_model_id")
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    return {"kind": "model_monitoring", "model_id": model_id}


def category(system):
    return "model_operations" if model_operation(system) else "business"


def published_references(db, *, system, model, workspace_models):
    """Static lineage references, including explicit pins to other versions.

    An explicit model id takes precedence over a slug, as in the serving
    wrapper. A publication pointer is read from its immutable, tenant-owned
    version rather than an editable draft or an inconsistent legacy mirror.
    """
    if category(system) != "business":
        return []
    version_id = system.published_flow_version_id
    if version_id:
        version = db.get(SystemVersion, version_id)
        if (
            version is None
            or version.system_id != system.id
            or version.workspace_id != system.workspace_id
        ):
            return []
        flow = version.flow_definition
    else:
        if system.status == "draft":
            return []
        flow = system.flow_definition
    if not isinstance(flow, Mapping) or not isinstance(flow.get("nodes"), list):
        return []
    references = []
    for node in flow["nodes"]:
        if not isinstance(node, Mapping):
            continue
        config = node.get("config")
        if not isinstance(config, Mapping) or config.get("skill_slug") not in PREDICTION_SKILLS:
            continue
        params = config.get("params")
        if not isinstance(params, Mapping):
            continue
        selected_id = params.get("model_id")
        selected = workspace_models.get(selected_id) if isinstance(selected_id, str) else None
        slug = selected.slug if selected is not None else params.get("model_slug")
        if slug != model.slug:
            continue
        pin = params.get("pinned_version")
        references.append(
            {
                "node_id": str(node.get("id") or ""),
                "binding": "champion" if pin is None else "pinned",
                "pinned_version": pin,
                "flow_version_id": version_id,
            }
        )
    return references
