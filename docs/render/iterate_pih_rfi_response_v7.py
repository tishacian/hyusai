#!/usr/bin/env python3
"""RFI Response v7 — from v6, propagating the PIH clarification register
(issued 10 July 2026): B6 on-site core squad, D14 three inference models
(neutral), E16 SAP-access answer, C8 reference implementation, C9/C10
capability discovery, C12 toolchain disclosure, E17 golden-set IP, F19
at-risk proposal, F20 perpetual use licence. DRAFT marking -> v7."""
import os
from docx import Document

HERE = os.path.dirname(os.path.abspath(__file__))
PIH = os.path.join(HERE, "..", "pih")
SRC = os.path.join(PIH, "RFI-PIH-AI-Factory-Response-v6.docx")
OUT = os.path.join(PIH, "RFI-PIH-AI-Factory-Response-v7.docx")

doc = Document(SRC)


def replace_paragraph(par, segments):
    """Replace paragraph content with (text, bold) segments, keeping the
    first run's font as the template."""
    template = par.runs[0].font if par.runs else None
    for run in list(par.runs):
        run._element.getparent().remove(run._element)
    for text, bold in segments:
        run = par.add_run(text)
        run.bold = bold
        if template is not None:
            run.font.size = template.size
            run.font.name = template.name


def set_cell(cell, text):
    first = cell.paragraphs[0]
    if first.runs:
        first.runs[0].text = text
        for run in first.runs[1:]:
            run.text = ""
    else:
        first.add_run(text)
    for par in cell.paragraphs[1:]:
        for run in par.runs:
            run.text = ""


def find_paragraph(startswith):
    for par in doc.paragraphs:
        if par.text.strip().startswith(startswith):
            return par
    raise LookupError(startswith)


# ---------------------------------------------------------------- DRAFT marking & date
for par in doc.paragraphs:
    if "DRAFT v6" in par.text:
        for run in par.runs:
            if "DRAFT v6" in run.text:
                run.text = run.text.replace("DRAFT v6", "DRAFT v7")
            if "‹ 14 July 2026 ›" in run.text:
                run.text = run.text.replace("‹ 14 July 2026 ›", "20 July 2026")

# ---------------------------------------------------------------- pending boxes -> resolved
RESOLVED = "✔ PIH CLARIFICATION RECEIVED (register of 10 July 2026) — "
box_updates = {
    "⚠ PENDING PIH CLARIFICATION — Q5 (consortium/prime structure) and Q8": RESOLVED
    + "PIH accepts consortium structures with a single named prime (B5); Datategy responds as an "
    "autonomous prime with no subcontracting. Abstraction Layer components are in build (C8); "
    "see §7 for our reference-implementation proposition.",
    "⚠ PENDING PIH CLARIFICATION — Q21 (mobilisation/interim payment)": RESOLVED
    + "a mobilisation payment on signature is confirmed (F21), and the 30%/15% reuse targets are "
    "design targets, not contractual commitments (F18). The commercial figures above stand as "
    "submitted; the reuse measurement method in §5 is our proposed refinement per Q2A.1.",
    "⚠ PENDING PIH CLARIFICATION — Q16 (non-production SAP environment availability)": RESOLVED
    + "fewer than 10 priority SAP agents across FI, MM, SD, HCM and FI-AA for the Phase 1 pilot "
    "(A3); the pilot plan and pricing stand. On SAP access (E16): the publicly available "
    "S/4HANA/BTP sandboxes are sufficient for capability development and demonstration at RFI "
    "stage — our response does not depend on further access. PIH non-production access is "
    "required only from contract, for four things generic sandboxes cannot provide: "
    "representative master data and organisational structures to calibrate agent business "
    "rules; production-aligned authorisation objects and roles to validate mandates and "
    "privileged writes; real transaction volumetry to size the parallel run and establish the "
    "Finance baseline; and integration with PIH transport/change management. None of this "
    "bears on our RFI pricing assumptions.",
    "⚠ PENDING PIH CLARIFICATION — Q5 (consortium structure) conditions": RESOLVED
    + "Datategy responds as an autonomous prime (B5). SAP module SMEs are fielded as part of "
    "the on-site core squad during the Phase 1 pilot (B6, see §4); named individuals and CVs "
    "at shortlist stage.",
    "⚠ PENDING PIH CLARIFICATION — Q8 (Abstraction Layer / AI Control Tower": RESOLVED
    + "Abstraction Layer components and the AI Control Tower are in build, and PIH is open to a "
    "partner-contributed reference implementation under PIH governance, branding and IP terms "
    "(C8). Datategy proposes Agentium as the transitional reference implementation: "
    "immediately operational at mobilisation, exposed through MCP-compliant interfaces, "
    "operated under PIH governance and branding, with API specifications handed over so PIH's "
    "own components take over without rework as they reach production readiness. This removes "
    "the pilot's dependency on components still in build, protects the October go-live, and "
    "preserves the portability PIH requires. Per C9/C10, a capability-discovery exercise "
    "against existing Hikmah components is run at engagement start: we integrate with and "
    "extend Hikmah through the Abstraction Layer and do not build competing implementations "
    "of the same function; any alternative category tool we propose is MCP-compliant, "
    "lock-in-free and explicitly justified.",
    "⚠ PENDING PIH CLARIFICATION — Q13/Q14 (sensitivity tiers": RESOLVED
    + "private or sovereign inference is required for Internal, Confidential and PIH-IP data; "
    "public data may route to approved SaaS endpoints (D13). PIH does not commit to "
    "provisioning sovereign GPU capacity (D14). Three infrastructure models are therefore "
    "described in §3.3 and Annex B — cloud-hosted sovereign (Azure Qatar, PIH tenancy), "
    "partner-provided (optional managed service), and PIH-provisioned on-premise capacity — "
    "with the implications and cost treatment of each. Our routing framework applies the data "
    "classification per agent at design-card stage.",
    "⚠ PENDING PIH CLARIFICATION — Q19 (at-risk fee": RESOLVED
    + "the at-risk percentage is deferred to PIH Procurement at RFP stage, and respondents are "
    "invited to propose their view (F22). Our proposal: a modest at-risk portion of 5–10% of "
    "each wave's build fees, tied to objective wave gates — agents passing the six go-live "
    "acceptance criteria — in addition to the adoption holdback described in §12, with "
    "aggregate at-risk exposure (wave-gate at-risk plus adoption holdback) capped at 15% of "
    "any wave's fees. We do not propose indexing at-risk fees to Finance-confirmed value, "
    "which also depends on PIH-retained change management; PIH's clarification confirms value "
    "is measured at process level with both parties as necessary conditions.",
}
boxes_done = set()
for tbl in doc.tables:
    if len(tbl.rows) == 1 and len(tbl.columns) == 1:
        current = tbl.rows[0].cells[0].text.strip()
        for prefix, new_text in box_updates.items():
            if current.startswith(prefix):
                set_cell(tbl.rows[0].cells[0], new_text)
                boxes_done.add(prefix)
assert len(boxes_done) == len(box_updates), f"boxes not found: {set(box_updates) - boxes_done}"

# ---------------------------------------------------------------- commercial table (§3)
for tbl in doc.tables:
    for row in tbl.rows:
        if row.cells[0].text.strip() == "Private / sovereign inference":
            set_cell(row.cells[1], "Three infrastructure models, per PIH clarification D14")
            set_cell(
                row.cells[2],
                "Cloud-hosted sovereign (Azure Qatar, PIH tenancy): $0 Datategy fee, GPU "
                "consumption billed PIH–cloud provider. Partner-provided: optional managed "
                "service, priced before commitment. PIH-provisioned on-premise: $0 Datategy "
                "infrastructure fee; deployment as Complex/first-of-type or T&M, model "
                "operations available as an annual subscription.",
            )

# ---------------------------------------------------------------- §3.3 inference (D14)
par = find_paragraph("Commercial structure & trajectory (Q5A.2)")
replace_paragraph(par, [
    ("Commercial structure & trajectory (Q5A.2) — ", True),
    (
        "Where PIH approves Azure/SaaS endpoints, Datategy charges $0 and PIH pays its cloud "
        "provider directly at the applicable tariff. For private/sovereign inference — required "
        "for Internal, Confidential and PIH-IP data per clarification D13 — three infrastructure "
        "models are available, since PIH does not commit to provisioning sovereign GPU capacity "
        "(D14): (1) cloud-hosted sovereign — open-weight or approved models served on "
        "PIH-controlled Azure Qatar GPU capacity, consumption billed directly between PIH and "
        "its cloud provider, no Datategy fee, mobilisable within weeks; (2) partner-provided — "
        "Datategy-operated dedicated capacity as an optional managed service, subject to PIH "
        "data-residency approval, scoped and priced before commitment; (3) PIH-provisioned "
        "on-premise — PIH-procured GPU capacity with Datategy deploying and operating the "
        "model-serving stack, setup scoped as Complex/first-of-type or T&M and ongoing model "
        "operations available as an annual subscription; procurement lead time applies. Each "
        "agent's routing across these models follows its data classification at design-card "
        "stage. Across all models we target a −30–50% reduction in cost per execution over 12 "
        "months through caching, right-sized routing and prompt optimisation, measured against "
        "a jointly agreed baseline and reviewed quarterly — a jointly managed optimisation "
        "target, not a guaranteed reduction.",
        False,
    ),
])

# ---------------------------------------------------------------- §4 mobilisation (B6)
par = find_paragraph("Mobilisation & team (Q2B.1)")
replace_paragraph(par, [
    ("Mobilisation & team (Q2B.1) — ", True),
    (
        "per PIH clarification B6, our core delivery squad — Factory Lead, SAP module SMEs "
        "(FI/MM/SD/HCM/FI-AA coverage) and QA lead — is physically present in Qatar for the "
        "Phase 1 pilot, from mobilisation through go-live stabilisation. Supporting roles "
        "operate hybrid/remote under PIH security and data-residency controls: solution "
        "architecture, agent build cells and the evaluation harness are delivered by the "
        "Datategy AI & Data Center of Excellence. Mobilisation plan: week 1–2 factory "
        "onboarding (access, environments, Abstraction Layer interfaces, data-quality audit "
        "kickoff) with the core squad on-site; weeks 3–13: build and parallel run; go-live per "
        "PIH gates. On-site/remote split, named individuals and visa/accommodation logistics "
        "are declared in the mobilisation plan; travel and accommodation at cost.",
        False,
    ),
])

# ---------------------------------------------------------------- §5 coding agents (C12)
par = find_paragraph("• AI coding agents (Q2A.3)")
replace_paragraph(par, [
    ("• AI coding agents (Q2A.3) — ", True),
    (
        "our build track is AI-assisted end-to-end (code agents for flow scaffolding, test "
        "generation, connector stubs), with governance aligned to PIH's clarification C12: our "
        "AI coding toolchain is disclosed at mobilisation, all generated code is committed to "
        "PIH Git repositories under PIH IP terms, and every merge passes human review through "
        "the PR and review-agent process — generated code is subject to the same golden-set "
        "regression and security validation as hand-written code. Observed effect on recent "
        "deliveries: 25–40% cycle-time reduction on authoring and test coverage; measurement "
        "methodology shared at shortlist stage.",
        False,
    ),
])

# ---------------------------------------------------------------- §8 golden sets (E17)
par = find_paragraph("• Ground truth & contamination (Q4A.1)")
replace_paragraph(par, [
    ("• Ground truth & contamination (Q4A.1) — ", True),
    (
        "golden sets are created at design-card stage from real historical cases (including "
        "refusal and escalation cases) under the shared-responsibility model of PIH "
        "clarification E17: PIH provides source-data access and the SMEs who validate labels; "
        "Datategy structures, labels and maintains the datasets under PIH governance. All "
        "labelled datasets are PIH IP, versioned and stored in PIH repositories — not on "
        "Datategy systems — and refreshed quarterly. Contamination is prevented structurally: "
        "the live path never reads evaluation data, and our regression tooling asserts it "
        "(anti-overfit test).",
        False,
    ),
])

# ---------------------------------------------------------------- §13 post-build / IP (F20)
par = find_paragraph("After the Factory build programme")
replace_paragraph(par, [
    (
        "After the Factory build programme, the Enterprise Platform & Managed Operations "
        "Baseline covers the first 50 live agents. PIH may operate agents itself or appoint "
        "another operator; delivered flows, design cards, evaluation evidence and documented "
        "connector mappings are handover-ready. If PIH requests direct L1 functional end-user "
        "assistance, Datategy offers Enhanced End-User Support as an optional per-agent "
        "service; it is separate from technical AgentOps, incident response and product "
        "support. Consistent with PIH clarification F20, PIH receives a perpetual, "
        "royalty-free, non-exclusive licence to use and execute accepted delivered agent "
        "versions within the PIH environment, without dependence on a continued commercial "
        "relationship with Datategy. This covers delivered and accepted versions; it does not "
        "include future product releases or upgrades, does not transfer Agentium product IP or "
        "source code — updates, compatibility, regression and N3 support remain part of the "
        "post-build continuity regime.",
        False,
    ),
])

# ---------------------------------------------------------------- §9 lived risk examples (Q4E.1)
par = find_paragraph("‹ TO COMPLETE — Q4E.1")
replace_paragraph(par, [
    ("• Lived examples (Q4E.1) — ", True),
    (
        "(1) Data quality on an industrial corpus: for a global industrial engineering group, we "
        "deployed a grounded retrieval assistant over a multi-million-chunk multilingual "
        "technical corpus. The design-stage corpus audit revealed that a material share of "
        "documents carried conflicting revisions and OCR-hostile legacy scans — answers built "
        "on them would have been confidently wrong. We stopped the build, quarantined "
        "superseded revisions, added provenance and version-control gates to ingestion, and "
        "re-baselined the golden set on the cleaned corpus before resuming; the assistant went "
        "live with grounded, cited answers meeting its quality thresholds. This experience is "
        "why we treat data-quality sign-off as a hard gate before build — aligned with PIH's "
        "clarification that master-data remediation is PIH-owned and escalated at design "
        "stage. (2) Integration depth on an ERP-triggered estate: for a European automotive "
        "financial-services group, a recurring timeout on one critical interface propagated in "
        "cascade through the ESB across a heterogeneous estate (mainframe to ESB), repeatedly "
        "blocking nightly financing batches. We mapped the dependency chain, instrumented logs "
        "and metrics end-to-end (multi-million-line pipelines on Spark) and moved supervision "
        "from reactive to predictive — risk windows are anticipated and watched before they "
        "block the business. This is why our SAP approach signs interface contracts and maps "
        "downstream dependencies before any code is written, and why every posting flow "
        "carries a mandatory parallel run.",
        False,
    ),
])

# ---------------------------------------------------------------- §13 lived incident (Q8.3)
par = find_paragraph("‹ TO COMPLETE — Q8.3")
replace_paragraph(par, [
    ("• Lived incident (Q8.3) — ", True),
    (
        "on a production retrieval assistant we operate for a global industrial engineering "
        "group, continuous quality scoring flagged a groundedness decay within hours of a "
        "scheduled corpus refresh (issue): the refresh batch had introduced a document set "
        "with mixed-language OCR artifacts that polluted retrieval. Response: the affected "
        "index was rolled back to the previous validated snapshot within the restore SLA, the "
        "agent remained live throughout, and the exception was ledgered and reported to the "
        "business owner the same day. Permanent fix: an ingestion quality gate now blocks "
        "corpus updates failing format and language checks, the failing cases were added to "
        "the golden set, and every corpus update runs the pre-publication regression suite "
        "before it can reach the live index. The incident and its fix are documented in the "
        "runbook and fed back into the pattern library.",
        False,
    ),
])

# ---------------------------------------------------------------- §12 adoption holdback + aggregate cap
par = find_paragraph("• Adoption-linked structure (Q5B.3)")
replace_paragraph(par, [
    ("• Adoption-linked structure (Q5B.3) — ", True),
    (
        "we accept linking a portion of outcome payments to adoption: proposal — up to 10–15% "
        "of the per-agent outcome fee held back against adoption thresholds set per agent type "
        "after a 4-week post-go-live baseline (indicative commitment: ≥70% active usage on "
        "assistive agents at T+90 days), released monthly on measured metrics; clawback "
        "accepted within the holdback envelope (no uncapped clawback). Aggregate at-risk "
        "exposure — this adoption holdback plus the wave-gate at-risk portion proposed for "
        "F22 — is capped at 15% of any wave's fees.",
        False,
    ),
])

# ---------------------------------------------------------------- §2 stale capability-table residues
for tbl in doc.tables:
    for row in tbl.rows:
        for cell in row.cells:
            if "‹structure depends on consortium clarification›" in cell.text:
                set_cell(
                    cell,
                    "Named SAP module experts to be presented at shortlist, contracted directly "
                    "by Datategy as prime (per PIH clarification B5).",
                )
            elif "Reference deployment on Databricks to be documented. ‹TO COMPLETE›" in cell.text:
                set_cell(cell, "Reference deployment on Databricks: evidence at shortlist stage.")
            elif cell.text.strip().endswith("Named Datategy SAP module experts confirmed at shortlist."):
                # Duplicate of the adjacent gap-column sentence; keep the capability statement only.
                set_cell(
                    cell,
                    "Agentic + integration engineering proven on SAP-adjacent estates "
                    "(SuccessFactors, ERP triggers).",
                )

# ---------------------------------------------------------------- cosmetic placeholders (no chevrons)
for par in doc.paragraphs:
    for run in par.runs:
        if "‹reference details to confirm for shortlist›" in run.text:
            run.text = run.text.replace(
                "‹reference details to confirm for shortlist›",
                "Reference details are confirmed at shortlist stage.",
            )
        if "(‹ under NDA ›)" in run.text:
            run.text = run.text.replace("(‹ under NDA ›)", "(shared under NDA)")
        if "(‹ at shortlist ›)" in run.text:
            run.text = run.text.replace("(‹ at shortlist ›)", "(provided at shortlist stage)")

# ---------------------------------------------------------------- §15 drop unclear reference mention
for par in doc.paragraphs:
    for run in par.runs:
        if "‹additional Gulf telecommunications reference subject to clearance›" in run.text:
            run.text = run.text.replace(
                " ‹additional Gulf telecommunications reference subject to clearance›", ""
            )

# ---------------------------------------------------------------- §14 remove Kenneth's row (not participating)
for tbl in doc.tables:
    for row in list(tbl.rows):
        if any("Kenneth Ezukwoke" in cell.text for cell in row.cells):
            row._element.getparent().remove(row._element)

# ---------------------------------------------------------------- SAP S/4HANA production evidence (Andritz, anonymised)
# In production on the same industrial account: agentic campaign generation for
# spare-parts aftermarket, collecting the required data from SAP S/4HANA.
par = find_paragraph("• Integration & compliance experience")
replace_paragraph(par, [
    ("• Integration & compliance experience — ", True),
    (
        "integration patterns applied on SAP-centred estates: live S/4HANA integration in "
        "production for a global industrial engineering group — agents collect master and "
        "transactional data from SAP S/4HANA (installed base, parts consumption, order "
        "history) to generate targeted spare-parts aftermarket campaigns; event-driven "
        "triggers from SuccessFactors (joiner/mover/leaver states), OData reads for master "
        "and transactional data, BAPI/RFC wrapped as typed skills with bounded retries and "
        "idempotency, IDoc/CDC where streaming is required. Financial-posting context: "
        "parallel run against human postings on identical transactions, weekly GL "
        "reconciliation during hypercare, external SoD review before the go-live gate.",
        False,
    ),
])

par = find_paragraph("• 4 · Enterprise knowledge & retrieval at industrial scale")
replace_paragraph(par, [
    ("• ", False),
    ("4 · Enterprise knowledge, retrieval & SAP-integrated agents at industrial scale — ", True),
    (
        "grounded, cited assistant over a multi-million-chunk technical corpus for a global "
        "industrial engineering group — hybrid retrieval, evaluation harness, expert "
        "knowledge capture. On the same account, in production: S/4HANA-integrated agents "
        "collecting installed-base and parts data from SAP to generate targeted spare-parts "
        "aftermarket (upsell) campaigns.",
        False,
    ),
])

par = find_paragraph("Acknowledged gap per the RFI's reference criteria")
replace_paragraph(par, [
    ("Acknowledged gap per the RFI's reference criteria: ", True),
    (
        "our references include S/4HANA-integrated agents in production (reference 4, "
        "read-side data collection driving aftermarket campaigns) but not yet an SAP "
        "financial-posting agent delivery. Named Datategy SAP module experts and relevant "
        "financial-posting evidence will be presented at shortlist stage.",
        False,
    ),
])

for tbl in doc.tables:
    for row in tbl.rows:
        if row.cells[0].text.strip().startswith("SAP — S/4HANA"):
            set_cell(
                row.cells[1],
                "S/4HANA integration in production (agentic data collection driving "
                "aftermarket campaigns for a global industrial engineering group); agentic + "
                "integration engineering on SAP-adjacent estates (SuccessFactors, ERP "
                "triggers).",
            )

# ---------------------------------------------------------------- §16 open clarifications
par = find_paragraph("• Open clarifications")
replace_paragraph(par, [
    ("• Clarification register — ", True),
    (
        "we submitted 21 written clarification questions on 7 July 2026; PIH's responses "
        "(register of 10 July 2026) are consolidated throughout this document — programme "
        "sizing and the 40/40/20 tier mix, on-site delivery structure, Abstraction Layer "
        "status and reference implementation, sovereign inference models, SAP environment "
        "access, reuse-target status, IP licensing and mobilisation payment. Two items remain "
        "open at RFP stage: the at-risk fee percentage (deferred to PIH Procurement — our "
        "proposal is stated in §12) and full domain-level agent specifications (provided to "
        "shortlisted respondents).",
        False,
    ),
])

doc.save(OUT)
print("saved:", OUT)

# ---------------------------------------------------------------- verification
import re
import zipfile

xml = zipfile.ZipFile(OUT).read("word/document.xml").decode("utf-8")
txt = re.sub(r"<[^>]+>", " ", xml)
txt = re.sub(r"\s+", " ", txt)
for needle in [
    "DRAFT v7",
    "physically present in Qatar for the Phase 1 pilot",
    "cloud-hosted sovereign",
    "PIH-provisioned on-premise",
    "perpetual, royalty-free, non-exclusive licence",
    "publicly available S/4HANA/BTP sandboxes",
    "transitional reference implementation",
    "capability-discovery",
    "committed to PIH Git repositories",
    "All labelled datasets are PIH IP",
    "5–10% of each wave's build fees",
    "Low $120 · Medium $140 · High $160",
    "Lived examples (Q4E.1)",
    "Lived incident (Q8.3)",
    "groundedness decay",
    "capped at 15% of any wave's fees",
    "Observed effect on recent deliveries",
    "S/4HANA-integrated agents",
    "spare-parts aftermarket",
    "S/4HANA integration in production",
]:
    assert needle in txt, f"missing: {needle}"
for stale in [
    "DRAFT v6",
    "⚠ PENDING PIH CLARIFICATION",
    "delivered remote-first",
    "owned jointly",
    "At the time of submission no responses had been received",
    "‹ TO COMPLETE — Q4E.1",
    "‹ TO COMPLETE — Q8.3",
    "‹ 14 July 2026 ›",
    "telecommunications reference subject to clearance",
    "‹internal metric to finalise›",
    "‹percentages to validate internally›",
    "‹structure depends on consortium clarification›",
    "Databricks to be documented. ‹TO COMPLETE›",
    "‹reference details to confirm for shortlist›",
    "‹ under NDA ›",
    "‹ at shortlist ›",
    "Named Datategy SAP module experts confirmed at shortlist.",
    "Kenneth Ezukwoke",
]:
    assert stale not in txt, f"stale: {stale}"
print("all checks passed")
