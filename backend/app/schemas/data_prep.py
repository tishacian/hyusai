"""Versioned preparation contracts; author configuration never grants data access."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PrepStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
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


class PrepOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    port: str = Field(default="out", pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=200)
    append_version_of: str | None = None


class DataPrepSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    operation: Literal[
        "prepare", "join", "union", "aggregate", "pivot", "unpivot", "split", "sample"
    ]
    steps: list[PrepStep] = Field(default_factory=list, max_length=100)
    params: dict[str, Any] = Field(default_factory=dict)
    outputs: list[PrepOutput] = Field(min_length=1, max_length=8)
    seed: int = Field(default=42, ge=0, le=2147483647)

    @model_validator(mode="after")
    def validate_outputs(self):
        import json

        if len(json.dumps(self.model_dump(), allow_nan=False).encode()) > 256000:
            raise ValueError("DATAPREP_SPEC_TOO_LARGE")
        if self.operation != "prepare" and self.steps:
            raise ValueError("DATAPREP_STEPS_REQUIRE_PREPARE")
        ports = [output.port for output in self.outputs]
        if len(ports) != len(set(ports)) or len({o.name for o in self.outputs}) != len(
            self.outputs
        ):
            raise ValueError("DATAPREP_OUTPUT_DUPLICATE")
        if self.operation != "split" and ports != ["out"]:
            raise ValueError("DATAPREP_SINGLE_OUT_REQUIRED")
        if self.operation == "split" and len(ports) < 2:
            raise ValueError("DATAPREP_SPLIT_OUTPUTS_REQUIRED")
        return self
