from datetime import UTC, datetime, timedelta

import pytest

from app.services.huggingface.errors import HFError
from app.services.huggingface.lifecycle import execute_purge, plan_purge

NOW = datetime(2026, 10, 9, tzinfo=UTC)


def artifact(identity="a", *, files=None, **kwargs):
    return {
        "id": identity,
        "status": "revoked",
        "in_catalogue": False,
        "manifest_key": f"hub/artifacts/{identity}/manifest.json",
        "manifest_json": {
            "kind": "model",
            "files": files
            or {
                "config.json": {"object_key": "hub/blobs/shared/config.json"},
                "weights.gguf": {"object_key": f"hub/blobs/{identity}/weights.gguf"},
            },
        },
        **kwargs,
    }


def plan(value, **kwargs):
    return plan_purge(value, **{"artifacts": [], "grants": [], "usages": [], "now": NOW, **kwargs})


def test_purge_preserves_other_selection_shared_files():
    first, second = artifact(), artifact("b", status="ready")
    result = plan(first, artifacts=[first, second])
    assert result.delete_keys == ("hub/blobs/a/weights.gguf",)
    assert result.preserve_shared_keys == ("hub/blobs/shared/config.json",)


@pytest.mark.parametrize("reason", ["grant", "catalogue", "lease", "draining", "active"])
def test_purge_waits_for_all_reference_holders(reason):
    candidate, kwargs = artifact(), {}
    if reason == "grant":
        kwargs["grants"] = [{"artifact_id": "a", "revoked_at": None}]
    elif reason == "catalogue":
        candidate["in_catalogue"] = True
    else:
        kwargs["usages"] = [
            {
                "artifact_id": "a",
                "status": "unavailable" if reason == "lease" else reason,
                "lease_expires_at": NOW + timedelta(seconds=1) if reason == "lease" else None,
            }
        ]
    with pytest.raises(HFError) as error:
        plan(candidate, **kwargs)
    assert error.value.code == "HF_PURGE_BLOCKED"


def test_expired_lease_only_releases_unavailable_usage():
    usage = {
        "artifact_id": "a",
        "status": "unavailable",
        "lease_expires_at": NOW - timedelta(seconds=1),
    }
    assert plan(artifact(), usages=[usage]).delete_keys
    usage["status"] = "draining"
    with pytest.raises(HFError):
        plan(artifact(), usages=[usage])


def test_remote_deletion_must_be_confirmed_before_any_local_delete():
    candidate = plan(artifact())
    with pytest.raises(HFError, match="not confirmed"):
        execute_purge(
            candidate,
            revalidate=lambda: candidate,
            release_remote_copies=lambda _: False,
            remove_local_cache=lambda _: pytest.fail("Must preserve local files"),
            delete_object=lambda _: pytest.fail("Must preserve objects"),
            record_receipt=lambda _: None,
        )


def test_local_open_lease_blocks_object_deletion():
    candidate = plan(artifact())
    with pytest.raises(HFError, match="cache lease"):
        execute_purge(
            candidate,
            revalidate=lambda: candidate,
            release_remote_copies=lambda _: True,
            remove_local_cache=lambda _: False,
            delete_object=lambda _: pytest.fail("Must preserve objects"),
            record_receipt=lambda _: None,
        )


def test_receipt_after_deletion_manifest_last_and_revalidation():
    candidate = plan(artifact())
    deleted, receipts = [], []
    result = execute_purge(
        candidate,
        revalidate=lambda: candidate,
        release_remote_copies=lambda _: True,
        remove_local_cache=lambda identity: deleted.append(f"cache:{identity}"),
        delete_object=deleted.append,
        record_receipt=receipts.append,
        now=NOW,
    )
    assert deleted[0] == "cache:a"
    assert deleted[-1] == "hub/artifacts/a/manifest.json"
    assert receipts == [result]


def test_failed_deletion_does_not_record_success():
    candidate = plan(artifact())

    def fail(_):
        raise OSError("store unavailable")

    with pytest.raises(OSError):
        execute_purge(
            candidate,
            revalidate=lambda: candidate,
            release_remote_copies=lambda _: True,
            remove_local_cache=lambda _: None,
            delete_object=fail,
            record_receipt=lambda _: pytest.fail("Incomplete purge must not be recorded"),
        )
