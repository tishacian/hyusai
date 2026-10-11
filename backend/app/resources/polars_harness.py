"""Standalone Polars transform harness executed BY THE VENV PYTHON.

Contract with the author script:
  * the script must define ``transform(inputs: dict[str, pl.DataFrame])``;
  * ``inputs`` maps the addressable name of each source (``input``, ``input_1``,
    the dataset's own view name) to an eagerly-read frame;
  * the return value becomes the produced dataset. A ``pl.DataFrame`` is the
    normal answer; a ``pl.LazyFrame`` is collected, and a dict of columns or a
    list of row dicts is accepted because both are natural things to build.

Only ``polars`` is assumed present — it is pinned into the managed venv by the
node's environment spec. The application is NOT importable here: the harness
runs on the venv interpreter, in a scratch cwd, with no application variable in
its environment.

Exit codes are the machine contract with the supervising worker:
  0 success · 1 script raised · 3 transform() missing · 4 result not tabular ·
  5 result unwritable · 6 harness usage/manifest error
"""
from __future__ import annotations

import importlib.util
import json
import sys
import traceback


def _fail(code: int, message: str) -> int:
    print(message, file=sys.stderr)
    return code


def _coerce(result, pl):  # noqa: ANN001 - polars types live in the venv
    """Turn whatever the author returned into a DataFrame, or None."""

    if result is None:
        return None
    if isinstance(result, pl.DataFrame):
        return result
    if isinstance(result, pl.LazyFrame):
        return result.collect()
    if isinstance(result, pl.Series):
        return result.to_frame()
    if isinstance(result, dict):
        try:
            return pl.DataFrame(result)
        except Exception:  # noqa: BLE001 - reported as "not tabular" below
            return None
    if isinstance(result, list):
        try:
            return pl.DataFrame(result)
        except Exception:  # noqa: BLE001
            return None
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        return _fail(6, "usage: polars_harness.py SCRIPT MANIFEST_JSON RESULT_JSON")
    script_path, manifest_path, result_path = argv[1:4]
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as exc:
        return _fail(6, f"polars_manifest_unreadable: {exc}")
    if not isinstance(manifest, dict):
        return _fail(6, "polars_manifest_not_object")
    sources = manifest.get("inputs")
    output_path = manifest.get("output_path")
    if not isinstance(sources, dict) or not isinstance(output_path, str):
        return _fail(6, "polars_manifest_incomplete")

    try:
        import polars as pl
    except ImportError as exc:
        return _fail(6, f"polars_missing_in_env: {exc}")

    inputs = {}
    try:
        for name, path in sources.items():
            inputs[str(name)] = pl.read_parquet(str(path))
    except Exception as exc:  # noqa: BLE001 - a bad input is our fault, not the author's
        return _fail(6, f"polars_input_unreadable: {exc}")

    spec = importlib.util.spec_from_file_location("agentium_polars", script_path)
    if spec is None or spec.loader is None:
        return _fail(6, "polars_script_unloadable")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except BaseException:  # noqa: BLE001 - author code, full traceback wanted
        traceback.print_exc()
        return 1

    entrypoint = getattr(module, "transform", None)
    if not callable(entrypoint):
        return _fail(
            3,
            "polars_transform_missing: define "
            "`def transform(inputs: dict[str, pl.DataFrame]) -> pl.DataFrame`",
        )

    try:
        result = entrypoint(inputs)
    except BaseException:  # noqa: BLE001
        traceback.print_exc()
        return 1

    frame = _coerce(result, pl)
    if frame is None:
        return _fail(
            4,
            "polars_result_not_tabular: transform() must return a polars DataFrame "
            "(a LazyFrame, a dict of columns or a list of row dicts also work)",
        )
    if frame.width == 0:
        return _fail(4, "polars_result_no_columns: the result has no column")

    row_limit = manifest.get("row_limit")
    if isinstance(row_limit, int) and row_limit > 0 and frame.height > row_limit:
        frame = frame.head(row_limit)

    try:
        frame.write_parquet(output_path)
    except Exception as exc:  # noqa: BLE001
        return _fail(5, f"polars_result_unwritable: {exc}")

    summary = {"rows": frame.height, "columns": frame.width, "names": list(frame.columns)}
    try:
        with open(result_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, ensure_ascii=False))
    except OSError as exc:
        return _fail(5, f"polars_summary_unwritable: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
