"""Reference-aware physical deletion after logical revocation.

The caller holds the registry admission lock for the full plan/delete/receipt
transaction. A failed deletion is safely retryable: a revoked manifest is never
made ready again and missing objects count as already deleted.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from app.services.huggingface.errors import HFError

_RELEASED_STATES = frozenset(
    {"stopped", "failed", "released", "deleted", "inactive", "unavailable"}
)


def _get(record: Any, field: str, default: Any = None) -> Any:
    return (
        record.get(field, default)
        if isinstance(record, Mapping)
        else getattr(record, field, default)
    )


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def retained_usage(usage: Any, *, now: datetime) -> bool:
    """A drain is still a holder, even when its grant has been revoked."""
    lease = _get(usage, "lease_expires_at")
    if isinstance(lease, str):
        try:
            lease = datetime.fromisoformat(lease)
        except ValueError:
            return True  # Unknown lease is never evidence of release.
    if lease is not None and (not isinstance(lease, datetime) or _aware(lease) > _aware(now)):
        return True
    return str(_get(usage, "status", "unknown")).lower() not in _RELEASED_STATES


def _manifest(artifact: Any) -> Mapping:
    return _get(artifact, "manifest_json", {}) or {}


def object_references(artifact: Any) -> set[str]:
    """Published blobs and dataset results; source dataset staging is excluded."""
    manifest = _manifest(artifact)
    files = manifest.get("files", {}) if manifest.get("kind") != "dataset" else {}
    refs = {
        str(item["object_key"])
        for item in files.values()
        if isinstance(item, Mapping) and item.get("object_key")
    }
    if _get(artifact, "kind") == "model":
        from types import SimpleNamespace

        from app.services.huggingface.storage import blob_key

        owner = SimpleNamespace(**artifact) if isinstance(artifact, Mapping) else artifact
        for path in _get(artifact, "files_json", {}) or {}:
            refs.add(blob_key(owner, path))
    result = manifest.get("dataset_result") or {}
    if isinstance(result, Mapping) and result.get("object_key"):
        refs.add(str(result["object_key"]))
    return refs


@dataclass(frozen=True)
class PurgePlan:
    artifact_id: str
    delete_keys: tuple[str, ...]
    preserve_shared_keys: tuple[str, ...]
    manifest_key: str | None


def plan_purge(
    artifact: Any,
    *,
    artifacts: Iterable[Any],
    grants: Iterable[Any],
    usages: Iterable[Any],
    retained_result_keys: Iterable[str] = (),
    now: datetime | None = None,
) -> PurgePlan:
    """Compute deletion from a consistent snapshot under the admission lock.

    All other artifact references are preserved, including revoked artifacts whose
    own purge has not completed. Dataset output references are supplied separately.
    This deliberately favors a later garbage-collection pass over a dangling ref.
    """
    now = now or datetime.now(UTC)
    artifact_id = str(_get(artifact, "id", _get(artifact, "artifact_id", "")))
    if not artifact_id or _get(artifact, "status") != "revoked":
        raise HFError("HF_PURGE_BLOCKED", "Revoke the artifact before physical purge", 409)
    if _get(artifact, "in_catalogue", False):
        raise HFError(
            "HF_PURGE_BLOCKED", "Remove the artifact from the platform catalogue before purge", 409
        )
    for grant in grants:
        if str(_get(grant, "artifact_id")) == artifact_id and _get(grant, "revoked_at") is None:
            raise HFError(
                "HF_PURGE_BLOCKED",
                "An active workspace authorization still retains this artifact",
                409,
            )
    for usage in usages:
        if str(_get(usage, "artifact_id")) == artifact_id and retained_usage(usage, now=now):
            raise HFError(
                "HF_PURGE_BLOCKED", "A runtime usage or lease still retains this artifact", 409
            )
    candidate = object_references(artifact)
    retained = set(retained_result_keys)
    for other in artifacts:
        other_id = str(_get(other, "id", _get(other, "artifact_id", "")))
        if other_id == artifact_id:
            continue
        metadata = _get(other, "metadata_json", {}) or {}
        if not _get(other, "purged_at") and not metadata.get("purge_receipt"):
            retained.update(object_references(other))
    manifest_key = _get(artifact, "manifest_key")
    expected_manifest_key = f"hub/artifacts/{artifact_id}/manifest.json"
    if manifest_key and manifest_key != expected_manifest_key:
        raise HFError("HF_PURGE_BLOCKED", "Artifact manifest key is outside its owned prefix", 409)
    for key in candidate:
        if (
            not key
            or key.startswith("/")
            or "\\" in key
            or any(part in {"", ".", ".."} for part in key.split("/"))
        ):
            raise HFError("HF_PURGE_BLOCKED", "Invalid retained object reference", 409)
    return PurgePlan(
        artifact_id=artifact_id,
        delete_keys=tuple(sorted(candidate - retained)),
        preserve_shared_keys=tuple(sorted(candidate & retained)),
        manifest_key=manifest_key,
    )


def execute_purge(
    plan: PurgePlan,
    *,
    revalidate: Callable[[], PurgePlan],
    delete_object: Callable[[str], Any],
    remove_local_cache: Callable[[str], Any],
    release_remote_copies: Callable[[str], bool],
    record_receipt: Callable[[dict], Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Delete only after a final reference check and node release confirmation.

    Callbacks must run with the same registry lock. ``release_remote_copies`` must
    return True only after all tracked node copies are absent; lack of a reachable
    node is not proof of deletion. Receipts are persisted only after every operation.
    """
    if revalidate() != plan:
        raise HFError(
            "HF_PURGE_BLOCKED", "Artifact references changed; recompute the purge plan", 409
        )
    if release_remote_copies(plan.artifact_id) is not True:
        raise HFError("HF_PURGE_BLOCKED", "Remote artifact copies have not confirmed deletion", 409)
    if remove_local_cache(plan.artifact_id) is False:
        raise HFError(
            "HF_PURGE_BLOCKED", "A local runtime still holds this artifact's cache lease", 409
        )
    deleted = []
    for key in plan.delete_keys:
        delete_object(key)
        deleted.append(key)
    # Keep the manifest until its owned files are removed, allowing safe retry
    # after partial object-store failure. Registry provenance remains immutable.
    if plan.manifest_key:
        delete_object(plan.manifest_key)
        deleted.append(plan.manifest_key)
    receipt = {
        **asdict(plan),
        "deleted_keys": deleted,
        "deleted_at": (now or datetime.now(UTC)).isoformat(),
        "local_cache_removed": True,
        "remote_copies_released": True,
    }
    record_receipt(receipt)
    return receipt


def purge_registry_artifact(
    db: Any,
    artifact_id: str,
    *,
    store: Any,
    remove_local_cache: Callable[[str], Any],
    release_remote_copies: Callable[[str], bool],
    delete_dataset_result: Callable[[str, Mapping], Any] | None = None,
    retained_result_keys: Iterable[str] = (),
) -> dict[str, Any]:
    """Registry-backed purge, serialized with import admission and grants.

    The API verifies platform-admin rights before calling this function. Dataset
    deletion uses the dedicated tabular identity, never the hub writer credentials.
    The callback receives the artifact ID plus its verified result metadata and
    must derive/check the owning tabular key itself.
    """
    from app.models.huggingface import HubArtifact, HubArtifactGrant, HubArtifactUsage
    from app.services.huggingface.registry import admission_lock

    admission_lock(db)
    artifact = db.get(HubArtifact, artifact_id)
    if artifact is None:
        raise HFError("HF_NOT_FOUND", "Artifact does not exist", 404)
    if artifact.purged_at:
        return dict((artifact.metadata_json or {}).get("purge_receipt") or {})

    def revalidate() -> PurgePlan:
        db.flush()
        return plan_purge(
            artifact,
            artifacts=db.query(HubArtifact).all(),
            grants=db.query(HubArtifactGrant).filter_by(artifact_id=artifact_id).all(),
            usages=db.query(HubArtifactUsage).filter_by(artifact_id=artifact_id).all(),
            retained_result_keys=retained_result_keys,
        )

    plan = revalidate()
    dataset_result = _manifest(artifact).get("dataset_result") or {}
    dataset_key = dataset_result.get("object_key")
    if dataset_key in plan.delete_keys and delete_dataset_result is None:
        raise HFError(
            "HF_PURGE_BLOCKED", "Dataset purge requires the owning tabular storage identity", 409
        )

    def delete(key: str) -> None:
        if dataset_key and key == dataset_key:
            delete_dataset_result(artifact_id, dataset_result)
        else:
            if not key.startswith("hub/"):
                raise HFError(
                    "HF_PURGE_BLOCKED", "Hub purge cannot delete outside the hub prefix", 409
                )
            store.delete(key)

    def record(receipt: dict) -> None:
        artifact.metadata_json = {**(artifact.metadata_json or {}), "purge_receipt": receipt}
        artifact.purged_at = datetime.utcnow()
        db.flush()

    return execute_purge(
        plan,
        revalidate=revalidate,
        delete_object=delete,
        remove_local_cache=remove_local_cache,
        release_remote_copies=release_remote_copies,
        record_receipt=record,
    )
