"""One connector operation in a supervised process; no database or broker access."""

from __future__ import annotations

import ctypes
import json
import os
import re
import signal
import sys
from datetime import datetime
from pathlib import Path


def run(spec_path: Path, result_path: Path) -> int:
    try:
        spec = json.loads(spec_path.read_text())
        # The credential-bearing envelope exists only until the child has read
        # it. Parent cleanup covers startup failures; the directory is 0700.
        spec_path.unlink()
        if sys.platform.startswith("linux"):
            if (
                ctypes.CDLL(None).prctl(1, signal.SIGKILL) != 0
                or os.getppid() != spec["parent_pid"]
            ):
                raise RuntimeError("CONNECTOR_PARENT_LOST")
        from app.core.config import settings
        from app.services.connectors.adapters import execute
        from app.services.connectors.network_exceptions import NetworkGrant, network_grants

        settings.connector_runner_image_sha256 = spec.get("runner_image_sha256", "")
        for key, value in spec["network_policy"].items():
            setattr(settings, key, value)
        grants = tuple(
            NetworkGrant(
                item["cidr"], tuple(item["ports"]), datetime.fromisoformat(item["expires_at"])
            )
            for item in spec["network_grants"]
        )
        with network_grants(grants):
            output = execute(
                spec["operation"],
                spec["config"],
                spec["credentials"],
                spec["parameters"],
                spec["deadline_at"],
                result_path.parent,
                family=spec["family"],
                dialect=spec["dialect"],
                access=spec["access"],
                limits=spec["limits"],
                execution=spec.get("execution"),
            )
        if spec["operation"] == "test":
            from app.services.connectors.runtime_identity import observe

            output["runtime_identity"] = observe(spec["profile_key"], output)
        if spec["operation"] == "import":
            from app.services.connectors.artifacts import parquet_artifact

            output = parquet_artifact(output, result_path.parent, spec["deadline_at"])
            if spec["parameters"].get("incremental"):
                from app.services.connectors.incremental_merge import merge_incremental

                output = merge_incremental(
                    output,
                    result_path.parent,
                    spec["deadline_at"],
                    spec["execution"]["read_checkpoint"],
                    spec["parameters"]["incremental"]["key_column"],
                )
        result_path.write_text(json.dumps({"ok": True, "output": output}, allow_nan=False))
        return 0
    except BaseException as exc:
        # Never serialize a driver exception or its traceback. Only closed
        # machine codes are allowed out of this process.
        code = getattr(exc, "code", None)
        if not isinstance(code, str) or not re.fullmatch(r"(?:CONNECTOR|HANA)_[A-Z_]+", code):
            code = "CONNECTOR_ADAPTER_FAILED"
        result_path.write_text(json.dumps({"ok": False, "error_code": code}))
        return 1
    finally:
        spec_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(run(Path(sys.argv[1]), Path(sys.argv[2])))
