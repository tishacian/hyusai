# Agentium benchmark result — 2026-09-16

## Run configuration

- Product: Agentium OS v0.4.0, local development build
- Model shown in the UI: `claude-opus-5`
- Retrieval trace: `chah backend`
- Knowledge collection: `documents`, six indexed documents, 161 chunks
- Workspace: Alice's workspace
- Web search and external connectors: not used
- Core score: **91 / 100**
- Recovery test P6: **not run**; recorded separately from the 100-point core score

## Prompt results

| Test | Result | Evidence |
| --- | --- | --- |
| P1 multi-source decision | Pass with omissions | Correctly prohibited restart, cited 11.4 versus 7.1 mm/s RMS, identified `SEAL-KIT-3309`, reported 0 at `DEPOT-AUR`, 3 at `HUB-LYS`, six-hour transfer, and calculated the 2026-03-03 07:10 UTC deadline. It omitted the two-certified-technician and 5.5-hour repair requirements, and did not state service-credit terms in P1. |
| P2 conversational follow-up | Pass | Correctly resolved “that part” and returned `WORKAROUND-GP-02`, maximum 48 hours, 60% nominal flow, level 3 approval, operating limits, and that the restoration clock continues. It also supplied the service-credit terms. |
| P3 exact identifiers and decoy | Pass after product fix | Returned both requested inventory lines and correctly rejected `GBX-5501` as a conveyor spare unrelated to the pump incident. Before the fix, “inventory line” was incorrectly routed to collection-inventory handling. |
| P4 safe abstention | Pass | Explicitly stated that warranty period and manufacturer contact were absent and invented neither. |
| P5 multilingual grounding | Pass | Answered in French; named Yara Oduya, identified the level 3 role, and stated the 30-minute logging deadline. Citations covered the English procedure PDF and French service note. |

## Scorecard

| Category | Score | Notes |
| --- | ---: | --- |
| Factual correctness | 43 / 50 | Full credit except partial F3 because P1 omitted two technicians and 5.5 hours, and zero for F6 because P1 omitted service-credit terms. |
| Citation correctness and source usability | 20 / 20 | Required source types were cited; citation controls expose the source content; the unrelated fleet policy was never cited. |
| Safe abstention | 10 / 10 | P4 abstained without inventing warranty facts. |
| Follow-up memory | 5 / 5 | P2 resolved the prior part and incident without identifiers being repeated. |
| Multilingual grounding | 5 / 5 | P5 combined French and English evidence and answered in French. |
| Evidence UX | 5 / 5 | Inline numbered citations, expandable sources, and source preview were available and usable. |
| Setup and operational clarity | 3 / 5 | Upload/indexing was clear, but an indexed collection was not automatically bound to Quick ask and required a separate Chat & Sources defaults step. |
| **Total** | **91 / 100** | Strict score against the supplied vendor-neutral rubric. |

## Defects found during the run

1. **Fixed: exact inventory-row prompt misclassification.** The phrase “inventory line” was treated as a request to list knowledge collections. The RAG intent rules now classify `inventory line` and `stock line` as table-value lookup language. A focused regression test passes.
2. **Configuration UX issue: indexed does not mean active.** The `documents` collection was indexed but initially absent from Quick ask's default source scope. Adding it under Chat & Sources and saving defaults restored correct retrieval.
3. **Auto-QA false positive.** Agentium displayed `Composite 72/100` with hallucination breaches for P5, although the cited service note explicitly contains Yara Oduya, substitute approver Serge Lemoine, and the 30-minute deadline. The external benchmark score therefore uses the supplied ground truth rather than that incorrect internal warning.

## Verification

- Agentium frontend: running on `http://127.0.0.1:4210`
- Backend: running on `http://127.0.0.1:8000`
- Focused regression test: `1 passed, 83 deselected`
- `git diff --check`: clean
