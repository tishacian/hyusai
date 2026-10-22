"""Authoritative campaign ownership for artifacts; ordinary business data stays separate."""

from app.models.run import Run
from app.services.evaluation.qualification import bound_profile, digest


def campaign_for_run(db, run_id, workspace_id=None):
    if not run_id:
        return None
    run = db.get(Run, run_id)
    if run is None:
        return None  # Historical producers may retain only a deleted Run id.
    if workspace_id is not None and run.workspace_id != workspace_id:
        raise ValueError("EVALUATION_ARTIFACT_RUN_INVALID")
    if run.evaluation_campaign_id:
        bound_profile(db, run)
    return run.evaluation_campaign_id


def dataset_slug(db, *, workspace_id, name, run_id=None, node_id=None):
    from app.services.tabular_datasets import slugify

    slug = slugify(name)
    campaign_id = campaign_for_run(db, run_id, workspace_id)
    if not campaign_id:
        return slug, None
    run = db.get(Run, run_id)
    suffix = digest([campaign_id, run.evaluation_binding, node_id, slug])[:24]
    return f"qa-{suffix}-{slug[:145]}", campaign_id


def validate_inputs(db, *, run_id, workspace_id, datasets):
    campaign_id = campaign_for_run(db, run_id, workspace_id)
    for item in datasets:
        if item.workspace_id != workspace_id:
            raise ValueError("EVALUATION_INPUT_WORKSPACE_INVALID")
        if item.evaluation_campaign_id and item.evaluation_campaign_id != campaign_id:
            raise ValueError("EVALUATION_INPUT_SCOPE_INVALID")
    return campaign_id
