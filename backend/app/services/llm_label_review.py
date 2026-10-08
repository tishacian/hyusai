"""Human review of immutable LLM labels through the existing HITL Decision.

Approval and publication share the caller's transaction. Original LLM labels
stay in the parent dataset, never in a feature column of the reviewed table.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
import tempfile
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.decision import Decision
from app.models.tabular import TabularDataset
from app.models.workspace_job import WorkspaceJob
from app.services.tabular_datasets import TabularError, dataset_reference, get_dataset, materialize

PROMPT_KIND = "review_dataset_labels"
PRODUCER = "llm_label_review_v1"
LABEL_PRODUCER = "llm_label_dataset_v1"
MAX_ROWS = 5000
MAX_BYTES = 32 * 1024 * 1024


class LabelCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    row_id: int = Field(ge=0, lt=MAX_ROWS)
    label: str = Field(min_length=1, max_length=100)


class LabelReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dataset_id: str = Field(min_length=1, max_length=36)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    acknowledged: Literal[True]
    corrections: list[LabelCorrection] = Field(default_factory=list, max_length=MAX_ROWS)


def _refuse(code, message, status_code=409):
    raise TabularError(code=code, message=message, status_code=status_code)


def _snapshot(dataset):
    import polars as pl

    if dataset.status != "ready" or not 0 < (dataset.row_count or 0) <= MAX_ROWS:
        _refuse("LABEL_REVIEW_SOURCE_UNAVAILABLE", "Review requires a ready labeling dataset of at most 5,000 rows.")
    if (dataset.size_bytes or 0) > MAX_BYTES:
        _refuse("LABEL_REVIEW_SOURCE_UNAVAILABLE", "The labeling dataset exceeds the review size limit.")
    with tempfile.TemporaryDirectory(prefix="label-review-") as scratch:
        path = materialize(dataset, Path(scratch) / "source.parquet")
        if path.stat().st_size > MAX_BYTES:
            _refuse("LABEL_REVIEW_SOURCE_UNAVAILABLE", "The labeling dataset exceeds the review size limit.")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        frame = pl.scan_parquet(path).head(MAX_ROWS + 1).collect()
    if frame.height != dataset.row_count:
        _refuse("LABEL_REVIEW_SOURCE_CHANGED", "The labeling dataset no longer matches its recorded rows.")
    return frame, digest


def _source(db, workspace_id, dataset_id):
    dataset = get_dataset(db, workspace_id=workspace_id, dataset_id=dataset_id)
    metadata = (dataset.lineage_json or {}).get("labeling") or {}
    job = db.query(WorkspaceJob).filter_by(id=metadata.get("job_id"), workspace_id=workspace_id,
                                         kind="llm_label_dataset").first()
    if (dataset.source != "generated" or dataset.produced_by != LABEL_PRODUCER
            or job is None or job.status != "completed" or (job.result or {}).get("output_id") != dataset.id):
        _refuse("LABEL_REVIEW_SOURCE_INVALID", "Select a dataset produced by a completed LLM labeling operation.")
    return dataset, job


def make_binding(db, *, workspace_id, dataset_id):
    """Freeze the exact dataset shown at this human gate, before it pauses."""
    dataset, job = _source(db, workspace_id, dataset_id)
    frame, digest = _snapshot(dataset)
    spec = job.input_ref["spec"]
    column = spec["label_column"]
    if column not in frame.columns or any(label not in spec["labels"] for label in frame[column].to_list()):
        _refuse("LABEL_REVIEW_SOURCE_INVALID", "The original labels do not match the labeling contract.")
    return {"dataset_id": dataset.id, "dataset_name": dataset.name, "source_version": dataset.version,
            "sha256": digest, "label_column": column, "labels": spec["labels"],
            "text_columns": spec["text_columns"], "total": frame.height}


def _bound_source(db, decision):
    binding = (decision.rationale or {}).get("label_review")
    if not isinstance(binding, dict) or not binding.get("dataset_id"):
        _refuse("LABEL_REVIEW_NOT_PENDING", "This decision is not a dataset label review.")
    source, job = _source(db, decision.workspace_id, binding["dataset_id"])
    frame, digest = _snapshot(source)
    if digest != binding["sha256"] or source.version != binding["source_version"]:
        _refuse("LABEL_REVIEW_SOURCE_CHANGED", "The dataset changed after the review gate opened.")
    return binding, source, job, frame


def review_page(db, decision, *, offset=0, limit=50):
    if decision.status != "proposed":
        _refuse("LABEL_REVIEW_NOT_PENDING", "This review decision has already been resolved.")
    binding, _, _, frame = _bound_source(db, decision)
    columns = binding["text_columns"]
    records = frame.slice(offset, limit).to_dicts()
    return {**binding, "decision_id": decision.id, "offset": offset,
            "rows": [{"row_id": offset + i, "values": {key: row[key] for key in columns},
                      "label": row[binding["label_column"]]} for i, row in enumerate(records)]}


def apply_review(db, decision, *, reviewer_id: str, body: LabelReviewInput | None):
    """Stage the reviewed dataset; the HITL route commits it with its approval."""
    import polars as pl
    from app.services.tabular_datasets import register_frame

    if body is None:
        _refuse("LABEL_REVIEW_REQUIRED", "Review the labels and explicitly confirm the dataset before accepting.")
    if decision.status != "proposed":
        _refuse("LABEL_REVIEW_NOT_PENDING", "This review decision has already been resolved.")
    # Keep retirement from racing publication while the approval transaction
    # owns this exact source row. The Decision itself is locked by the route.
    binding_id = ((decision.rationale or {}).get("label_review") or {}).get("dataset_id")
    db.query(TabularDataset).filter_by(id=binding_id, workspace_id=decision.workspace_id).populate_existing().with_for_update().first()
    binding, source, _, frame = _bound_source(db, decision)
    if body.dataset_id != source.id or body.sha256 != binding["sha256"]:
        _refuse("LABEL_REVIEW_SOURCE_CHANGED", "The submitted review does not match this decision's dataset.")
    originals = frame[binding["label_column"]].to_list()
    corrections = {}
    for correction in body.corrections:
        if correction.row_id in corrections or correction.row_id >= frame.height or correction.label not in binding["labels"]:
            _refuse("LABEL_REVIEW_CORRECTION_INVALID", "Use each row once and choose a class from the allowed labels.", 422)
        corrections[correction.row_id] = correction.label
    labels = [corrections.get(i, value) for i, value in enumerate(originals)]
    corrected = sum(left != right for left, right in zip(originals, labels))
    metadata = {"decision_id": decision.id, "reviewed_by": reviewer_id,
                "reviewed_at": datetime.utcnow().isoformat(), "source_dataset_id": source.id,
                "source_version": source.version, "source_sha256": binding["sha256"],
                "rows_reviewed": frame.height, "corrected_rows": corrected,
                "label_column": binding["label_column"], "labels": binding["labels"]}
    output = register_frame(db, workspace_id=decision.workspace_id, name=f"{source.name[:180]} — reviewed",
        frame=frame.with_columns(pl.Series(binding["label_column"], labels, dtype=pl.String)),
        source="generated", produced_by=PRODUCER, parent_ids=[source.id], run_id=decision.target_id,
        node_id=(decision.rationale or {}).get("node_id"), created_by=reviewer_id,
        lineage={"kind": "label_review", "label_review": metadata,
                 "labeling": {**source.lineage_json["labeling"], "review_status": "reviewed"}})
    # This is server-owned evidence, kept outside the caller's accepted payload.
    _, digest = _snapshot(output)
    decision.rationale = {**decision.rationale, "label_review_result": {
        **metadata, "dataset_id": output.id, "sha256": digest}}
    db.flush()
    return output


def reviewed_output(db, decision):
    """A timer or generic approval cannot manufacture human-reviewed labels."""
    evidence = (decision.rationale or {}).get("label_review_result") or {}
    if (decision.status not in ("accepted", "applied") or not decision.human_confirmed_by
            or decision.human_confirmed_at is None or evidence.get("reviewed_by") != decision.human_confirmed_by):
        _refuse("LABEL_REVIEW_HUMAN_REQUIRED", "A confirmed human dataset review is required before training.")
    output = get_dataset(db, workspace_id=decision.workspace_id, dataset_id=evidence.get("dataset_id") or "")
    if output.produced_by != PRODUCER or (output.lineage_json or {}).get("label_review", {}).get("decision_id") != decision.id:
        _refuse("LABEL_REVIEW_PROVENANCE_INVALID", "The reviewed dataset does not match its approval.")
    _, digest = _snapshot(output)
    if digest != evidence.get("sha256"):
        _refuse("LABEL_REVIEW_SOURCE_CHANGED", "The reviewed dataset changed after approval.")
    return output


def training_provenance(db, dataset, target):
    """Verified teacher labels for holdout diagnostics, never model features."""
    metadata = (dataset.lineage_json or {}).get("label_review") or {}
    labeling = (dataset.lineage_json or {}).get("labeling") or {}
    if dataset.produced_by == LABEL_PRODUCER and target == labeling.get("label_column"):
        _refuse("ML_LABEL_REVIEW_REQUIRED", "Pass the LLM labels through a human review gate before training.")
    if dataset.produced_by != PRODUCER or target != metadata.get("label_column"):
        return None
    decision = db.query(Decision).filter_by(id=metadata.get("decision_id"), workspace_id=dataset.workspace_id,
                                          scope="run", kind="hitl_approval").first()
    if decision is None or reviewed_output(db, decision).id != dataset.id:
        _refuse("LABEL_REVIEW_PROVENANCE_INVALID", "The reviewed dataset has no matching human approval.")
    binding, source, job, original = _bound_source(db, decision)
    reviewed, _ = _snapshot(dataset)
    if original.height != reviewed.height or original.columns != reviewed.columns or not original.drop(target).equals(reviewed.drop(target)):
        _refuse("LABEL_REVIEW_PROVENANCE_INVALID", "The reviewed rows no longer align with the original labels.")
    evidence = decision.rationale["label_review_result"]
    return {"version": 1, "source_dataset_id": source.id, "source_version": source.version,
            "reviewed_dataset_id": dataset.id, "decision_id": decision.id,
            "label_column": target, "labels": binding["labels"],
            "rows_reviewed": evidence["rows_reviewed"], "corrected_rows": evidence["corrected_rows"],
            "teacher_labels": original[target].to_list(),
            "llm_estimated_cost_usd": job.result.get("estimated_cost_usd"),
            "llm_labeled_rows": job.result.get("rows_total"),
            "unknown_attempts": job.result.get("unknown_attempts", 0),
            "teacher_model": job.input_ref["model"]}
