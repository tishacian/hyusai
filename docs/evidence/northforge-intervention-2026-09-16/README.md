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
