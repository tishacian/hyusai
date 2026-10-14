"""Explicit local storage fault injection / fixture setup, never a writer API."""

from app.services.object_store import get_object_store
from app.services.tabular_datasets import _apply_profile, profile_frame


def overwrite_legacy_fixture(dataset, frame):
    """Deliberately replace bytes so integrity tests can exercise corrupted versions.

    Production register_frame now correctly refuses rewriting a ready version.
    Tests that change a completed source must inject corruption below that gate.
    """
    store = get_object_store()
    assert store.backend == "local" and dataset.storage_key.endswith(".parquet")
    path = store._local_path(dataset.storage_key)
    frame.write_parquet(path, compression="zstd")
    dataset.size_bytes = path.stat().st_size
    _apply_profile(dataset, profile_frame(frame))
