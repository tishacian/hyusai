#!/usr/bin/env python3
"""Deterministically build every generated file in the Agentium pump-incident demo kit.

Two artefacts are generated, both from editable sources that live next to them:

* ``upload/02-safety-procedure-PROC-SAFE-118.pdf`` from
  ``source/safety-procedure-PROC-SAFE-118.source.md``;
* ``roi/roi-model.md`` from ``roi/roi-assumptions.json``.

Usage::

    python3 tools/generate_assets.py            # write the artefacts
    python3 tools/generate_assets.py --check    # fail if a committed artefact drifted

The generator uses the Python standard library only, makes no network call and
produces byte-identical output on every run, so ``--check`` is a real drift gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdf_writer import (  # noqa: E402  (path is prepared just above)
    CONTENT_WIDTH,
    MARGIN_LEFT,
    Draw,
    PdfDocument,
    Run,
    split_bold_runs,
    text_width,
    wrap_runs,
)

KIT_ROOT = Path(__file__).resolve().parents[1]
PDF_SOURCE = KIT_ROOT / "source" / "safety-procedure-PROC-SAFE-118.source.md"
PDF_TARGET = KIT_ROOT / "upload" / "02-safety-procedure-PROC-SAFE-118.pdf"
ROI_SOURCE = KIT_ROOT / "roi" / "roi-assumptions.json"
ROI_TARGET = KIT_ROOT / "roi" / "roi-model.md"

PDF_FOOTER = (
    "PROC-SAFE-118  |  Nordvane Fluid Systems SA  |  synthetic demonstration document"
)

BODY_SIZE = 10.0
TITLE_SIZE = 17.0
HEADING_SIZE = 12.5


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
def _parse_blocks(markdown: str) -> list[tuple[str, object]]:
    blocks: list[tuple[str, object]] = []
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        if not line.strip():
            index += 1
            continue
        if line.startswith("# "):
            blocks.append(("title", line[2:].strip()))
        elif line.startswith("## "):
            blocks.append(("heading", line[3:].strip()))
        elif line.startswith("|"):
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].startswith("|"):
                cells = [
                    cell.strip() for cell in lines[index].strip().strip("|").split("|")
                ]
                if not all(set(cell) <= set("-: ") and cell for cell in cells):
                    rows.append(cells)
                index += 1
            blocks.append(("table", rows))
            continue
        elif line.startswith("- "):
            items: list[str] = []
            while index < len(lines) and lines[index].startswith("- "):
                item = lines[index][2:].strip()
                index += 1
                while (
                    index < len(lines)
                    and lines[index].startswith("  ")
                    and lines[index].strip()
                ):
                    item += " " + lines[index].strip()
                    index += 1
                items.append(item)
            blocks.append(("bullets", items))
            continue
        else:
            paragraph = [line.strip()]
            index += 1
            while (
                index < len(lines)
                and lines[index].strip()
                and not lines[index].startswith(("#", "|", "- "))
            ):
                paragraph.append(lines[index].strip())
                index += 1
            blocks.append(("paragraph", " ".join(paragraph)))
            continue
        index += 1
    return blocks


def _render_table(doc: PdfDocument, rows: list[list[str]]) -> None:
    if not rows:
        return
    columns = max(len(row) for row in rows)
    rows = [row + [""] * (columns - len(row)) for row in rows]
    natural = [
        max(text_width(row[column], BODY_SIZE, row is rows[0]) for row in rows)
        for column in range(columns)
    ]
    padding = 10.0
    total_natural = sum(natural) + padding * columns
    if total_natural <= CONTENT_WIDTH:
        widths = [value + padding for value in natural]
        widths[-1] += CONTENT_WIDTH - sum(widths)
    else:
        scale = (CONTENT_WIDTH - padding * columns) / sum(natural)
        widths = [value * scale + padding for value in natural]

    # Keep a table's header with its first rows: a header stranded at the foot
    # of a page reads as a broken document in a citation preview.
    doc.space(4)
    doc.ensure(min(len(rows), 4) * (BODY_SIZE * 1.35 + 3))
    for row_index, row in enumerate(rows):
        header = row_index == 0
        wrapped = [
            wrap_runs(split_bold_runs(cell), BODY_SIZE, widths[column] - padding)
            for column, cell in enumerate(row)
        ]
        height = max(len(cell) for cell in wrapped) * BODY_SIZE * 1.35 + 3
        doc.ensure(height)
        top = doc.y
        for column, cell_lines in enumerate(wrapped):
            x = MARGIN_LEFT + sum(widths[:column])
            doc.y = top
            for line in cell_lines:
                runs = [Run(run.text, header or run.bold) for run in line]
                doc.y -= BODY_SIZE * 1.35
                doc.pages[-1].append(
                    Draw("text", x=x, y=doc.y, runs=runs, size=BODY_SIZE)
                )
        doc.y = top - height
        if header:
            doc.rule(MARGIN_LEFT, CONTENT_WIDTH, gray=0.35, height=0.8)
        else:
            doc.rule(MARGIN_LEFT, CONTENT_WIDTH, gray=0.82, height=0.4)
    doc.space(6)


def build_pdf_bytes() -> bytes:
    markdown = PDF_SOURCE.read_text(encoding="utf-8")
    blocks = _parse_blocks(markdown)
    title = next((value for kind, value in blocks if kind == "title"), "Document")
    doc = PdfDocument(title=str(title), footer=PDF_FOOTER)

    for kind, value in blocks:
        if kind == "title":
            for line in wrap_runs([Run(str(value), True)], TITLE_SIZE, CONTENT_WIDTH):
                doc.text_line(line, TITLE_SIZE, MARGIN_LEFT)
            doc.space(7)
            doc.rule(MARGIN_LEFT, CONTENT_WIDTH, gray=0.35, height=1.0)
            doc.space(8)
        elif kind == "heading":
            doc.space(10)
            doc.ensure(HEADING_SIZE * 2.4)
            for line in wrap_runs([Run(str(value), True)], HEADING_SIZE, CONTENT_WIDTH):
                doc.text_line(line, HEADING_SIZE, MARGIN_LEFT)
            doc.space(3)
        elif kind == "paragraph":
            for line in wrap_runs(
                split_bold_runs(str(value)), BODY_SIZE, CONTENT_WIDTH
            ):
                doc.text_line(line, BODY_SIZE, MARGIN_LEFT)
            doc.space(6)
        elif kind == "bullets":
            for item in value:  # type: ignore[union-attr]
                lines = wrap_runs(split_bold_runs(item), BODY_SIZE, CONTENT_WIDTH - 16)
                for line_index, line in enumerate(lines):
                    doc.text_line(line, BODY_SIZE, MARGIN_LEFT + 16)
                    if line_index == 0:
                        doc.pages[-1].append(
                            Draw(
                                "text",
                                x=MARGIN_LEFT + 5,
                                y=doc.pages[-1][-1].y,
                                runs=[Run("-", False)],
                                size=BODY_SIZE,
                            )
                        )
                doc.space(2)
            doc.space(6)
        elif kind == "table":
            _render_table(doc, value)  # type: ignore[arg-type]
    return doc.to_bytes()


# --------------------------------------------------------------------------
# ROI
# --------------------------------------------------------------------------
def compute_roi(assumptions: dict) -> dict:
    """Single source of truth for the ROI arithmetic (shared with the validator)."""
    b1 = assumptions["benefit_1_search_time"]
    b2 = assumptions["benefit_2_sla_credit_avoidance"]
    b3 = assumptions["benefit_3_expedited_freight_avoidance"]
    costs = assumptions["year_one_costs"]

    minutes_saved_per_incident = round(
        b1["baseline_minutes_per_incident"] * b1["reduction_rate"], 2
    )
    benefit_1 = round(
        b1["incidents_per_year"]
        * (b1["baseline_minutes_per_incident"] * b1["reduction_rate"])
        / 60
        * b1["loaded_hourly_cost_eur"],
        2,
    )
    breaches_avoided = round(
        b2["p1_incidents_per_year"]
        * b2["baseline_breach_rate"]
        * b2["breach_reduction_rate"],
        2,
    )
    benefit_2 = round(breaches_avoided * b2["credit_per_breach_eur"], 2)
    shipments_avoided = round(
        b3["expedited_shipments_per_year"] * b3["avoidance_rate"], 2
    )
    benefit_3 = round(shipments_avoided * b3["cost_per_expedited_shipment_eur"], 2)
    annual_benefit = round(benefit_1 + benefit_2 + benefit_3, 2)

    internal_effort = round(
        costs["internal_effort_hours"] * costs["internal_effort_hourly_cost_eur"], 2
    )
    year_one_cost = round(
        costs["implementation_services_eur"]
        + costs["platform_and_model_runtime_eur"]
        + internal_effort,
        2,
    )
    net_value = round(annual_benefit - year_one_cost, 2)
    roi_percent = round(net_value / year_one_cost * 100, 2)
    monthly_benefit = round(annual_benefit / 12, 2)
    payback_months = round(year_one_cost / (annual_benefit / 12), 2)

    return {
        "minutes_saved_per_incident": minutes_saved_per_incident,
        "benefit_1_search_time_eur": benefit_1,
        "breaches_avoided_per_year": breaches_avoided,
        "benefit_2_sla_credit_avoidance_eur": benefit_2,
        "shipments_avoided_per_year": shipments_avoided,
        "benefit_3_expedited_freight_avoidance_eur": benefit_3,
        "annual_benefit_eur": annual_benefit,
        "internal_effort_eur": internal_effort,
        "year_one_cost_eur": year_one_cost,
        "net_value_year_one_eur": net_value,
        "roi_percent_year_one": roi_percent,
        "monthly_benefit_eur": monthly_benefit,
        "payback_period_months": payback_months,
    }


def _money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def build_roi_markdown() -> str:
    assumptions = json.loads(ROI_SOURCE.read_text(encoding="utf-8"))
    result = compute_roi(assumptions)
    b1 = assumptions["benefit_1_search_time"]
    b2 = assumptions["benefit_2_sla_credit_avoidance"]
    b3 = assumptions["benefit_3_expedited_freight_avoidance"]
    costs = assumptions["year_one_costs"]

    lines: list[str] = []
    add = lines.append
    add("<!-- GENERATED FILE. Edit roi/roi-assumptions.json, then run:")
    add("     python3 tools/generate_assets.py -->")
    add("")
    add("# Modeled demo ROI — Agentium field-service knowledge")
    add("")
    add("**This is a modeled demo ROI, not a measured customer result.** Every number")
    add("below is computed from the editable assumptions in `roi-assumptions.json` by")
    add("`tools/generate_assets.py`. No figure here was observed at a customer, and no")
    add(
        "figure here is a Nordvane, Helioforge or Agentium price. Replace the assumptions"
    )
    add(
        "with the evaluator's own numbers before using this in any commercial discussion."
    )
    add("")
    add(f"Currency: {assumptions['currency']}. Horizon: year one only.")
    add("")
    add("## Headline result")
    add("")
    add("| Result | Value |")
    add("| --- | --- |")
    add(f"| Annual benefit | EUR {_money(result['annual_benefit_eur'])} |")
    add(f"| Year-one cost | EUR {_money(result['year_one_cost_eur'])} |")
    add(f"| Net value, year one | EUR {_money(result['net_value_year_one_eur'])} |")
    add(f"| ROI, year one | {result['roi_percent_year_one']:.2f} % |")
    add(f"| Payback period | {result['payback_period_months']:.2f} months |")
    add("")
    add("## Organisation assumed")
    add("")
    add("| Assumption | Value |")
    add("| --- | --- |")
    for key, value in assumptions["organisation"].items():
        add(f"| {key.replace('_', ' ')} | {value} |")
    add("")
    add("## Benefit 1 — " + b1["label"])
    add("")
    add("```")
    add(b1["formula"])
    add(
        f"= {b1['incidents_per_year']} * ({b1['baseline_minutes_per_incident']} * "
        f"{b1['reduction_rate']}) / 60 * {b1['loaded_hourly_cost_eur']}"
    )
    add(
        f"= {b1['incidents_per_year']} * {result['minutes_saved_per_incident']} minutes / 60 * "
        f"{b1['loaded_hourly_cost_eur']} EUR per hour"
    )
    add(f"= EUR {result['benefit_1_search_time_eur']:.2f} per year")
    add("```")
    add("")
    add(f"Conservatism: {b1['conservatism_note']}")
    add("")
    add("## Benefit 2 — " + b2["label"])
    add("")
    add("```")
    add(b2["formula"])
    add(
        f"= {b2['p1_incidents_per_year']} * {b2['baseline_breach_rate']} * "
        f"{b2['breach_reduction_rate']} * {b2['credit_per_breach_eur']}"
    )
    add(
        f"= {result['breaches_avoided_per_year']} breaches avoided * EUR "
        f"{b2['credit_per_breach_eur']} per 12-hour credit block"
    )
    add(f"= EUR {result['benefit_2_sla_credit_avoidance_eur']:.2f} per year")
    add("```")
    add("")
    add(f"Conservatism: {b2['conservatism_note']}")
    add("")
    add("## Benefit 3 — " + b3["label"])
    add("")
    add("```")
    add(b3["formula"])
    add(
        f"= {b3['expedited_shipments_per_year']} * {b3['avoidance_rate']} * "
        f"{b3['cost_per_expedited_shipment_eur']}"
    )
    add(
        f"= {result['shipments_avoided_per_year']} shipments avoided * EUR "
        f"{b3['cost_per_expedited_shipment_eur']} each"
    )
    add(f"= EUR {result['benefit_3_expedited_freight_avoidance_eur']:.2f} per year")
    add("```")
    add("")
    add(f"Conservatism: {b3['conservatism_note']}")
    add("")
    add("## Annual benefit")
    add("")
    add("```")
    add("annual_benefit = benefit_1 + benefit_2 + benefit_3")
    add(
        f"= {result['benefit_1_search_time_eur']:.2f} + "
        f"{result['benefit_2_sla_credit_avoidance_eur']:.2f} + "
        f"{result['benefit_3_expedited_freight_avoidance_eur']:.2f}"
    )
    add(f"= EUR {result['annual_benefit_eur']:.2f}")
    add("```")
    add("")
    add("## Year-one cost")
    add("")
    add("| Cost line | Value |")
    add("| --- | --- |")
    add(
        f"| Implementation services | EUR {_money(costs['implementation_services_eur'])} |"
    )
    add(
        f"| Platform and model runtime, 12 months | EUR "
        f"{_money(costs['platform_and_model_runtime_eur'])} |"
    )
    add(
        f"| Internal effort, {costs['internal_effort_hours']} h at EUR "
        f"{costs['internal_effort_hourly_cost_eur']}/h | EUR {_money(result['internal_effort_eur'])} |"
    )
    add(f"| **Total year-one cost** | **EUR {_money(result['year_one_cost_eur'])}** |")
    add("")
    add("```")
    add("internal_effort = " + costs["internal_effort_formula"])
    add(
        f"= {costs['internal_effort_hours']} * {costs['internal_effort_hourly_cost_eur']} = EUR "
        f"{result['internal_effort_eur']:.2f}"
    )
    add(
        "year_one_cost = implementation_services + platform_and_model_runtime + internal_effort"
    )
    add(
        f"= {costs['implementation_services_eur']} + {costs['platform_and_model_runtime_eur']} + "
        f"{result['internal_effort_eur']:.2f}"
    )
    add(f"= EUR {result['year_one_cost_eur']:.2f}")
    add("```")
    add("")
    add(f"Conservatism: {costs['conservatism_note']}")
    add("")
    add("## Net value, ROI and payback")
    add("")
    add("```")
    add("net_value = annual_benefit - year_one_cost")
    add(
        f"= {result['annual_benefit_eur']:.2f} - {result['year_one_cost_eur']:.2f} = EUR "
        f"{result['net_value_year_one_eur']:.2f}"
    )
    add("")
    add("roi_percent = net_value / year_one_cost * 100")
    add(
        f"= {result['net_value_year_one_eur']:.2f} / {result['year_one_cost_eur']:.2f} * 100 = "
        f"{result['roi_percent_year_one']:.2f} %"
    )
    add("")
    add("payback_months = year_one_cost / (annual_benefit / 12)")
    add(
        f"= {result['year_one_cost_eur']:.2f} / {result['monthly_benefit_eur']:.2f} = "
        f"{result['payback_period_months']:.2f} months"
    )
    add("```")
    add("")
    add("## Deliberately excluded from this model")
    add("")
    for item in assumptions["excluded_from_the_model"]:
        add(f"- {item}")
    add("")
    add("## How to re-run this model with the evaluator's numbers")
    add("")
    add("1. Edit `roi/roi-assumptions.json`.")
    add("2. Run `python3 tools/generate_assets.py` from the kit root.")
    add("3. Run `python3 tools/validate_demo_kit.py` to re-check the arithmetic.")
    add("4. Present the result as a model built on the evaluator's own assumptions.")
    add("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write. Exit non-zero if a committed artefact differs from a fresh build.",
    )
    args = parser.parse_args(argv)

    artefacts: list[tuple[Path, bytes]] = [
        (PDF_TARGET, build_pdf_bytes()),
        (ROI_TARGET, build_roi_markdown().encode("utf-8")),
    ]

    drifted: list[str] = []
    for path, payload in artefacts:
        relative = path.relative_to(KIT_ROOT)
        if args.check:
            if not path.exists():
                drifted.append(f"{relative}: missing")
            elif path.read_bytes() != payload:
                drifted.append(f"{relative}: differs from a fresh deterministic build")
            else:
                print(f"unchanged  {relative}  ({len(payload)} bytes)")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            print(f"wrote      {relative}  ({len(payload)} bytes)")

    if drifted:
        for problem in drifted:
            print(f"DRIFT      {problem}", file=sys.stderr)
        print("\nRun: python3 tools/generate_assets.py", file=sys.stderr)
        return 1
    print(
        "\nOK: generated assets are deterministic and up to date."
        if args.check
        else "\nOK: generated assets written."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
