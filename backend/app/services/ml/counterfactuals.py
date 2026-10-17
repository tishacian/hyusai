"""What would have to change to flip the answer: a bounded counterfactual search.

In the spirit of DiCE, but deliberately small enough to be read and trusted:
the caller names one to three fields it can act on (a plan, a discount, a
tenure), and the search proposes the fewest and nearest changes to those
fields that make the model give the answer the caller wants — another class,
or a value inside a range.

Three properties are decisions:

**Candidates come from the contract, never from imagination.** A field's
values are the ones the training set vouched for and the harness recorded in
the input contract: the levels of a category, true/false, or a grid inside the
numeric ``[min, max]`` seen at fit time. Nothing outside the training range is
ever proposed, and a field whose contract carries no such facts is refused with
its reason rather than guessed at.

**Minimal first.** One-field changes are searched before two, two before three,
and a combination that contains a change already sufficient on its own is not
a new answer. Results rank by how many fields change, then by how far
(numeric distance normalized by the training range, one per changed category).

**Predictions only, and nothing written.** The candidates are scored by the
same loaded pipeline ``/predict`` uses, in-process, under a hard budget of
candidate rows. No candidate is journalled, no shadow is staged, nothing is
stored whatever the workspace's storage policy. The call is admitted like one
interactive prediction of one row (see ``ml_governance.admit``): it is one
human question, so it takes a request from the lineage's budget, but its
internal candidates do not drain the per-minute row budget of real traffic.
"""

from __future__ import annotations

import itertools
import math
import time
from typing import Any

from app.core.config import settings
from app.services.tabular_datasets import TabularError

MAX_FIELDS = 3
_NUMERIC = frozenset({"double", "float", "long", "integer"})


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _integral(*values: Any) -> bool:
    numbers = [_number(value) for value in values]
    return all(number is not None and float(number).is_integer() for number in numbers)


def candidate_values(
    spec: dict[str, Any], current: Any
) -> tuple[list[Any], dict | None, str | None]:
    """The values a field may take in a counterfactual, and how to measure distance.

    Returns ``(values, scale, refusal_reason)``. ``scale`` is ``{"low", "high"}``
    for a numeric field and ``None`` for a categorical one.
    """

    declared = str(spec.get("type") or "string")
    kind = str(spec.get("kind") or "")
    if declared == "datetime" or kind == "datetime":
        return [], None, "unsupported_kind"
    if declared == "boolean":
        return [value for value in (True, False) if value != current], None, None
    if declared in _NUMERIC:
        low, high = _number(spec.get("min")), _number(spec.get("max"))
        if low is None or high is None:
            return [], None, "no_range"
        if high <= low:
            return [], None, "constant"
        points = int(settings.ml_counterfactual_grid_points)
        grid = [low + (high - low) * index / (points - 1) for index in range(points)]
        typical = _number(spec.get("default"))
        if typical is not None and low <= typical <= high:
            grid.append(typical)
        whole = _integral(low, high, typical if typical is not None else low)
        # A count recorded as whole numbers at fit time stays whole: proposing
        # 37.4 months of tenure would be a value the training set never held.
        values = sorted({round(value) if whole else round(value, 6) for value in grid})
        values = [float(value) for value in values if low <= value <= high]
        return (
            [value for value in values if value != _number(current)],
            {
                "low": low,
                "high": high,
            },
            None,
        )
    choices = spec.get("choices")
    if not isinstance(choices, list) or not choices:
        return [], None, "no_levels"
    return [str(choice) for choice in choices if str(choice) != current], None, None


def _distance(change: tuple[str, Any], original: dict[str, Any], scales: dict) -> float:
    field, value = change
    scale = scales.get(field)
    before = _number(original.get(field))
    if scale is None or before is None:
        return 1.0
    return abs(float(value) - before) / (scale["high"] - scale["low"])


def _target_of(model: Any, classes: list[str], current: dict[str, Any], target: Any) -> dict:
    target = dict(target or {})
    if model.task == "classification":
        wanted = target.get("class")
        if wanted is not None and str(wanted) not in classes:
            raise TabularError(
                code="ML_COUNTERFACTUAL_TARGET_INVALID",
                message="The desired class is not one of the model's classes.",
                details={"classes": classes[:24]},
            )
        if wanted is None and len(classes) == 2:
            # Binary: "the other answer" is a definite class, and naming it lets
            # the results quote that class's probability.
            wanted = next(label for label in classes if label != current.get("prediction"))
        return {"class": str(wanted) if wanted is not None else None}
    low, high = _number(target.get("min")), _number(target.get("max"))
    if low is None and high is None:
        raise TabularError(
            code="ML_COUNTERFACTUAL_TARGET_INVALID",
            message="A regression target needs a min, a max or both.",
        )
    if low is not None and high is not None and high < low:
        raise TabularError(
            code="ML_COUNTERFACTUAL_TARGET_INVALID",
            message="The target's max is below its min.",
        )
    return {"min": low, "max": high}


def _reaches(model: Any, answer: dict[str, Any], target: dict, current: dict[str, Any]) -> bool:
    if model.task == "classification":
        wanted = target.get("class")
        label = answer.get("prediction")
        return label == wanted if wanted is not None else label != current.get("prediction")
    value = _number(answer.get("prediction"))
    if value is None:
        return False
    low, high = target.get("min"), target.get("max")
    return (low is None or value >= low) and (high is None or value <= high)


def _summary(model: Any, answer: dict[str, Any], target: dict) -> dict[str, Any]:
    if model.task != "classification":
        return {"prediction": answer.get("prediction")}
    wanted = target.get("class") or answer.get("prediction")
    probability = next(
        (
            item["value"]
            for item in answer.get("probabilities") or []
            if item.get("label") == wanted
        ),
        answer.get("confidence"),
    )
    return {"prediction": answer.get("prediction"), "probability": probability}


def _diverse(ranked: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Up to ``limit`` results, preferring ones that change different fields."""

    chosen: list[dict[str, Any]] = []
    seen: set[frozenset[str]] = set()
    for item in ranked:
        fields = frozenset(change["field"] for change in item["changes"])
        if fields not in seen:
            chosen.append(item)
            seen.add(fields)
        if len(chosen) == limit:
            return chosen
    for item in ranked:
        if item not in chosen:
            chosen.append(item)
        if len(chosen) == limit:
            break
    return chosen


def search(
    db: Any,
    model: Any,
    row: Any,
    *,
    fields: Any,
    target: Any = None,
    version: Any = None,
) -> dict[str, Any]:
    """Search the fewest, nearest changes to ``fields`` that reach ``target``."""

    from app.services.ml_governance import admit
    from app.services.tabular_predict import (
        _positive_label,
        _predict_frame,
        _rows_from,
        _served_block,
        build_frame,
        coerce_rows,
        contract_fields,
        load_pipeline_traced,
        serving_version,
    )

    served = serving_version(db, model, version=version)
    if (served.family or "tabular") != "tabular" or served.task not in {
        "classification",
        "regression",
    }:
        raise TabularError(
            code="ML_COUNTERFACTUAL_UNSUPPORTED",
            message="Counterfactuals are searched for tabular classification and regression models.",
            status_code=409,
            details={"family": served.family, "task": served.task},
        )
    contract = contract_fields(served)
    by_name = {str(spec["name"]): spec for spec in contract}
    requested = [str(name) for name in (fields or [])]
    if not 1 <= len(requested) <= MAX_FIELDS or len(set(requested)) != len(requested):
        raise TabularError(
            code="ML_COUNTERFACTUAL_FIELDS_INVALID",
            message=f"Name between 1 and {MAX_FIELDS} distinct fields the answer may change.",
            details={"max": MAX_FIELDS},
        )
    unknown = [name for name in requested if name not in by_name]
    if unknown:
        raise TabularError(
            code="ML_COUNTERFACTUAL_FIELD_UNKNOWN",
            message=f"'{unknown[0]}' is not an input of this model.",
            details={"fields": unknown},
        )
    original = coerce_rows(served, [row])[0]

    candidates: dict[str, list[Any]] = {}
    scales: dict[str, dict] = {}
    refused: list[dict[str, str]] = []
    for name in requested:
        values, scale, reason = candidate_values(by_name[name], original.get(name))
        if reason or not values:
            refused.append({"field": name, "reason": reason or "no_alternative"})
            continue
        candidates[name] = values
        if scale is not None:
            scales[name] = scale
    if not candidates:
        raise TabularError(
            code="ML_COUNTERFACTUAL_FIELDS_UNSUPPORTED",
            message="None of these fields has training facts a change can be drawn from.",
            status_code=422,
            details={"refused": refused},
        )

    # One interactive question, one row of the lineage's budget; see module doc.
    admit(db, model, rows=1)
    started = time.monotonic()
    entry, _ = load_pipeline_traced(served)
    classes = entry.classes
    positive = _positive_label(served, classes)

    def score(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        predicted, proba = _predict_frame(entry, served, build_frame(contract, rows))
        return _rows_from(served, classes, positive, predicted, proba)

    current = score([original])[0]
    goal = _target_of(served, classes, current, target)
    base = {
        "served": _served_block(served),
        "task": served.task,
        "target": goal,
        "current": _summary(served, current, goal),
        "fields": [
            {"field": name, "candidates": len(values)} for name, values in candidates.items()
        ],
        "refused": refused,
        "budget": int(settings.ml_counterfactual_max_candidates),
    }
    if _reaches(served, current, goal, current):
        return {
            **base,
            "status": "already_reached",
            "results": [],
            "evaluated": 0,
            "exhausted": False,
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
        }

    budget = int(settings.ml_counterfactual_max_candidates)
    batch_size = int(settings.ml_counterfactual_batch_rows)
    wanted = int(settings.ml_counterfactual_max_results)
    evaluated, exhausted = 0, False
    sufficient: set[frozenset[tuple[str, Any]]] = set()
    found: list[dict[str, Any]] = []
    names = list(candidates)

    def flush(pending: list[tuple[tuple[tuple[str, Any], ...], dict[str, Any]]]) -> None:
        for (changes, _), answer in zip(pending, score([variant for _, variant in pending])):
            if not _reaches(served, answer, goal, current):
                continue
            sufficient.add(frozenset(changes))
            found.append(
                {
                    "changes": [
                        {"field": field, "from": original.get(field), "to": value}
                        for field, value in changes
                    ],
                    "changed_fields": len(changes),
                    "distance": round(sum(_distance(c, original, scales) for c in changes), 6),
                    **_summary(served, answer, goal),
                }
            )

    for size in range(1, len(names) + 1):
        pending: list[tuple[tuple[tuple[str, Any], ...], dict[str, Any]]] = []
        for combination in itertools.combinations(names, size):
            for values in itertools.product(*(candidates[name] for name in combination)):
                changes = tuple(zip(combination, values))
                # Not minimal: a smaller part of this change already flips it.
                if size > 1 and any(
                    frozenset(part) in sufficient
                    for width in range(1, size)
                    for part in itertools.combinations(changes, width)
                ):
                    continue
                if evaluated >= budget:
                    exhausted = True
                    break
                pending.append((changes, {**original, **dict(changes)}))
                evaluated += 1
                if len(pending) >= batch_size:
                    flush(pending)
                    pending = []
            if exhausted:
                break
        if pending:
            flush(pending)
        # Larger changes can only rank after these; stop once the page is full.
        if exhausted or len(found) >= wanted:
            break

    found.sort(key=lambda item: (item["changed_fields"], item["distance"]))
    return {
        **base,
        "status": "found" if found else "not_found",
        "results": _diverse(found, wanted),
        "evaluated": evaluated,
        "exhausted": exhausted,
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
    }


__all__ = ["MAX_FIELDS", "candidate_values", "search"]
