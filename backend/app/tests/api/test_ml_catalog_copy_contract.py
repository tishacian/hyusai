"""The training form's vocabulary must exist in both languages.

The Models surface builds its labels from the catalog the API serves: an
algorithm becomes ``models.algo.<key>``, a knob becomes
``models.studio.knob.<key>``, a tag becomes ``models.tag.<tag>``. A key with no
dictionary entry does not fail — `I18nService.t` returns the key verbatim — so
adding a knob here puts ``models.studio.knob.min_samples_split`` on screen next
to a slider, in front of whoever is watching the demo.

The same holds for a refusal: `validate_training` answers with a code the form
renders as a sentence, and a code without copy is a raw identifier shown against
a form field.

So this test reads the frontend dictionary and asserts it names everything this
service can produce. It parses the TypeScript rather than executing it, which
keeps the check free of a node toolchain.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.ml import metrics as metric_registry
from app.services.ml.families import FAMILIES, all_tasks
from app.services.tabular_ml import ALGOS, TASKS, catalog_payload

REPO_ROOT = Path(__file__).resolve().parents[4]
DICT = (
    REPO_ROOT
    / "frontend-ng"
    / "src"
    / "app"
    / "core"
    / "i18n"
    / "models.dict.ts"
)

# Both dictionaries are flat object literals of `'key': 'copy',` lines, and
# FR/EN parity inside the file is already enforced at compile time by
# `Record<keyof typeof MODELS_FR, string>`. Collecting the keys is enough.
_KEY = re.compile(r"^  '([a-z0-9_.]+)':", re.MULTILINE)

# Codes `validate_training` and `submit_training` can raise, which the studio
# renders inline against the field that caused them.
_REFUSAL_CODES = (
    "ML_TRAIN_DISABLED",
    "DATASET_NOT_READY",
    "ML_DATASET_UNPROFILED",
    "ML_TARGET_REQUIRED",
    "ML_TARGET_UNKNOWN",
    "ML_TASK_UNKNOWN",
    "ML_TARGET_NOT_NUMERIC",
    "ML_TARGET_TOO_MANY_CLASSES",
    "ML_TARGET_SINGLE_CLASS",
    "ML_FEATURE_UNKNOWN",
    "ML_FEATURES_REQUIRED",
    "ML_TOO_MANY_FEATURES",
    "ML_ROWS_INSUFFICIENT",
    "ML_ROWS_TOO_MANY",
    "ML_ALGO_UNKNOWN",
    "ML_ALGO_TASK_MISMATCH",
    "ML_SPEC_INVALID",
    "ML_FAMILY_UNAVAILABLE",
    "ML_MODEL_NOT_READY",
    "ML_MODEL_NOT_FOUND",
)

# Terminal failures the worker writes into `MLModel.error` as `CODE: detail`.
_TRAINING_ERROR_CODES = (
    "ML_TIMEOUT",
    "ML_FIT_FAILED",
    "ML_TARGET_UNUSABLE",
    "ML_ROWS_INSUFFICIENT",
    "ML_ARTIFACT_UNWRITABLE",
    "ML_HARNESS_ERROR",
    "ML_SUMMARY_MISSING",
    "ML_DATASET_UNAVAILABLE",
    "ML_ARTIFACT_EMPTY",
    "ML_TRAIN_DISABLED",
    "ML_RUNTIME_MISSING",
)
# Why a family can be offered but not trainable right now (ml.runtime).
_FAMILY_REASONS = ("no_worker", "runtime_missing", "disabled")
_CODE = re.compile(r"\"(ML_[A-Z_]+)\"")


def _family_refusal_codes() -> set[str]:
    """Every code a family validator can refuse with, read from its source.

    A family's validator is where most of its refusals live (a forecast's date
    column, its history); listing them by hand here would be the copy that
    drifts first.
    """

    codes: set[str] = set()
    for family in FAMILIES:
        if family.validator is None:
            continue
        source = Path(family.validator.__code__.co_filename).read_text(encoding="utf-8")
        # The same module declares its harness's exit codes: those are run
        # failures, phrased under models.error, not form refusals.
        codes |= set(_CODE.findall(source)) - set(family.exit_codes.values())
    return codes


def _dictionary_keys() -> set[str]:
    if not DICT.exists():  # pragma: no cover - only outside a full checkout
        pytest.skip(f"models dictionary not found at {DICT}")
    keys = set(_KEY.findall(DICT.read_text(encoding="utf-8")))
    assert len(keys) > 100, "the dictionary parser stopped matching entries"
    return keys


def test_every_algorithm_knob_and_tag_in_the_catalog_has_copy():
    keys = _dictionary_keys()
    expected: set[str] = set()
    for algo in ALGOS:
        expected.add(f"models.algo.{algo.key}")
        # The hint is what tells an author why they would pick this family; a
        # picker card without one is four names and no argument.
        expected.add(f"models.algo.{algo.key}.hint")
        for tag in algo.tags:
            expected.add(f"models.tag.{tag}")
        for knob in algo.knobs:
            expected.add(f"models.studio.knob.{knob.key}")
            # A choice renders as its own option label.
            for choice in knob.choices:
                expected.add(f"models.studio.knob.{knob.key}.{choice}")
    missing = sorted(expected - keys)
    assert not missing, (
        "the training form builds these keys from the algorithm catalog, so each "
        f"one renders as its own identifier on screen: {missing}"
    )


def test_every_task_the_catalog_offers_has_a_name_and_a_hint():
    keys = _dictionary_keys()
    expected = {f"models.task.{task}" for task in all_tasks()} | {
        f"models.task.{task}.hint" for task in all_tasks()
    }
    assert not sorted(expected - keys)


def test_every_family_metric_and_unavailability_reason_has_copy():
    """The form names a family, explains why it is greyed out, and labels every
    score the registry can rank — including the forecasting errors."""

    keys = _dictionary_keys()
    expected = {f"models.family.{family.key}" for family in FAMILIES}
    expected |= {f"models.family.reason.{reason}" for reason in _FAMILY_REASONS}
    for spec in metric_registry.METRICS:
        expected |= {f"models.metric.{spec.key}", f"models.metric.{spec.key}.hint"}
    missing = sorted(expected - keys)
    assert not missing, f"rendered as raw identifiers: {missing}"


def test_every_refusal_and_failure_code_has_copy():
    keys = _dictionary_keys()
    expected = {f"models.refusal.{code.lower()}" for code in (*_REFUSAL_CODES, *_family_refusal_codes())}
    expected |= {f"models.error.{code.lower()}" for code in _TRAINING_ERROR_CODES}
    # A family's harness names its own exits (a series with gaps, too little
    # history), and the worker writes them into the row like any other failure.
    expected |= {f"models.error.{code.lower()}" for family in FAMILIES for code in family.exit_codes.values()}
    missing = sorted(expected - keys)
    assert not missing, (
        "these codes reach the UI as coded refusals and would be shown raw: "
        f"{missing}"
    )


def test_every_spec_field_and_choice_a_family_declares_has_copy():
    """A forecast's form is built from its family's spec fields: each one is a
    label, a hint, and one label per choice (frequencies lowercased, since a
    dictionary key is)."""

    keys = _dictionary_keys()
    expected: set[str] = set()
    for family in FAMILIES:
        for field in family.spec_fields:
            expected |= {f"models.spec.{field.key}", f"models.spec.{field.key}.hint"}
            if field.kind in {"enum", "column_roles"}:
                expected |= {f"models.spec.{field.key}.{choice.lower()}" for choice in field.choices}
    missing = sorted(expected - keys)
    assert not missing, f"rendered as raw identifiers: {missing}"


def test_the_frontend_lists_every_refusal_and_failure_a_family_can_produce():
    """The view-model only phrases codes it lists; an unlisted one is shown as
    the server's English sentence in the middle of a French form."""

    source = (REPO_ROOT / "frontend-ng" / "src" / "app" / "features" / "models" / "models.vm.ts").read_text(
        encoding="utf-8"
    )
    refusals = source[source.index("export const REFUSAL_CODES") :]
    refusals = refusals[: refusals.index("] as const")]
    errors = source[source.index("export const TRAINING_ERROR_CODES") :]
    errors = errors[: errors.index("] as const")]
    missing = sorted(code for code in _family_refusal_codes() if f"'{code}'" not in refusals)
    missing += sorted(
        code for family in FAMILIES for code in family.exit_codes.values() if f"'{code}'" not in errors
    )
    assert not missing, f"codes the studio would not phrase: {missing}"


def test_the_catalog_payload_is_shaped_the_way_the_form_reads_it():
    """A guard on the contract the studio's view-model is typed against."""

    payload = catalog_payload()
    assert set(payload) >= {"enabled", "tasks", "algos", "limits", "defaults", "families", "metrics"}
    assert payload["tasks"] == list(all_tasks())
    assert set(TASKS) <= set(payload["tasks"])
    for family in payload["families"]:
        assert set(family) >= {"key", "tasks", "runtime", "serving", "available", "spec_fields"}
        assert family["serving"] in {"in_process", "remote"}
    assert {metric["key"] for metric in payload["metrics"]} >= {"roc_auc", "r2", "mae", "mase"}
    assert all(metric["direction"] in {"max", "min", "none"} for metric in payload["metrics"])
    assert payload["defaults"]["algo"] in {algo.key for algo in ALGOS}
    assert payload["defaults"]["task"] in TASKS
    assert set(payload["limits"]) == {
        "min_rows",
        "max_rows",
        "max_features",
        "max_classes",
        "timeout_s",
    }
    for algo in payload["algos"]:
        assert set(algo) == {"key", "tasks", "estimators", "scale", "tags", "knobs"}
        assert algo["tasks"], f"{algo['key']} claims no task"
        for knob in algo["knobs"]:
            assert knob["kind"] in {"int", "float", "enum", "bool", "int_list"}
            if knob["kind"] in {"int", "float"}:
                assert set(knob) >= {"key", "kind", "default", "min", "max", "step"}
                # The slider mirrors these bounds to stay honest mid-drag, so a
                # default outside them would render a thumb the form then moves.
                assert knob["min"] <= knob["default"] <= knob["max"]
            elif knob["kind"] == "enum":
                assert knob["default"] in knob["choices"]
            elif knob["kind"] == "int_list":
                assert 0 < len(knob["default"]) <= knob["max_items"]
