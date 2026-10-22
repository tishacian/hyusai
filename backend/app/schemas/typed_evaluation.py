"""Closed contracts for evidence-bound evaluation; quality is not confidence."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class TypedQuestion(StrictModel):
    key: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
    question: str = Field(min_length=1, max_length=2000)
    type: Literal["boolean", "choice", "multi_choice", "score", "probability"]
    choices: list[str] = Field(default_factory=list, max_length=100)
    minimum: float | None = None
    maximum: float | None = None
    required: bool = True
    requires_evidence: bool = True
    acceptable_values: list[str | bool] | None = Field(default=None, max_length=100)
    accept_minimum: float | None = None
    accept_maximum: float | None = None

    @field_validator("question")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("The question must contain text.")
        return value

    @model_validator(mode="after")
    def compatible_contract(self):
        if any(not item.strip() or len(item) > 120 for item in self.choices):
            raise ValueError("Choices must be nonempty and at most 120 characters.")
        if len(set(self.choices)) != len(self.choices):
            raise ValueError("Choices must be distinct.")
        numeric = self.type in {"score", "probability"}
        if self.type in {"choice", "multi_choice"}:
            if len(self.choices) < 2:
                raise ValueError("At least two choices are required.")
        elif self.choices:
            raise ValueError("Only choice questions declare choices.")
        if self.type == "score" and (self.minimum is None or self.maximum is None):
            raise ValueError("A score requires explicit bounds.")
        if self.type == "probability":
            if self.minimum not in (None, 0) or self.maximum not in (None, 1):
                raise ValueError("A probability is bounded by zero and one.")
        if not numeric and any(
            v is not None
            for v in (self.minimum, self.maximum, self.accept_minimum, self.accept_maximum)
        ):
            raise ValueError("Only numeric questions declare numeric bounds.")
        low, high = (0, 1) if self.type == "probability" else (self.minimum, self.maximum)
        if numeric:
            if low > high:
                raise ValueError("Minimum must not exceed maximum.")
            if self.acceptable_values is not None:
                raise ValueError("Numeric criteria use acceptance bounds.")
            for bound in (self.accept_minimum, self.accept_maximum):
                if bound is not None and not low <= bound <= high:
                    raise ValueError("Acceptance bounds must lie within the scale.")
            if (
                self.accept_minimum is not None
                and self.accept_maximum is not None
                and self.accept_minimum > self.accept_maximum
            ):
                raise ValueError("Acceptance bounds are reversed.")
        if self.acceptable_values is not None:
            allowed = [True, False] if self.type == "boolean" else self.choices
            if any(value not in allowed for value in self.acceptable_values):
                raise ValueError("An acceptance value is not a declared choice.")
            if self.type != "multi_choice" and not self.acceptable_values:
                raise ValueError("An acceptance set must not be empty.")
        return self


class JudgeEvidence(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$")
    text: str = Field(default="", max_length=32000)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    kind: Literal["text", "image"] = "text"
    asset_ref: dict[str, Any] | None = None


class RunEvidenceSource(StrictModel):
    """A published selector, never a caller-supplied excerpt or invocation id."""

    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$")
    skill_slug: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,159}$")
    node_id: str | None = Field(default=None, min_length=1, max_length=160)
    paths: list[str] = Field(min_length=1, max_length=32)
    required: Literal[True] = True

    @field_validator("paths")
    @classmethod
    def explicit_json_pointers(cls, paths):
        import re

        if len(set(paths)) != len(paths) or any(
            not path.startswith("/")
            or len(path) > 500
            or path == "/"
            or re.search(r"~(?![01])", path)
            for path in paths
        ):
            raise ValueError("Select distinct, non-root JSON pointers into output fields.")
        return paths


class RunEvidenceNativeRef(StrictModel):
    kind: Literal["dataset", "model", "document_set"]
    id: str = Field(min_length=1, max_length=36)


class RunEvidenceSnapshot(StrictModel):
    sources: list[RunEvidenceSource] = Field(min_length=1, max_length=16)
    native_refs: list[RunEvidenceNativeRef] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def unique_sources(self):
        if len({source.id for source in self.sources}) != len(self.sources):
            raise ValueError("Evidence source identifiers must be distinct.")
        if not any(source.required for source in self.sources):
            raise ValueError("At least one evidence source must be required.")
        if len({(ref.kind, ref.id) for ref in self.native_refs}) != len(self.native_refs):
            raise ValueError("Native references must be distinct.")
        return self


class JudgeBudget(StrictModel):
    max_calls: int = Field(ge=1, le=10000)
    max_tokens: int = Field(ge=1, le=100_000_000)
    max_cost_usd: float = Field(gt=0, le=10000)
    max_output_tokens: int = Field(default=2048, ge=64, le=8192)
    timeout_s: int = Field(default=45, ge=1, le=120)
    max_prompt_bytes: int = Field(default=32000, ge=1024, le=128000)


class JudgeTariff(StrictModel):
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    input_per_million: float = Field(ge=0, le=1000)
    output_per_million: float = Field(ge=0, le=1000)
    currency: Literal["USD"] = "USD"
    reference: str = Field(min_length=1, max_length=300)


class TypedEvaluationInput(StrictModel):
    batch_key: str = Field(min_length=1, max_length=160)
    request_key: str = Field(min_length=1, max_length=160)
    subject_ref: str = Field(min_length=1, max_length=300)
    rubric_id: str = Field(min_length=1, max_length=160)
    rubric_version: str = Field(min_length=1, max_length=60)
    questions: list[TypedQuestion] = Field(min_length=1, max_length=32)
    evidence: list[JudgeEvidence] = Field(min_length=1, max_length=64)
    budget: JudgeBudget
    tariff: JudgeTariff

    @model_validator(mode="after")
    def unique_keys(self):
        if len({q.key for q in self.questions}) != len(self.questions):
            raise ValueError("Question keys must be unique.")
        if len({e.id for e in self.evidence}) != len(self.evidence):
            raise ValueError("Evidence identifiers must be unique.")
        if not any(q.required for q in self.questions):
            raise ValueError("At least one question must be required.")
        return self


def compile_question_schema(questions: list[TypedQuestion | dict]) -> dict:
    """Provider schema; every declared question has its own actual value type."""
    parsed = [
        q if isinstance(q, TypedQuestion) else TypedQuestion.model_validate(q) for q in questions
    ]
    if not parsed or len(parsed) > 32 or len({q.key for q in parsed}) != len(parsed):
        raise ValueError("Declare one to 32 distinct questions.")
    properties = {}
    for question in parsed:
        if question.type == "boolean":
            value = {"type": "boolean"}
        elif question.type == "choice":
            value = {"type": "string", "enum": question.choices}
        elif question.type == "multi_choice":
            value = {
                "type": "array",
                "items": {"type": "string", "enum": question.choices},
                "uniqueItems": True,
                "maxItems": len(question.choices),
            }
        else:
            low, high = (
                (0, 1) if question.type == "probability" else (question.minimum, question.maximum)
            )
            value = {"type": "number", "minimum": low, "maximum": high}
        properties[question.key] = {
            "type": "object",
            "additionalProperties": False,
            "required": ["status", "value", "reason", "explanation", "evidence"],
            "properties": {
                "status": {"type": "string", "enum": ["answered", "abstained"]},
                "value": {"anyOf": [value, {"type": "null"}]},
                "reason": {
                    "type": ["string", "null"],
                    "enum": [
                        None,
                        "insufficient_evidence",
                        "ambiguous",
                        "out_of_scope",
                        "unsupported_modality",
                    ],
                },
                "explanation": {"type": "string", "minLength": 1, "maxLength": 1200},
                "evidence": {
                    "type": "array",
                    "maxItems": 16,
                    "items": {
                        "anyOf": [
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["evidence_id", "start", "end", "quote"],
                                "properties": {
                                    "evidence_id": {"type": "string"},
                                    "start": {"type": "integer", "minimum": 0},
                                    "end": {"type": "integer", "minimum": 1},
                                    "quote": {"type": "string", "minLength": 1, "maxLength": 2000},
                                },
                            },
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "required": [
                                    "kind",
                                    "evidence_id",
                                    "image_sha256",
                                    "region",
                                    "description",
                                ],
                                "properties": {
                                    "kind": {"type": "string", "enum": ["image"]},
                                    "evidence_id": {"type": "string"},
                                    "image_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                                    "region": {
                                        "anyOf": [
                                            {
                                                "type": "array",
                                                "minItems": 4,
                                                "maxItems": 4,
                                                "items": {
                                                    "type": "number",
                                                    "minimum": 0,
                                                    "maximum": 1,
                                                },
                                            },
                                            {"type": "null"},
                                        ]
                                    },
                                    "description": {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": 1200,
                                    },
                                },
                            },
                        ]
                    },
                },
            },
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["answers"],
        "properties": {
            "answers": {
                "type": "object",
                "additionalProperties": False,
                "required": list(properties),
                "properties": properties,
            }
        },
    }


def compile_typed_output_schema(questions: list[TypedQuestion | dict]) -> dict:
    """Tighten the catalog envelope for a frozen Flow's static questions."""
    answers = compile_question_schema(questions)["properties"]["answers"]
    for answer in answers["properties"].values():
        answer["properties"]["status"]["enum"].append("invalid")
        answer["properties"]["reason"] = {"type": ["string", "null"]}
        answer["properties"]["confidence"] = {
            "type": ["number", "null"],
            "minimum": 0,
            "maximum": 1,
        }
        answer["required"].append("confidence")
    return {
        "type": "object",
        "required": [
            "schema_version",
            "evaluation_id",
            "answers",
            "status",
            "disposition",
            "confidence",
            "quality_status",
            "coverage",
        ],
        "properties": {
            "schema_version": {"const": 2},
            "evaluation_id": {"type": "string"},
            "answers": answers,
            "status": {"enum": ["completed", "partial", "failed"]},
            "disposition": {"enum": ["review"]},
            "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
            "quality_status": {"enum": ["passed", "failed", "unassessed"]},
            "coverage": {"type": "object"},
        },
        "additionalProperties": True,
    }


class CalibrationContext(StrictModel):
    source: str = Field(min_length=1, max_length=120)
    language: str = Field(min_length=2, max_length=40)
    task: Literal["j2450_translation", "typed_questions"]


class CalibrationCaseFromEvaluation(StrictModel):
    evaluation_id: str = Field(min_length=1, max_length=36)
    logical_key: str = Field(min_length=1, max_length=120)
    document_family: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=1, max_length=120)
    language: str = Field(min_length=2, max_length=40)
    task: Literal["j2450_translation", "typed_questions"]

    @field_validator("logical_key", "document_family", "source", "language")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("A declared value must not be blank.")
        return value.strip()


class CalibrationModel(StrictModel):
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    returned_model: str = Field(min_length=1, max_length=200)


class CalibrationUnit(StrictModel):
    key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    document_family: str = Field(min_length=1, max_length=160)
    partition: Literal["dev", "calibration", "test"]
    asset_ref: dict[str, Any]


class CalibrationPolicy(StrictModel):
    # No invented service thresholds: a human must declare each gate.
    min_calibration_units: int = Field(ge=2, le=1000)
    min_test_units: int = Field(ge=2, le=1000)
    min_calibration_families: int = Field(ge=2, le=1000)
    min_test_families: int = Field(ge=2, le=1000)
    min_critical_positives: int = Field(ge=1, le=1000)
    min_precision: float = Field(ge=0, le=1)
    min_recall: float = Field(ge=0, le=1)
    max_critical_miss_rate: float = Field(ge=0, le=1)
    min_coverage: float = Field(ge=0, le=1)
    min_confidence_lower: float = Field(ge=0, le=1)
    max_brier: float | None = Field(ge=0, le=1)
    max_ece: float | None = Field(ge=0, le=1)
    critical_labels: dict[str, list[str | bool]]
    numeric_tolerances: dict[str, float] = Field(default_factory=dict)


class CalibrationCorpus(StrictModel):
    logical_key: str = Field(min_length=1, max_length=160)
    rubric_id: str = Field(min_length=1, max_length=160)
    rubric_version: str = Field(min_length=1, max_length=60)
    questions: list[TypedQuestion] = Field(min_length=1, max_length=32)
    model: CalibrationModel
    context: CalibrationContext
    units: list[CalibrationUnit] = Field(min_length=4, max_length=1000)
    policy: CalibrationPolicy


class HumanAnnotation(StrictModel):
    unit_key: str
    values: dict[str, Any]
    # Observed binary outcomes for probability questions, independently annotated.
    outcomes: dict[str, bool] = Field(default_factory=dict)
    note: str = Field(min_length=1, max_length=2000)
    adjudication: bool = False


class CalibrationPrediction(StrictModel):
    unit_key: str
    evaluation_id: str = Field(min_length=1, max_length=36)


class VisionRouteDefinition(StrictModel):
    logical_key: str = Field(min_length=1, max_length=120)
    provider: Literal["openai", "azure_openai"]
    model: str = Field(min_length=1, max_length=200)
    returned_model: str = Field(min_length=1, max_length=200)
    max_images: int = Field(ge=1, le=16)
    max_image_bytes: int = Field(ge=1, le=8_000_000)
    max_total_bytes: int = Field(ge=1, le=32_000_000)
    max_image_tokens: int = Field(ge=1, le=100_000)
    max_pixels: int = Field(ge=1, le=40_000_000)


class VisionRouteQualification(StrictModel):
    verification_ref: dict[str, Any]
    note: str = Field(min_length=20, max_length=2000)
