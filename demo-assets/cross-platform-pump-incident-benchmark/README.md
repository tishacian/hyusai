# Cross-platform grounded knowledge benchmark

This folder is a vendor-neutral benchmark for comparing Agentium with Dify,
AnythingLLM, Open WebUI, Microsoft Copilot Studio, custom RAG applications, or
another document-grounded assistant.

All organisations, people, dates, identifiers and financial figures are
synthetic. The corpus contains no customer or confidential information.

## What this benchmark tests

- Retrieval across Markdown, a selectable-text PDF and a CSV.
- Synthesis of facts that do not coexist in one document.
- Exact identifier retrieval and rejection of an irrelevant part.
- Claim-level citations that open the real supporting source.
- Follow-up memory without repeating the subject.
- Safe refusal when the corpus does not contain the answer.
- A French question answered from French and English evidence.
- Failure visibility, retry and execution evidence where the product supports it.

## Fair-comparison rules

1. Use a new empty workspace or knowledge base for every product.
2. Use the same model and model version where the products support it.
3. Disable web search, general knowledge and external connectors.
4. Upload only the files in `upload/`; do not upload this README or the expected answers.
5. Start with each product's documented default retrieval settings. Record a second
   tuned run separately instead of silently changing the default result.
6. Do not add facts from `reference/EXPECTED-ANSWERS.md` to a system prompt.
7. Start a new conversation for each full benchmark run. P2 must follow P1 in the
   same conversation; the other prompts can be separate turns.
8. Record ingestion time, answer latency, citations, settings changes and failures.
9. Score only what is visible in the answer or its opened sources.
10. A confident unsupported statement scores worse than a clear abstention.

## Setup

1. Create a new knowledge base or collection named `pump-incident-benchmark`.
2. Upload these five core files together:
   - `01-incident-brief-NVX-INC-4821.md`
   - `02-safety-procedure-PROC-SAFE-118.pdf`
   - `03-service-level-policy-SLA-PLATINUM-04.md`
   - `04-spare-parts-inventory-NVX-2026-03.csv`
   - `06-unrelated-fleet-vehicle-policy-POL-FLEET-22.md`
3. Wait until every file reports ready/indexed. Record the elapsed time.
4. Bind only this collection to the assistant, application or agent under test.
5. Confirm that no web-search tool or unrelated collection is active.
6. Run P1 through P4 in order. P2 must be in the same conversation as P1.
7. Upload `05-note-de-service-NOTE-SVC-77.md`, wait until it is indexed, then run P5.
8. If the product supports controlled failure testing, run P6. Otherwise mark the
   recovery criteria `N/A`, not zero.
9. Complete `RESULTS-TEMPLATE.md` and `SCORECARD.csv` for that product.

## Prompts

### P1 — multi-source operational decision

> For incident NVX-INC-4821 on pump NVX-PUMP-7742, can the pump be restarted now, which spare part is required, where is that part in stock, and by when must the repair be finished under SLA-PLATINUM-04?

Expected: restart prohibited; `SEAL-KIT-3309`; zero at `DEPOT-AUR`, three at
`HUB-LYS`, six-hour transfer; repair deadline `2026-03-03 07:10 UTC`.

### P2 — conversational follow-up

> If that part cannot arrive before the deadline, which temporary measure is allowed, what are its limits, and does it stop the restoration clock?

Expected: `WORKAROUND-GP-02`; maximum 48 hours; 60% nominal flow; level 3
reliability-engineer approval; it does not stop the restoration clock.

### P3 — exact identifiers and decoy rejection

> Show the inventory line for SEAL-KIT-3309 and the inventory line for GBX-5501. Which of the two is relevant to NVX-INC-4821, and why?

Expected: both rows are retrieved; `SEAL-KIT-3309` is compatible with
`NVX-PUMP-7742`; `GBX-5501` is a conveyor-drive part and is irrelevant.

### P4 — unsupported question

> What is the remaining manufacturer warranty period on NVX-PUMP-7742, and who is the warranty contact at the pump manufacturer?

Expected: the product explicitly says the corpus contains neither fact and does
not invent a warranty period, company, person, telephone number or email address.

### P5 — multilingual evidence

> Pour l'incident NVX-INC-4821, qui doit approuver la mesure temporaire WORKAROUND-GP-02 et dans quel délai l'approbation doit-elle être consignée ?

Expected in French: Yara Oduya is the designated level 3 reliability engineer;
approval must be recorded within 30 minutes. The answer should use the French
service note and the English procedure.

### P6 — failure and retry, where supported

> Repeat the restoration plan for NVX-INC-4821 as a numbered checklist a technician can follow on site.

Temporarily make the configured model unreachable without deleting the knowledge
base. Submit P6, record the error experience, restore the model, and retry the
same turn. The product should preserve the question, avoid raw secrets or stack
traces, and return a cited checklist after recovery.

## Scoring

Use `SCORECARD.csv`. The normalized core score is 100 points:

- Factual correctness: 50
- Citation correctness and source usability: 20
- Safe abstention: 10
- Follow-up memory: 5
- Multilingual grounding: 5
- Evidence UX: 5
- Setup and operational clarity: 5

Recovery is recorded separately because not every comparison product exposes a
testable execution/runtime layer. Never award factual points for an uncited fact
when the product claims to be source-grounded.

The canonical facts, acceptable wording and required source mapping are in
`reference/EXPECTED-ANSWERS.md`. Keep that file away from the product being tested.
