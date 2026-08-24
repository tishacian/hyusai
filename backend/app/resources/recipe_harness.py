"""Standalone recipe harness executed BY THE VENV PYTHON, never imported.

Contract with the author script:
  * the script must define ``main(inputs: dict) -> dict``;
  * ``inputs`` is the resolved node input (JSON object);
  * the returned dict becomes the node output (must be JSON-serializable).

The harness is deliberately stdlib-only: the venv contains the author's
dependencies, not the application. Exit codes are the machine contract with
the supervising worker:
  0 success · 1 script raised · 3 main() missing · 4 output not an object ·
  5 output not JSON-serializable · 6 harness usage/input error
"""
from __future__ import annotations

import importlib.util
import json
import sys
import traceback


def _fail(code: int, message: str) -> "int":
    print(message, file=sys.stderr)
    return code


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        return _fail(6, "usage: recipe_harness.py SCRIPT INPUT_JSON OUTPUT_JSON")
    script_path, input_path, output_path = argv[1:4]
    try:
        with open(input_path, "r", encoding="utf-8") as handle:
            inputs = json.load(handle)
    except (OSError, ValueError) as exc:
        return _fail(6, f"recipe_input_unreadable: {exc}")
    if not isinstance(inputs, dict):
        return _fail(6, "recipe_input_not_object: inputs must be a JSON object")

    spec = importlib.util.spec_from_file_location("agentium_recipe", script_path)
    if spec is None or spec.loader is None:
        return _fail(6, "recipe_script_unloadable")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except BaseException:  # noqa: BLE001 - author code, full traceback wanted
        traceback.print_exc()
        return 1

    entrypoint = getattr(module, "main", None)
    if not callable(entrypoint):
        return _fail(3, "recipe_main_missing: define `def main(inputs: dict) -> dict`")

    try:
        result = entrypoint(inputs)
    except BaseException:  # noqa: BLE001
        traceback.print_exc()
        return 1

    if result is None:
        result = {}
    if not isinstance(result, dict):
        return _fail(4, "recipe_output_not_object: main() must return a dict")
    try:
        serialized = json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        return _fail(5, f"recipe_output_not_serializable: {exc}")
    try:
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(serialized)
    except OSError as exc:
        return _fail(6, f"recipe_output_unwritable: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
