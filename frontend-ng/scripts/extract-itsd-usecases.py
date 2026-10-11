#!/usr/bin/env python3
"""Extract the Nawa ITSD use-case catalogue from the customer xlsx into JSON.

Usage (from ``frontend-ng/``):

    python3 scripts/extract-itsd-usecases.py \
        --source "../docs/pih/IT Operations Automation Details.xlsx"

The source workbook describes the automation target using a **competitor's**
tooling: the vendor name appears 53 times over 24 rows, plus two bot names
(6 + 1 occurrences), four of them inside use-case titles that would land
straight on the demo screen. This script is the single enforcement point:
it rewrites those mentions and then re-reads its own output, exiting non-zero
if a single banned term survived. There is no human proof-reading step.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import openpyxl

SHEET = "End User Support"
HEADER_ROW = 4
FIRST_DATA_ROW = 5

# Assistant shown to the customer. Never a competitor name (SPEC §5.4).
ASSISTANT = "NAWA WE"

# Competitor / third-party bot names that must never reach the screen, the
# JSON, or the bundle. Lower-cased; matched case-insensitively as substrings so
# a casing or spacing variant cannot slip through.
BANNED_TERMS = ("leena", "daizy", "qwik")

# Ordered rewrites applied to every text cell. Order matters: the product
# names ("<vendor> Desktop Agent", "<vendor> dashboard") must be consumed
# before the bare vendor token, otherwise they degrade into nonsense.
#
# Rule from SPEC §5.4: substitute with the assistant name when the sentence
# describes the *automation gesture* ("<vendor> routes the requester…"), and
# use a neutral formulation when the substitution would be factually wrong —
# typically when the sentence describes the legacy manual process or the
# requester's entry channel.
SUBSTITUTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Source typos glue a branch label to the next sentence ("RejectedLeena
    # notifies…", "Failed:10 Agents"). Repairing them first is what lets the
    # vendor rules below see a word boundary at all — without this the purge
    # silently misses those cells.
    (re.compile(r"\b(Rejected|Failed|Missed Approval)(?=[A-Z])"), r"\1: "),
    (re.compile(r"(?<=:)(?=[A-Za-z0-9])"), " "),
    # Endpoint agent: a product, not the gesture.
    (re.compile(r"Leena\s+Desktop\s+Agent", re.IGNORECASE), f"{ASSISTANT} endpoint agent"),
    # The legacy reporting console the operator logs into by hand. Claiming
    # this is our dashboard would misdescribe the manual process.
    (re.compile(r"Leena\s+dashboard", re.IGNORECASE), "automation dashboard"),
    # Entry channel ("submits a query via <bot>") stays neutral.
    (re.compile(r"\b(via|through|in|from)\s+Daizy\b", re.IGNORECASE), r"\1 the assistant"),
    (re.compile(r"\bQWIK\s+BOT\b", re.IGNORECASE), "the assistant"),
    # Remaining bot mentions are automation gestures ("<bot> automatically
    # triggers an ITSD ticket").
    (re.compile(r"\bDaizy\b", re.IGNORECASE), ASSISTANT),
    # Bare vendor token: always the actor performing the automation.
    (re.compile(r"\bLeena\b", re.IGNORECASE), ASSISTANT),
)

# Use-case titles rewritten verbatim per the SPEC §5.4 table, keyed by SR#.
NAME_OVERRIDES = {
    19: "Ticket creation & tracking (assistant)",
    23: "Onboarding (assistant-driven)",
    35: "Collecting user hardware information (assistant)",
    39: "Automation Dashboard Data Extractor",
}

# The use cases wired end to end, mapped to the surface that serves them. Both
# are entries of the customer's own list rather than surfaces invented for a
# demonstration: SR#1 is the password reset the agent executes, SR#18 is the
# knowledge Q&A the assistant answers from the published service desk library.
LIVE_ROUTES = {
    1: "/nawa/itsd/password-reset",
    18: "/nawa/itsd/assistant",
}

# Six variants of a single "directory object change with approval" pattern,
# budgeted at 38 agents each in the source plan. The badge makes the
# factorisation argument visible on screen instead of leaving it to the pitch.
SAME_PATTERN_SR = (4, 5, 6, 7, 8, 9)
SAME_PATTERN_LABEL = "Directory object change with dual approval"


def slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", ascii_value.lower())).strip("-")


def purge(value: str) -> str:
    for pattern, replacement in SUBSTITUTIONS:
        value = pattern.sub(replacement, value)
    return value


def text(cell: object) -> str:
    if cell is None:
        return ""
    # Source cells carry stray tabs and blank leading lines.
    lines = [line.strip() for line in str(cell).replace("\t", " ").splitlines()]
    collapsed = "\n".join(line for line in lines if line)
    return purge(re.sub(r"[ ]{2,}", " ", collapsed)).strip()


def number(cell: object) -> float | int | None:
    if not isinstance(cell, (int, float)):
        return None
    return int(cell) if float(cell).is_integer() else round(float(cell), 1)


def extract(source: Path) -> dict:
    sheet = openpyxl.load_workbook(source, data_only=True)[SHEET]
    headers = [text(sheet.cell(HEADER_ROW, column).value) for column in range(1, 9)]

    use_cases = []
    for row in range(FIRST_DATA_ROW, sheet.max_row + 1):
        sr = sheet.cell(row, 1).value
        name = sheet.cell(row, 2).value
        if not isinstance(sr, (int, float)) or not name:
            continue
        sr = int(sr)
        display_name = NAME_OVERRIDES.get(sr) or text(name)
        use_cases.append(
            {
                "sr": sr,
                "name": display_name,
                "slug": slugify(display_name),
                "manual_process": text(sheet.cell(row, 3).value),
                "automated_process": text(sheet.cell(row, 4).value),
                "agents": number(sheet.cell(row, 5).value),
                "monthly_volume": number(sheet.cell(row, 6).value),
                "automated_minutes": number(sheet.cell(row, 7).value),
                "legacy_minutes": number(sheet.cell(row, 8).value),
                "status": "live" if sr in LIVE_ROUTES else "planned",
                "route": LIVE_ROUTES.get(sr),
                "pattern_group": SAME_PATTERN_LABEL if sr in SAME_PATTERN_SR else None,
            }
        )

    return {
        "meta": {
            "assistant": ASSISTANT,
            "source_workbook": source.name,
            "source_sheet": SHEET,
            "generated_by": "frontend-ng/scripts/extract-itsd-usecases.py",
            "use_case_count": len(use_cases),
            "planned_agent_total": sum(case["agents"] or 0 for case in use_cases),
            # Verbatim source headers: the workbook annotates the target-time
            # column with "Time in hours" while every value reads as minutes
            # against a legacy column explicitly in minutes. Carried as-is so
            # the UI labels the customer's own wording instead of inventing one.
            "source_headers": headers,
            "same_pattern_label": SAME_PATTERN_LABEL,
        },
        "use_cases": use_cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    parser.add_argument(
        "--source",
        type=Path,
        default=here.parents[1] / "docs" / "pih" / "IT Operations Automation Details.xlsx",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=here.parent / "src" / "assets" / "nawa" / "itsd-use-cases.json",
    )
    args = parser.parse_args()

    if not args.source.is_file():
        print(f"source workbook not found: {args.source}", file=sys.stderr)
        return 2

    payload = extract(args.source)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    # The guard rail: inspect exactly what would be written, and refuse to
    # write it if the purge missed anything.
    haystack = serialized.lower()
    survivors = sorted({term for term in BANNED_TERMS if term in haystack})
    if survivors:
        print(
            "REFUSING TO WRITE — banned term(s) survived the purge: "
            + ", ".join(survivors),
            file=sys.stderr,
        )
        for line_number, line in enumerate(serialized.splitlines(), start=1):
            lowered = line.lower()
            if any(term in lowered for term in survivors):
                print(f"  line {line_number}: {line.strip()[:160]}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(serialized, encoding="utf-8")
    print(
        f"wrote {args.out} — {payload['meta']['use_case_count']} use cases, "
        f"{payload['meta']['planned_agent_total']} planned agents, purge clean"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
