#!/usr/bin/env python3
"""Real TabICLv2 safe conversion and autonomous reload qualification (Linux).

Uses the two explicitly provisioned checkpoints and safetensors directories.
A seccomp filter denies connect/send syscalls before fitting; there is no Hub
fallback. This tiny smoke establishes portability, not business value.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import errno
import gc
import json
import resource
import shutil
import socket
import sys
import tempfile
import time
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def deny_network():
    library = ctypes.CDLL(ctypes.util.find_library("seccomp") or "libseccomp.so.2", use_errno=True)
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    library.seccomp_load.argtypes = [ctypes.c_void_p]
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    context = library.seccomp_init(0x7FFF0000)
    if not context:
        raise RuntimeError("Cannot initialize seccomp; offline proof unavailable")
    try:
        for name in (b"connect", b"sendto", b"sendmsg", b"sendmmsg"):
            syscall = library.seccomp_syscall_resolve_name(name)
            if syscall >= 0 and library.seccomp_rule_add(
                context, 0x00050000 | errno.EPERM, syscall, 0
            ):
                raise RuntimeError("Cannot install network denial rule")
        if library.seccomp_load(context):
            raise RuntimeError("Cannot enforce seccomp network denial")
    finally:
        library.seccomp_release(context)
    with socket.socket() as probe:
        try:
            probe.connect(("192.0.2.1", 443))
        except PermissionError:
            return
    raise RuntimeError("Network denial probe did not fail with EPERM")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("weights", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    deny_network()
    import numpy as np
    import pandas as pd
    from sklearn.datasets import load_diabetes, load_iris
    from tabicl import TabICLClassifier, TabICLRegressor

    from app.resources.ml_tabicl_runtime import build_estimator, export_state, load_state

    records = []
    for task, data in (("classification", load_iris()), ("regression", load_diabetes())):
        started = time.monotonic()
        X = pd.DataFrame(data.data[:120], columns=[f"x{i}" for i in range(data.data.shape[1])])
        y = data.target[:120]
        with tempfile.TemporaryDirectory(prefix="tabicl-offline-") as temporary:
            root = Path(temporary)
            source = root / "source"
            shutil.copytree(args.weights / task, source)
            cls = TabICLClassifier if task == "classification" else TabICLRegressor
            reference = cls(
                n_estimators=1,
                model_path=str(args.weights / f"{task}.ckpt"),
                allow_auto_download=False,
                device="cpu",
                n_jobs=4,
                batch_size=1,
                use_amp=False,
                use_fa3=False,
                offload_mode=False,
            )
            reference.fit(X.iloc[:90], y[:90])
            expected = reference.predict(X.iloc[90:95])
            del reference
            gc.collect()
            estimator = build_estimator(task, source)
            estimator.fit(X.iloc[:90], y[:90])
            before = estimator.predict(X.iloc[90:95])
            np.testing.assert_allclose(before, expected, rtol=1e-6, atol=1e-6)
            export_state(estimator, X.iloc[:90], y[:90], root / "state")
            del estimator
            gc.collect()
            shutil.rmtree(source)
            restored = load_state(root / "state")
            np.testing.assert_allclose(
                restored.predict(X.iloc[90:95]), before, rtol=1e-6, atol=1e-6
            )
            del restored
            gc.collect()
        record = {
            "task": task,
            "status": "passed",
            "conversion_parity": True,
            "autonomous_reload": True,
            "source_copy_removed": True,
            "rtol": 1e-6,
            "atol": 1e-6,
            "seconds": time.monotonic() - started,
            "process_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        }
        if record["process_peak_rss_mib"] >= 4096:
            raise RuntimeError("TabICL smoke exceeded the 4 GiB serving memory ceiling")
        records.append(record)
        print(json.dumps(record), flush=True)
    report = {
        "schema": 1,
        "network": "seccomp_connect_send_denied_verified_eperm",
        "versions": {
            name: version(name)
            for name in ("tabicl", "torch", "numpy", "pandas", "scikit-learn", "safetensors")
        },
        "results": records,
        "scope": "technical_smoke_no_business_value_claim",
    }
    args.report.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
