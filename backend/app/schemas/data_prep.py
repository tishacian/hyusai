"""Versioned preparation contracts; author configuration never grants data access."""

import json
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PrepStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default="", max_length=64)
    enabled: bool = True
    comment: str = Field(default="", max_length=500)
    action: Literal[
        "select",
        "drop",
        "rename",
        "cast",
        "fill_null",
        "drop_null",
        "filter",
        "derive",
        "sort",
        "deduplicate",
        "trim",
        "upper",
        "lower",
        "replace",
        "date_format",
        "hash",
        "select_columns",
        "drop_columns",
        "rename_columns",
        "move_columns",
        "copy_column",
        "concat_columns",
        "normalize_column_names",
        "add_column",
        "parse_date",
        "format_date",
        "from_epoch",
        "parse_number",
        "to_boolean",
        "drop_nulls",
        "fill_nulls",
        "filter_rows",
        "filter_range",
        "filter_expression",
        "flag_rows",
        "text_transform",
        "replace_values",
        "split_column",
        "extract_regex",
        "count_occurrences",
        "substring",
        "pad",
        "length",
        "negate_boolean",
        "bin_numeric",
        "bin",
        "formula",
        "conditional_column",
        "map_values",
        "window",
        "mask",
        "dedup",
        "round",
        "math",
        "extract_date_parts",
        "date_diff",
        "date_add",
        "truncate_date",
        "convert_timezone",
        "scale",
    ]
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def read_kind(cls, value):
        if isinstance(value, dict) and "kind" in value:
            value = dict(value)
            kind = value.pop("kind")
            if "action" in value and value["action"] != kind:
                raise ValueError("DATAPREP_STEP_KIND_CONFLICT")
            value["action"] = kind
        return value

    @property
    def kind(self):
        return self.action

    def canonical(self):
        value = self.model_dump(mode="json")
        value["kind"] = value.pop("action")
        return value


class PrepOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    port: str = Field(default="out", pattern=r"^[a-z][a-z0-9_]{0,30}$")
    name: str = Field(min_length=1, max_length=200)
    append_version_of: str | None = None


class DataPrepSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    operation: Literal[
        "prepare", "join", "union", "aggregate", "pivot", "unpivot", "split", "sample"
    ]
    steps: list[PrepStep] = Field(default_factory=list, max_length=200)
    params: dict[str, Any] = Field(default_factory=dict)
    outputs: list[PrepOutput] = Field(min_length=1, max_length=8)
    seed: int = Field(default=42, ge=0, le=2147483647)

    @model_validator(mode="before")
    @classmethod
    def read_v1(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        if value.get("version", 1) != 1:
            raise ValueError("DATAPREP_SPEC_VERSION")
        raw_params = value.get("params", {})
        if not isinstance(raw_params, dict):
            raise ValueError("DATAPREP_PARAMS_INVALID")
        params = dict(raw_params)
        if value.get("operation") == "prepare" and "steps" in params:
            steps = params.pop("steps")
            if "steps" in value and value["steps"] != steps:
                raise ValueError("DATAPREP_STEPS_CONFLICT")
            value["steps"] = steps
        if "seed" in params:
            if "seed" in value and value["seed"] != params["seed"]:
                raise ValueError("DATAPREP_SEED_CONFLICT")
            value["seed"] = params.pop("seed")
        value["params"] = params
        return value

    def canonical(self):
        params = dict(self.params)
        if self.operation == "prepare":
            params["steps"] = [step.canonical() for step in self.steps]
        if self.operation in {"split", "sample"}:
            params["seed"] = self.seed
        return {"version": self.version, "operation": self.operation, "params": params}

    @model_validator(mode="after")
    def validate_outputs(self):
        from app.core.config import settings

        if len(self.steps) > settings.dataops_max_steps:
            raise ValueError("DATAPREP_STEPS_LIMIT")
        if len(json.dumps(self.model_dump(), allow_nan=False).encode()) > 256000:
            raise ValueError("DATAPREP_SPEC_TOO_LARGE")
        if self.operation != "prepare" and self.steps:
            raise ValueError("DATAPREP_STEPS_REQUIRE_PREPARE")
        ports = [output.port for output in self.outputs]
        if any(not output.name.strip() for output in self.outputs):
            raise ValueError("DATAPREP_OUTPUT_NAME_REQUIRED")
        if len(ports) != len(set(ports)) or len({o.name for o in self.outputs}) != len(
            self.outputs
        ):
            raise ValueError("DATAPREP_OUTPUT_DUPLICATE")
        if self.operation != "split" and ports != ["out"]:
            raise ValueError("DATAPREP_SINGLE_OUT_REQUIRED")
        if self.operation == "split" and len(ports) < 2:
            raise ValueError("DATAPREP_SPLIT_OUTPUTS_REQUIRED")
        for index, step in enumerate(self.steps):
            if not step.id:
                # Read migration is repeatable: opening an old draft never changes its identity.
                step.id = str(
                    uuid5(
                        NAMESPACE_URL,
                        json.dumps(
                            [index, step.action, step.params], sort_keys=True, allow_nan=False
                        ),
                    )
                )
        if len({step.id for step in self.steps}) != len(self.steps):
            raise ValueError("DATAPREP_STEP_ID_DUPLICATE")
        return self


def bind_spec(spec: dict | DataPrepSpec, outputs=None) -> DataPrepSpec:
    """Bind graph-owned output names without modifying an authored draft."""
    if spec is not None and not isinstance(spec, (dict, DataPrepSpec)):
        raise ValueError("DATAPREP_SPEC_INVALID")
    value = spec.model_dump(mode="json") if isinstance(spec, DataPrepSpec) else dict(spec or {})
    if outputs is not None:
        if not isinstance(outputs, list):
            raise ValueError("DATAPREP_OUTPUTS_INVALID")
        outputs = [o.model_dump(mode="json") if isinstance(o, PrepOutput) else o for o in outputs]
        if value.get("outputs") and value["outputs"] != outputs:
            raise ValueError("DATAPREP_OUTPUTS_CONFLICT")
        value["outputs"] = outputs
    return DataPrepSpec.model_validate(value)
