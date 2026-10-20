"""An explicit consistency requirement cannot silently downgrade on import."""

from types import SimpleNamespace

import pytest

from app.services.connectors import adapters
from app.services.connectors.adapters.sql import AdapterError


@pytest.mark.parametrize("actual", [None, "none", "per_partition"])
def test_required_snapshot_rejects_weaker_adapter_output(monkeypatch, tmp_path, actual):
    seen = []

    def execute(*args, **kwargs):
        seen.append(args[3])
        return {} if actual is None else {"consistency": actual}

    monkeypatch.setattr(adapters, "import_module", lambda name: SimpleNamespace(execute=execute))
    with pytest.raises(AdapterError, match="CONNECTOR_CONSISTENCY_UNAVAILABLE"):
        adapters.execute(
            "import",
            {},
            {},
            {"require_consistency": "snapshot"},
            999,
            tmp_path,
            family="object_store",
            dialect="s3",
        )
    assert seen == [{}]


def test_snapshot_can_satisfy_partition_requirement(monkeypatch, tmp_path):
    monkeypatch.setattr(
        adapters,
        "import_module",
        lambda name: SimpleNamespace(execute=lambda *a, **kw: {"consistency": "snapshot"}),
    )
    assert adapters.execute(
        "preview",
        {},
        {},
        {"require_consistency": "per_partition"},
        999,
        tmp_path,
        family="sqlalchemy",
        dialect="postgresql",
    ) == {"consistency": "snapshot"}
