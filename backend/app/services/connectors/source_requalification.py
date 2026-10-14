"""A changed object invalidates its imported dataset and native descendants."""

from app.models.tabular import TabularDataset
from app.services.dataops.asset_lineage import ensure_dataset_asset
from app.services.governed_assets import asset_ref, current_qualification, mark_for_requalification


def affected_datasets(rows, connection_id, changed):
    objects = {item["key"]: item for item in changed}
    roots = {
        row.id
        for row in rows
        if (row.lineage_json or {}).get("connection_id") == connection_id
        and any(
            item.get("key") in objects and item.get("etag") != objects[item["key"]].get("etag")
            for item in (row.lineage_json or {}).get("source_objects") or []
        )
    }
    affected = set(roots)
    while True:
        added = {row.id for row in rows if set(row.parent_ids or []) & affected} - affected
        if not added:
            break
        affected.update(added)
    return roots, affected


def invalidate(db, workspace_id, connection_id, changed):
    rows = db.query(TabularDataset).filter_by(workspace_id=workspace_id, status="ready").all()
    roots, affected = affected_datasets(rows, connection_id, changed)
    assets = {
        identifier: ensure_dataset_asset(db, workspace_id, identifier)
        for identifier in sorted(affected)
    }
    count = 0
    for identifier in sorted(roots):
        asset = assets[identifier]
        previous = current_qualification(db, workspace_id, asset.id)
        if previous and previous.status == "needs_requalification":
            continue
        count += mark_for_requalification(
            db,
            workspace_id,
            asset_ref(asset),
            actor="connector_watch",
            reason="CONNECTOR_SOURCE_OBJECT_CHANGED",
        )
    return count
