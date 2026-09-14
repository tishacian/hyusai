#!/usr/bin/env python3
"""Offline self-check for the Agentium pump-incident demo kit.

Verifies, without a network call and without any third-party package:

1. every file the kit and its guide reference exists;
2. every upload extension is accepted by the current Agentium UI dropzone and
   by the current backend upload endpoint (read from this repository when the
   kit is checked out inside it);
3. every exact identifier is present in its declared primary source and in each
   file it claims to also appear in;
4. every expected fact's evidence string is present in each declared source, so
   the demo's expected answers really are supported by the uploaded corpus;
5. the scoping decoy and the unrelated control document stay unrelated;
6. the corpus contains none of the terms the abstention prompt asks for;
7. the ROI arithmetic recomputed from the assumptions matches the generated ROI
   report and the headline figures quoted in the guide and the kit README.

PDF text is read straight out of the uncompressed content streams the kit's own
generator writes, so the check needs no PDF library.

Usage::

    python3 tools/validate_demo_kit.py            # human-readable report
    python3 tools/validate_demo_kit.py --quiet    # failures only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_assets import compute_roi  # noqa: E402  (path is prepared just above)

KIT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = KIT_ROOT.parents[1]
EXPECTED = KIT_ROOT / "expected" / "expected-facts.json"
ROI_ASSUMPTIONS = KIT_ROOT / "roi" / "roi-assumptions.json"
ROI_REPORT = KIT_ROOT / "roi" / "roi-model.md"
KIT_README = KIT_ROOT / "README.md"
GUIDE = REPO_ROOT / "docs" / "agentium-pump-incident-demo-runbook.md"

FRONTEND_DROPZONE = (
    REPO_ROOT / "frontend-ng/src/app/features/knowledge/knowledge-base.component.ts"
)
BACKEND_UPLOAD = REPO_ROOT / "backend/app/api/v1/endpoints/documents.py"

# Claims that reviews have already rejected once. Each rule is a narrow regex over
# the guide and the kit's own prose, not a copy of the text that should be there,
# so ordinary rewording stays free while the specific defect cannot come back.
FORBIDDEN_CLAIMS: tuple[tuple[str, str, str], ...] = (
    (
        "scoping-decoy-called-unused",
        r"(?is)(POL-FLEET-22[^.\n|]{0,40}and[^.\n|]{0,10}GBX-5501[^.\n|]{0,30}"
        r"(?:are not used|not used|never retrieved)"
        r"|GBX-5501[^.\n|]{0,40}(?:is|are) not (?:used|retrieved)"
        r"|\bNeither used\b)",
        "P3 deliberately retrieves GBX-5501 and rules it out. Requiring it to be "
        "unused contradicts the script: require POL-FLEET-22 to stay uncited, and "
        "GBX-5501 to be retrieved then explicitly ruled out.",
    ),
    (
        "save-an-invalid-model-to-force-a-failure",
        # Either word order: "invalid model ... save" and "model ... invalid ... save".
        r"(?is)(?:"
        r"(?:does not exist|nonexistent|non-existent|invalid|wrong|dead|bogus|fake)"
        r"[^.\n|]{0,40}(?:model|api key|key|endpoint|credential|deployment)"
        r"|(?:model name|model|api key|key|endpoint|credential|deployment)"
        r"[^.\n|]{0,40}(?:does not exist|nonexistent|non-existent|invalid|wrong|dead|bogus|fake)"
        r")[^.\n|]{0,80}(?:,\s*save|then save|and save\b|save it\b|save that\b|click[^.\n|]{0,20}save)",
        "Model setup is fail closed: an invalid model, key or endpoint is rejected "
        "by the live probe and never saved, so it cannot produce a later failure in "
        "Ask. Use a drill that breaks reachability outside Agentium instead.",
    ),
    (
        "unsourced-retrieval-benchmark",
        r"(?is)(?:35\s*(?:-|to|–)\s*60|low end of the (?:usual|typical) range"
        r"|usually claimed for enterprise retrieval|industry (?:benchmark|average))",
        "The kit cites no external benchmark. Present the reduction rate only as an "
        "editable scenario assumption for this synthetic model.",
    ),
)


# Fallback used only when the kit is copied out of the repository. Both lists
# are read from source when the repository is present.
FALLBACK_UI_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".md",
    ".docx",
    ".csv",
    ".json",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".webp",
}


class Report:
    def __init__(self, quiet: bool) -> None:
        self.quiet = quiet
        self.passed = 0
        self.failures: list[str] = []
        self.skipped: list[str] = []

    def section(self, title: str) -> None:
        if not self.quiet:
            print(f"\n== {title} ==")

    def check(self, ok: bool, label: str) -> bool:
        if ok:
            self.passed += 1
            if not self.quiet:
                print(f"  PASS  {label}")
        else:
            self.failures.append(label)
            print(f"  FAIL  {label}")
        return ok

    def skip(self, label: str) -> None:
        self.skipped.append(label)
        if not self.quiet:
            print(f"  SKIP  {label}")


# --------------------------------------------------------------------------
# Readers
# --------------------------------------------------------------------------
_PDF_LITERAL = re.compile(rb"\((?:\\.|[^\\()])*\)\s*Tj")


def _unescape_pdf(raw: bytes) -> str:
    body = raw[1 : raw.rindex(b")")]
    out = bytearray()
    index = 0
    while index < len(body):
        byte = body[index]
        if byte == 0x5C and index + 1 < len(body):
            index += 1
            out.append(body[index])
        else:
            out.append(byte)
        index += 1
    return out.decode("cp1252", errors="replace")


def read_pdf_text(path: Path) -> str:
    """Concatenate the show-text literals of an uncompressed kit-built PDF."""
    data = path.read_bytes()
    pieces = [
        _unescape_pdf(match.group(0).rsplit(b"Tj", 1)[0].strip())
        for match in _PDF_LITERAL.finditer(data)
    ]
    return "\n".join(pieces)


def read_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return read_pdf_text(path)
    return path.read_text(encoding="utf-8")


def normalise(text: str) -> str:
    """Compare on NFC text with typographic quotes folded to ASCII."""
    folded = unicodedata.normalize("NFC", text)
    for fancy, plain in (
        ("’", "'"),
        ("‘", "'"),
        ("“", '"'),
        ("”", '"'),
        ("–", "-"),
        ("—", "-"),
        (" ", " "),
    ):
        folded = folded.replace(fancy, plain)
    return folded


def accepted_ui_extensions(report: Report) -> set[str]:
    if not FRONTEND_DROPZONE.exists():
        report.skip(
            "UI dropzone accept list not readable (kit is outside the repository); "
            "falling back to the documented list"
        )
        return set(FALLBACK_UI_EXTENSIONS)
    source = FRONTEND_DROPZONE.read_text(encoding="utf-8")
    match = re.search(r'accept="([^"]+)"', source)
    if not match:
        report.skip(
            "UI dropzone accept attribute not found; falling back to documented list"
        )
        return set(FALLBACK_UI_EXTENSIONS)
    return {
        part.strip().lower()
        for part in match.group(1).split(",")
        if part.strip().startswith(".")
    }


def accepted_backend_extensions(report: Report) -> set[str] | None:
    if not BACKEND_UPLOAD.exists():
        report.skip(
            "Backend upload endpoint not readable (kit is outside the repository)"
        )
        return None
    source = BACKEND_UPLOAD.read_text(encoding="utf-8")
    match = re.search(r"_SUPPORTED_UPLOAD_EXTENSIONS\s*=\s*\{(.*?)\}", source, re.S)
    if not match:
        report.skip("Backend supported-extension set not found")
        return None
    return set(re.findall(r'"(\.[a-z0-9]+)"', match.group(1)))


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quiet", action="store_true", help="Print failures only.")
    args = parser.parse_args(argv)
    report = Report(args.quiet)

    manifest = json.loads(EXPECTED.read_text(encoding="utf-8"))
    corpus: dict[str, str] = {}

    # 1 — files exist -------------------------------------------------------
    report.section("Kit files")
    for entry in manifest["upload_order"]:
        path = KIT_ROOT / entry["path"]
        if report.check(path.exists(), f"{entry['path']} exists ({entry['role']})"):
            corpus[entry["path"]] = normalise(read_text(path))
    for extra in (
        ROI_ASSUMPTIONS,
        ROI_REPORT,
        KIT_README,
        EXPECTED,
        KIT_ROOT / "source/safety-procedure-PROC-SAFE-118.source.md",
        KIT_ROOT / "tools/generate_assets.py",
        KIT_ROOT / "tools/pdf_writer.py",
    ):
        report.check(extra.exists(), f"{extra.relative_to(KIT_ROOT)} exists")

    # 2 — upload extensions are accepted ------------------------------------
    report.section("Upload formats accepted by the current product")
    ui_extensions = accepted_ui_extensions(report)
    backend_extensions = accepted_backend_extensions(report)
    for entry in manifest["upload_order"]:
        extension = entry["extension"]
        report.check(
            extension in ui_extensions,
            f"{extension} is in the Knowledge dropzone accept list ({entry['path']})",
        )
        if backend_extensions is not None:
            report.check(
                extension in backend_extensions,
                f"{extension} is accepted by the backend upload endpoint "
                f"({entry['path']})",
            )

    # 3 — PDF really carries a text layer -----------------------------------
    report.section("PDF text layer")
    pdf_entry = next(e for e in manifest["upload_order"] if e["extension"] == ".pdf")
    pdf_text = corpus.get(pdf_entry["path"], "")
    report.check(
        len(pdf_text) > 2000,
        f"{pdf_entry['path']} exposes a selectable text layer "
        f"({len(pdf_text)} extracted characters)",
    )
    report.check("Page 1 of" in pdf_text, "PDF pages carry a numbered footer")

    # 4 — identifiers -------------------------------------------------------
    report.section("Exact identifiers")
    for identifier in manifest["identifiers"]:
        primary = identifier["primary_source"]
        report.check(
            identifier["id"] in corpus.get(primary, ""),
            f"{identifier['id']} present in its primary source {primary} "
            f"({identifier['meaning']})",
        )
        for other in identifier["also_appears_in"]:
            report.check(
                identifier["id"] in corpus.get(other, ""),
                f"{identifier['id']} also present in {other}",
            )

    # 5 — expected facts ----------------------------------------------------
    report.section("Expected answer facts and their sources")
    fact_ids: set[str] = set()
    for fact in manifest["expected_facts"]:
        fact_ids.add(fact["id"])
        declared = set(fact["supporting_sources"])
        evidenced = set(fact["evidence"])
        report.check(
            declared == evidenced,
            f"{fact['id']} declares evidence for exactly its supporting sources",
        )
        for source, snippets in fact["evidence"].items():
            for snippet in snippets:
                report.check(
                    normalise(snippet) in corpus.get(source, ""),
                    f'{fact["id"]} evidence found in {source}: "{snippet}"',
                )
        report.check(
            len(fact["statement"]) > 20, f"{fact['id']} states a checkable claim"
        )

    # 6 — multi-source requirement -----------------------------------------
    report.section("Cross-source synthesis")
    decision_prompt = next(p for p in manifest["prompts"] if p["id"] == "P1")
    sources_behind_p1 = {
        source
        for fact in manifest["expected_facts"]
        if fact["id"] in decision_prompt["expects_facts"]
        for source in fact["supporting_sources"]
    }
    report.check(
        len(sources_behind_p1) >= 4,
        f"the core decision needs {len(sources_behind_p1)} distinct sources, not one lookup",
    )

    # 7 — scoping controls ---------------------------------------------------
    report.section("Scoping controls")
    unrelated = "upload/06-unrelated-fleet-vehicle-policy-POL-FLEET-22.md"
    unrelated_text = corpus.get(unrelated, "")
    for leak in (
        "NVX-INC-4821",
        "NVX-PUMP-7742",
        "SEAL-KIT-3309",
        "SLA-PLATINUM-04",
        "PROC-SAFE-118",
        "WORKAROUND-GP-02",
    ):
        report.check(
            leak not in unrelated_text,
            f"the unrelated control document does not mention {leak}",
        )
    inventory = "upload/04-spare-parts-inventory-NVX-2026-03.csv"
    report.check(
        "conveyor_drive" in corpus.get(inventory, ""),
        "the inventory carries a decoy part from another asset class (GBX-5501)",
    )

    # 8 — abstention ---------------------------------------------------------
    report.section("Abstention question is genuinely unanswerable")
    for term in manifest["corpus_must_not_contain"]["terms"]:
        hits = [name for name, text in corpus.items() if term.lower() in text.lower()]
        report.check(
            not hits, f'no uploaded file contains "{term}" (hits: {hits or "none"})'
        )

    # 9 — prompts ------------------------------------------------------------
    report.section("Demo prompts")
    for prompt in manifest["prompts"]:
        report.check(
            all(f in fact_ids for f in prompt["expects_facts"]),
            f"{prompt['id']} references only declared facts",
        )
        report.check(
            all((KIT_ROOT / s).exists() for s in prompt["must_cite_any_of"]),
            f"{prompt['id']} expects citations from files that exist",
        )
        report.check(
            all((KIT_ROOT / s).exists() for s in prompt["must_not_cite"]),
            f"{prompt['id']} forbids citations from files that exist",
        )
        identifiers_in_prompt = [
            i["id"] for i in manifest["identifiers"] if i["id"] in prompt["prompt"]
        ]
        if prompt["id"] in {"P1", "P3", "P5"}:
            report.check(
                bool(identifiers_in_prompt),
                f"{prompt['id']} tests exact-reference retrieval "
                f"({', '.join(identifiers_in_prompt) or 'none'})",
            )
    locales = {p["locale"] for p in manifest["prompts"]}
    report.check(
        {"en", "fr"} <= locales, "the script exercises both English and French"
    )

    # 10 — ROI ---------------------------------------------------------------
    report.section("ROI model")
    assumptions = json.loads(ROI_ASSUMPTIONS.read_text(encoding="utf-8"))
    roi = compute_roi(assumptions)
    b1 = assumptions["benefit_1_search_time"]
    b2 = assumptions["benefit_2_sla_credit_avoidance"]
    b3 = assumptions["benefit_3_expedited_freight_avoidance"]
    costs = assumptions["year_one_costs"]

    expect_b1 = (
        b1["incidents_per_year"]
        * (b1["baseline_minutes_per_incident"] * b1["reduction_rate"])
        / 60
        * b1["loaded_hourly_cost_eur"]
    )
    expect_b2 = (
        b2["p1_incidents_per_year"]
        * b2["baseline_breach_rate"]
        * b2["breach_reduction_rate"]
        * b2["credit_per_breach_eur"]
    )
    expect_b3 = (
        b3["expedited_shipments_per_year"]
        * b3["avoidance_rate"]
        * b3["cost_per_expedited_shipment_eur"]
    )
    expect_cost = (
        costs["implementation_services_eur"]
        + costs["platform_and_model_runtime_eur"]
        + costs["internal_effort_hours"] * costs["internal_effort_hourly_cost_eur"]
    )
    expect_benefit = expect_b1 + expect_b2 + expect_b3
    expect_net = expect_benefit - expect_cost

    def close(a: float, b: float) -> bool:
        return abs(a - b) < 0.01

    report.check(
        close(roi["benefit_1_search_time_eur"], expect_b1),
        f"benefit 1 recomputes to EUR {roi['benefit_1_search_time_eur']:.2f}",
    )
    report.check(
        close(roi["benefit_2_sla_credit_avoidance_eur"], expect_b2),
        f"benefit 2 recomputes to EUR {roi['benefit_2_sla_credit_avoidance_eur']:.2f}",
    )
    report.check(
        close(roi["benefit_3_expedited_freight_avoidance_eur"], expect_b3),
        f"benefit 3 recomputes to EUR {roi['benefit_3_expedited_freight_avoidance_eur']:.2f}",
    )
    report.check(
        close(roi["annual_benefit_eur"], expect_benefit),
        f"annual benefit recomputes to EUR {roi['annual_benefit_eur']:.2f}",
    )
    report.check(
        close(roi["year_one_cost_eur"], expect_cost),
        f"year-one cost recomputes to EUR {roi['year_one_cost_eur']:.2f}",
    )
    report.check(
        close(roi["net_value_year_one_eur"], expect_net),
        f"net value recomputes to EUR {roi['net_value_year_one_eur']:.2f}",
    )
    report.check(
        close(roi["roi_percent_year_one"], round(expect_net / expect_cost * 100, 2)),
        f"year-one ROI recomputes to {roi['roi_percent_year_one']:.2f} %",
    )
    report.check(
        close(
            roi["payback_period_months"], round(expect_cost / (expect_benefit / 12), 2)
        ),
        f"payback recomputes to {roi['payback_period_months']:.2f} months",
    )
    report.check(
        roi["net_value_year_one_eur"] > 0, "the modeled year-one net value is positive"
    )
    report.check(
        roi["payback_period_months"] < 12, "the modeled payback lands inside year one"
    )

    report.section("ROI figures quoted in the kit and the guide")
    money = {
        "annual benefit": f"{roi['annual_benefit_eur']:,.0f}".replace(",", " "),
        "year-one cost": f"{roi['year_one_cost_eur']:,.0f}".replace(",", " "),
        "net value": f"{roi['net_value_year_one_eur']:,.0f}".replace(",", " "),
    }
    roi_percent = f"{roi['roi_percent_year_one']:.2f}"
    payback = f"{roi['payback_period_months']:.2f}"
    documents = {"roi/roi-model.md": ROI_REPORT, "README.md": KIT_README}
    if GUIDE.exists():
        documents[f"docs/{GUIDE.name}"] = GUIDE
    else:
        report.skip(f"presenter guide {GUIDE} not found")
    for label, path in documents.items():
        text = path.read_text(encoding="utf-8")
        for name, value in money.items():
            report.check(value in text, f"{label} quotes the {name} of EUR {value}")
        report.check(roi_percent in text, f"{label} quotes the ROI of {roi_percent} %")
        report.check(payback in text, f"{label} quotes the payback of {payback} months")
        report.check(
            "modeled" in text.lower() or "modelled" in text.lower(),
            f"{label} labels the figures as a model, not a measured result",
        )

    # 11 — the guide types the same prompts the manifest declares ------------
    report.section("Presenter guide prompts match the manifest")
    if GUIDE.exists():
        guide_text = normalise(GUIDE.read_text(encoding="utf-8"))
        for prompt in manifest["prompts"]:
            report.check(
                normalise(prompt["prompt"]) in guide_text,
                f"{prompt['id']} ({prompt['locale']}) is typed verbatim in the guide",
            )
        for fact in manifest["expected_facts"]:
            report.check(
                fact["id"] in guide_text,
                f"{fact['id']} is named in the guide's expected-facts tables",
            )
        for identifier in manifest["identifiers"]:
            report.check(
                identifier["id"] in guide_text,
                f"{identifier['id']} is named in the guide",
            )
        for section in (
            "Audience and outcome",
            "Five-minute preflight",
            "Main script",
            "Technical-audience expansion",
            "Failure and retry drill",
            "Reset and rehearsal",
            "Troubleshooting",
            "Capability-to-demo coverage matrix",
            "ROI calculation walkthrough",
            "Before / after scorecard",
            "Claim boundaries",
        ):
            report.check(section in guide_text, f'the guide has a "{section}" section')
    else:
        report.skip("presenter guide not found; prompt parity not checked")

    # 12 — claims a review has already rejected must not return -----------------
    report.section("Rejected claims must not reappear")
    prose: dict[str, str] = {
        str(path.relative_to(KIT_ROOT)): path.read_text(encoding="utf-8")
        for path in sorted(KIT_ROOT.rglob("*"))
        if path.is_file() and path.suffix in {".md", ".json"}
    }
    if GUIDE.exists():
        prose[f"docs/{GUIDE.name}"] = GUIDE.read_text(encoding="utf-8")
    for name, pattern, why in FORBIDDEN_CLAIMS:
        compiled = re.compile(pattern)
        offenders = []
        for label, text in prose.items():
            match = compiled.search(text)
            if match:
                offenders.append(f'{label}: "{match.group(0)[:90].strip()}"')
        report.check(
            not offenders,
            f'no file reintroduces "{name}" — {why}'
            + (f" Found in {'; '.join(offenders)}" if offenders else ""),
        )

    # 13 — the positive statements those rules protect --------------------------
    report.section("Scoping and failure-drill semantics")
    if GUIDE.exists():
        guide_raw = GUIDE.read_text(encoding="utf-8")
        report.check(
            re.search(
                r"(?is)GBX-5501[^|\n]{0,120}(?:ruled out|rule[sd]? .{0,12}out)",
                guide_raw,
            )
            is not None,
            "the guide requires GBX-5501 to be retrieved and then ruled out, not absent",
        )
        report.check(
            re.search(
                r"(?is)POL-FLEET-22[^|\n]{0,120}(?:never cited|not cited|not\b.{0,12}cited)",
                guide_raw,
            )
            is not None,
            "the guide requires POL-FLEET-22 to stay uncited",
        )
        report.check(
            "Nothing is saved when the test fails" in guide_raw,
            "the guide states the fail-closed model-setup contract verbatim",
        )
        report.check(
            re.search(
                r"(?is)cannot (?:simply )?save a broken configuration|never reaches the workspace",
                guide_raw,
            )
            is not None,
            "the guide explains why a broken configuration cannot be saved to force a failure",
        )
    else:
        report.skip("presenter guide not found; semantic guards not checked")

    # 14 — the guide references only files that exist -------------------------
    report.section("Guide and README file references")
    for label, path in (("README.md", KIT_README), (f"docs/{GUIDE.name}", GUIDE)):
        if not path.exists():
            report.skip(f"{label} not found")
            continue
        text = path.read_text(encoding="utf-8")
        referenced = sorted(set(re.findall(r"`(demo-assets/[^`\s]+)`", text)))
        for reference in referenced:
            report.check(
                (REPO_ROOT / reference).exists(),
                f"{label} references an existing path: {reference}",
            )
        report.check(bool(referenced), f"{label} points at the kit files")

    # --- verdict ------------------------------------------------------------
    print(f"\n{'-' * 72}")
    print(f"checks passed : {report.passed}")
    print(f"checks failed : {len(report.failures)}")
    print(f"checks skipped: {len(report.skipped)}")
    print(f"identifiers   : {len(manifest['identifiers'])}")
    print(f"expected facts: {len(manifest['expected_facts'])}")
    print(f"prompts       : {len(manifest['prompts'])}")
    print(f"upload files  : {len(manifest['upload_order'])}")
    print(
        f"headline ROI  : annual benefit EUR {roi['annual_benefit_eur']:.2f} | "
        f"year-one cost EUR {roi['year_one_cost_eur']:.2f} | "
        f"net EUR {roi['net_value_year_one_eur']:.2f} | "
        f"ROI {roi['roi_percent_year_one']:.2f} % | "
        f"payback {roi['payback_period_months']:.2f} months (MODELED, not measured)"
    )
    if report.failures:
        print("\nFAILED:")
        for failure in report.failures:
            print(f"  - {failure}")
        return 1
    print("\nOK: the demo kit is internally consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
