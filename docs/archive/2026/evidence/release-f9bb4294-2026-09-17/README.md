# Release f9bb4294 — conversation retrieves the published Capture

Deployed from `demo/agentic`: `f9bb429438119e2d9a2a5e90aa28fae51807a964`.
Three immutable images built on `omnirag-demo`, tag `f9bb42943811`.
Rollback: `fd9238fa6e4a`. No migration, flag change or NAWA theme edit.

[Local gates](local-checks.log): **292 backend tests**, **1,493 frontend tests**,
8,048 translation keys, navigation/chrome checks and production build pass.
Backend scope includes Capture service/API, RAG retrieval profiles, chat stream
hardening and Skill wrappers. Replacement now selects the Context collection even
when workspace defaults supply a Knowledge Scope; combine remains unchanged and
an executor's authoritative collection contract keeps priority.

[Images](images.log), [idle consumers](pre-switch-final.log),
[storage/worker qualification](storage-worker.log), [healthy services](health.log),
[backend SHA](backend-build-info.json), [frontend SHA](frontend-build-info.json),
[HTTP 200](home-http.log) and [zero startup exception matches](startup-error-count.log)
are retained. Giskard 2.19.2's worker check uses fixture models, not a new provider
campaign. [Carakai canaries](canaries.log): **10 passed, 2 intentional skips**;
artifacts `/tmp/iteration-canaries-20260916T235343Z.CW3Zmt`.

## Same document and question, new conversation

The [previous conversation failure](../release-fd9238fa-2026-09-17/capture-conversation-failure.json)
remains unchanged. No Capture regeneration, publication or review was repeated.
The [qualification script](recheck-capture-conversation.py) checks the live SHA,
loads the same Context and source preview, then submits exactly one new chat
request. It records intent before submitting and refuses an uncertain replay.

[Actual result](capture-conversation.json):

- Context `ebd6f6b2-8030-47af-b09b-98269bc51094` selects `qa-capture-fd92`.
- Document `8b2756be-df4c-5984-96d0-e171baddd5f6` still contains the corrected,
  explicitly synthetic statement and prohibition on real intervention.
- Question: “Quelle est la pression nominale retenue dans la fiche R2CAP4771 ?
  Cite le passage qui la justifie.” No expected answer is supplied to the model.
- Completed Run: [`985090d3-6b9e-48f9-a7a7-044c516a0a22`](https://agentium.papai.ai/runs/985090d3-6b9e-48f9-a7a7-044c516a0a22).
- Answer: “6 bar”, with the exact quote “La pression nominale est fixée à 6 bar.”
  Citation [1] carries the same document ID, filename and collection.
- The workspace's existing expert-fiche overlay also remains in the searched
  collections. This is not proof of exclusive single-collection retrieval.

This proves one technical text correction → publication → sourced conversation.
The fixture's earlier acceptance was explicitly automated technical QA; the
response's “fiche experte — validée” wording does not establish human acceptance.
No retained R1 Run or decision was changed.

## Remaining discrepancy and qualification

The [live collection inventory](capture-inventory.json) still reports `created`,
zero sources and zero chunks, despite the publication receipt and real retrieval.
Capture publishes directly through DocumentService but does not update the
canonical collection source ledger/counters. This remains a concrete R2 issue;
it has not been hidden by changing the inventory or re-publishing the fixture.

R2 remains open: source ledger consistency, UI handoff to a new scoped chat,
voice interruption/correction/reconnection, absence-before-Capture, five
consecutive repetitions and human trials are not established here. R0's current
manual smoke and the ten formative sessions remain open. The user browser was
still on Agentium sign-in; automated carakai tests are recorded separately.
