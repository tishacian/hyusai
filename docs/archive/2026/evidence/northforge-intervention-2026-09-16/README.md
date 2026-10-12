# NorthForge intervention resources — inventory and seed input

Read-only inspection of the live Showcase found three collections: documents,
NorthForge Expert Fiches, and NorthForge Notices. No dedicated intervention
history collection was present. The native decide_next_v1 and semantic_search_v1
Skills exist with their structured decision and query/results contracts.

The history document here derives directly from the existing Operational
Analysis ROWS (NF-01 through NF-04). It adds no causes, dates, technicians or
machine associations. In particular NF-04 must not be assumed to concern the
PMP-700. The notices remain the existing PMP-700/BRG-22 corpus.

The script `backend/scripts/showcase_intervention.py` defines fixed notice,
history, missing-information and out-of-mandate cases. Its regression test
verifies each rendered record matches the canonical dataset. This file has not
yet been ingested, and two workspace-scoped retrieval tools are not yet installed
or exercised. No tool-choice success is claimed.

Next qualification must pin each tool to its intended authorized resource,
prevent payload collection overrides and broad fallback, then execute both
questions with real retrieval and the canonical AgentLoop. Aggregate arithmetic
continues through SQL/Polars, not a retrieval answer.


## Live ingestion and retrieval

Created the dedicated synthetic collection through the authenticated document
API on Showcase, then uploaded the Markdown through the normal multipart route.
Worker job `947e90c5-5546-4534-8226-b69ceb814312` completed in approximately 23 s:
one document, one Qdrant chunk, nine extracted document facts, BM25 ready.
Collection: `b3fa0e81-e6c5-468d-b89c-af13bf5e138d`.

A real `/documents/search` query for NF-04 returned the correct source document
and the passage containing 30 planned / 55 actual minutes. The reported scope
contains only the intervention-history collection, with no fallback reason.
`ingestion-and-search.json` retains the upload, worker and retrieval evidence.
This qualifies ingestion and direct retrieval, not yet AgentLoop tool selection.
No application image or client configuration was changed.

## Read tools installed

After f63f1eaf deployed the pinned-collection guard, the canonical Skills API
created `northforge_notices` and `northforge_history` in the Showcase workspace.
Each uses the existing semantic_search_v1 wrapper with its own frozen collection.
The retained API responses are in `tools.json`. No AgentLoop execution or
successful tool-selection claim follows from creation alone.
