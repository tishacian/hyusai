# Retrieval → synthesis: preserve accepted evidence

The [actual 0f06b4eb Run](../release-0f06b4eb-2026-09-17/README.md)
retrieves a valid passage but loses it at synthesis. The answer agent reapplied
a cosine threshold to the hybrid RRF score (0.0164), ignoring the actual dense
score (0.7217) already checked by the canonical retriever.

The duplicate filtering/sorting block is removed. Inline and worker retrieval
already share thresholding, permissions, source policy and ranking. Citation
selection/deduplication and final source gating remain intact. No new exemption,
provider, setting, dependency, permission or client-theme change is introduced.

The regression traverses canonical thresholding, the actual answer-agent stream,
the captured model prompt and emitted citations. High-dense and sparse-only
hybrid evidence survives. Low dense evidence is still removed in both naive and
hybrid retrieval. On the old code the two valid hybrid cases fail; on the fixed
code all four pass. The LLM in this test is a recorder, not provider qualification.

Local gates: 137 backend tests; 1,512 frontend tests; i18n (8,077 keys), nav-links,
UI chrome and production build pass. Existing build/deprecation warnings remain.
Live same-question verification and carakai checks on the new candidate remain
pending; do not attribute the earlier actual Giskard campaign to this new code.
