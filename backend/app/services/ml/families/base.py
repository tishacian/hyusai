"""What a model family declares, and the contract its harness keeps.

A family is the unit the platform routes on: which tasks it trains, which image
(``runtime``) trains and serves it, which Celery queue reaches that image,
whether its models answer inside the API process or in their worker, which
modules must be importable for a fit to start, and which problem definition
(``spec``) a training request carries beyond target, features and knobs.

Harness contract, the same for every family:

* invoked as ``[python, harness, MANIFEST, RESULT]`` by ``supervise_harness``
  on the interpreter of the image that consumed the task;
* the manifest always carries ``family``, ``task``, ``data_path``,
  ``model_dir``, ``progress_path``, ``report_path``, ``random_state``,
  ``params`` and ``spec``, plus what the family adds;
* progress lines are ``step`` or ``step:count`` (``fitting:6903``,
  ``backtesting:2/5``), steps drawn from the family's own list;
* exit 0 writes ``result.json`` with ``metrics`` (``primary`` and ``scores``),
  ``signature`` and ``input_example``; exits 1–5 are the shared failure codes
  and a family may name them more precisely.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings

SPEC_FIELD_KINDS = (
    "column",
    "columns",
    "int",
    "float",
    "enum",
    "bool",
    "column_roles",
    "int_list",
    "artifact",
)


class SpecInvalid(ValueError):
    """A training ``spec`` the family cannot read; ``field`` names the culprit."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


@dataclass(frozen=True, slots=True)
class SpecField:
    """One field of a family's problem definition, rendered by the form.

    ``column`` and ``columns`` name dataset columns (restricted to
    ``column_kinds`` when set); ``column_roles`` maps columns to one of
    ``choices`` (a covariate known in the future, only in the past, static);
    ``when`` shows the field only while another field holds one of the listed
    values, e.g. ``{"shape": ("panel",)}``.
    """

    key: str
    kind: str
    required: bool = False
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    column_kinds: tuple[str, ...] = ()
    max_items: int = 0
    when: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in SPEC_FIELD_KINDS:
            raise ValueError(f"spec field {self.key}: unknown kind {self.kind!r}")

    def parse(self, value: Any) -> Any:
        kind = self.kind
        if kind == "artifact":
            import re

            if (
                not isinstance(value, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value) is None
            ):
                raise SpecInvalid(self.key, "expected an artifact identifier")
            return value
        if kind == "column":
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise SpecInvalid(self.key, "expected one column name")
            return value.strip()
        if kind == "columns":
            if not isinstance(value, list) or not all(
                isinstance(v, str) and v.strip() for v in value
            ):
                raise SpecInvalid(self.key, "expected a list of column names")
            names = list(dict.fromkeys(v.strip() for v in value))
            if self.max_items and len(names) > self.max_items:
                raise SpecInvalid(self.key, f"at most {self.max_items} columns")
            return names
        if kind == "column_roles":
            if not isinstance(value, dict) or not all(
                isinstance(k, str) and k.strip() and v in self.choices for k, v in value.items()
            ):
                raise SpecInvalid(self.key, f"expected column → one of {list(self.choices)}")
            if self.max_items and len(value) > self.max_items:
                raise SpecInvalid(self.key, f"at most {self.max_items} columns")
            return {k.strip(): v for k, v in value.items()}
        if kind == "int_list":
            if (
                not isinstance(value, list)
                or not value
                or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
            ):
                raise SpecInvalid(self.key, "expected a list of whole numbers")
            items = sorted(set(value))
            if self.max_items and len(items) > self.max_items:
                raise SpecInvalid(self.key, f"at most {self.max_items} values")
            if (self.minimum is not None and items[0] < self.minimum) or (
                self.maximum is not None and items[-1] > self.maximum
            ):
                raise SpecInvalid(self.key, f"expected values in [{self.minimum}, {self.maximum}]")
            return items
        if kind == "enum":
            if value not in self.choices:
                raise SpecInvalid(self.key, f"expected one of {list(self.choices)}")
            return value
        if kind == "bool":
            if not isinstance(value, bool):
                raise SpecInvalid(self.key, "expected true or false")
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SpecInvalid(self.key, "expected a number")
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise SpecInvalid(self.key, "expected a finite number")
        if kind == "int" and float(value) != int(value):
            raise SpecInvalid(self.key, "expected a whole number")
        number = int(value) if kind == "int" else float(value)
        if (self.minimum is not None and number < self.minimum) or (
            self.maximum is not None and number > self.maximum
        ):
            raise SpecInvalid(self.key, f"expected a value in [{self.minimum}, {self.maximum}]")
        return number

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {"key": self.key, "kind": self.kind, "required": self.required}
        for name, value in (
            ("default", self.default),
            ("min", self.minimum),
            ("max", self.maximum),
            ("max_items", self.max_items or None),
        ):
            if value is not None:
                body[name] = value
        if self.choices:
            body["choices"] = list(self.choices)
        if self.column_kinds:
            body["column_kinds"] = list(self.column_kinds)
        if self.when:
            body["when"] = {key: list(values) for key, values in self.when}
        return body


@dataclass(frozen=True, slots=True)
class Family:
    key: str
    tasks: tuple[str, ...]
    # The image that trains and serves this family: "worker" is the general
    # Celery worker every deployment runs; any other name is an image that
    # announces itself with a heartbeat (see ml.runtime).
    runtime: str
    # Settings attribute naming the training queue; empty means the default.
    queue_setting: str
    serving: str  # in_process | remote
    required_modules: tuple[str, ...]
    harness: Path
    spec_fields: tuple[SpecField, ...] = ()
    steps: tuple[str, ...] = ()
    exit_codes: dict[int, str] = field(default_factory=dict)
    # Validates a request for a family other than tabular, whose checks live in
    # tabular_ml.validate_training: called with the dataset, the resolved task
    # and target, the request's fields and the parsed ``spec``, it returns a
    # TrainingSpec or raises the coded refusal the form renders.
    validator: Callable[..., Any] | None = None
    # Settings attribute naming the queue a remote family answers on; empty
    # for a family served in the API process.
    serve_queue_setting: str = ""

    def train_queue(self) -> str:
        queue = str(getattr(settings, self.queue_setting, "") or "").strip()
        return queue or settings.celery_task_default_queue

    def serve_queue(self) -> str:
        return (
            str(getattr(settings, self.serve_queue_setting, "") or "").strip()
            if self.serve_queue_setting
            else ""
        )

    def missing_modules(self) -> list[str]:
        """Modules a fit needs that this interpreter cannot import."""

        missing = []
        for module in self.required_modules:
            try:
                if find_spec(module) is None:
                    missing.append(module)
            except (ImportError, ValueError):
                missing.append(module)
        return missing

    def parse_spec(
        self, raw: Any, *, task: str | None = None, warnings: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """The request's ``spec``, checked against this family's fields.

        Unknown keys are refused rather than dropped: a field the form believes
        it set and the fit silently ignored is how a problem definition and a
        trained model come to disagree. Fields are checked here for shape only;
        whether a named column exists is the family's validation, which has the
        dataset.

        A resolved ``task`` supplies visibility context without becoming a spec
        field. In that mode hidden options are removed before parsing: changing
        a Flow target must not leave an incompatible option blocking training.
        Callers without that context keep the existing family parsing contract.
        """

        if raw in (None, {}):
            raw = {}
        if not isinstance(raw, dict):
            raise SpecInvalid("spec", "expected an object")
        if len(json.dumps(raw, default=str)) > 8192:
            raise SpecInvalid("spec", "the problem definition is too large")
        fields = {spec_field.key: spec_field for spec_field in self.spec_fields}
        unknown = sorted(set(raw) - set(fields))
        if unknown:
            raise SpecInvalid(unknown[0], f"{self.key} models take no '{unknown[0]}'")
        values = {key: spec_field.default for key, spec_field in fields.items()}
        values.update({key: value for key, value in raw.items() if value is not None})
        if task is not None:
            values["task"] = task
        parsed: dict[str, Any] = {}
        for key, spec_field in fields.items():
            if task is not None and not self._shown(spec_field, values):
                if key in raw and raw[key] is not None and warnings is not None:
                    warnings.append({"code": "ML_SPEC_FIELD_IGNORED", "field": key, "task": task})
                continue
            if key in raw and raw[key] is not None:
                parsed[key] = spec_field.parse(raw[key])
            elif spec_field.default is not None:
                parsed[key] = spec_field.default
            elif spec_field.required and self._shown(
                spec_field, values if task is not None else {**raw, **parsed}
            ):
                raise SpecInvalid(key, f"'{key}' is required")
        return parsed

    @staticmethod
    def _shown(spec_field: SpecField, values: dict[str, Any]) -> bool:
        return all(values.get(key) in allowed for key, allowed in spec_field.when)

    def payload(
        self, *, available: bool, reason: str | None, serve_available: bool | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "key": self.key,
            "tasks": list(self.tasks),
            "runtime": self.runtime,
            "serving": self.serving,
            "available": available,
            "spec_fields": [spec_field.payload() for spec_field in self.spec_fields],
        }
        if reason:
            body["reason"] = reason
        if serve_available is not None:
            body["serve_available"] = serve_available
        return body
