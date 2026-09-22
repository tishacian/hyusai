# Automation-first roadmap

## Porte 0 — Le premier objet est une automation

Status: **URLs archived. The run finished; the output is not minutes.**

Evidence: `docs/evidence/porte-0-spark365-2026-09-22/README.md`.
System `2302c304-01ee-4bbd-9514-4fc57c167b43`, Run `8591bc37-fd79-4cd1-806a-b13d3032b1b6`.
The bound skill is `llm_rag_answer_v1` and answered with the retrieval fallback.

Done:

- primary Create composer is `New automation`;
- generated object is a canonical System draft;
- graph starts as `Trigger → Agent → Output`;
- palette is reduced to four primitives;
- draft-run remains primary and publication is deferred;
- backend contract proves draft admission without publication.

Acceptance still required:

1. process-owner account, not platform admin;
2. create SPARK-365 meeting minutes;
3. paste a transcript;
4. run the draft;
5. inspect the resulting draft and Run;
6. record System URL, Run URL and time to green;
7. confirm six or fewer product concepts are visible before the first run.

## Porte 1 — Deux verbes seulement

Status: **deployed. Run and Publish are on the bar. The draft card still says “Test draft” and “SERVER DRAFT R2”.**

Automation mode now shows **Run** directly and keeps **Publish** as the second
labelled verb. Save, Operate, More, runtime jargon, draft revision and hash are
removed from the primary bar. Autosave and the explicit publication review
remain unchanged.

## Porte 2 — Blocs gouvernés

Status: **closed on Nawa, 22 Sep 2026.** Retrieve returned a cited passage and document `a11da396-f296-5e64-9b90-4d58a5574eb9` (run `b3c8e9ad-769d-434c-9f0b-520515302e42`). SAP write stayed sealed, `called: false`, reason `unattended` (run `700d208c-f917-4b84-8143-85e50a2e59be`). That same pause is the decidable card on [Porte 2 approvals](https://agentium.papai.ai/work/porte-2-approval/validations).

After Porte 1:

- SAP preview/write block with named human decision and reconciliation;
- Retrieval block returning the cited passage and original;
- Work approval queue backed by the same paused Run decision.

## Boucle — Éditer le Flow déjà gouverné

Status: **steps 1–5 in code, not deployed.** The catalog refuses an eighth block. A patch is applied only against the hash just read, and a save that is not that patch fails. An explanation cannot patch, a run cannot edit, and there is no publish or approve tool. The turn reuses the existing draft test: a Retrieve cites or says there is no passage, and a SAP write without Approval stays sealed. The automation Flow page shows what was read, whether the save matched the patch, and the run when the intention allows one. This sits after Porte 2 and before Porte 3. It does not import the five Sim blocks, and it does not start publication, the Work job, or the Hypervisor export.

A chat turn on an automation may only explain the Flow, edit it, run the draft, or ask for a clarification. An edit only adds, links, or removes blocks that already exist in the automation palette. It does not invent a node type.

Closed catalog. Each entry is a node the engine already runs. The `edit` tool schema accepts only these types. Any other slug is a refusal.

| Block | Contract already in place |
|---|---|
| Trigger | Input `transcript`. |
| Agent | `workspace_llm_v1`. Instruction and transcript. No knowledge base. |
| Decision | Branch on a condition. |
| Approval | Human gate. Output `decided_by`. |
| Retrieve | `semantic_search_v1`. Outputs `passage` and `source`. |
| SAP write | `sap_create_po_v1`. With no person: `sealed`, `called: false`. |
| Output | The Flow result. |

Out of scope: Sim blocks `start_trigger`, `function`, `agent`, `condition`, `response`; the NAWA Copilot source, its prompt, and its OpenRouter transport; publication, the Work job, and the Hypervisor export (those stay Porte 3); unlocking SAP, RPA, or HANA without the human `decided_by` already required.

The loop, ten steps maximum. Changes already verified stay. The turn stops after that.

1. **Intention.** Classify the message as `explain`, `edit`, `run`, `edit_and_run`, or `clarify`. Only `edit` and `edit_and_run` receive the write tool. Only `run` and `edit_and_run` receive the test. `explain` and `clarify` only read.
2. **Read.** Read the current draft: nodes, edges, revision, hash. No write on a Flow that was not just read.
3. **Patch.** A list of adds, updates, and removals, plus the edges. Existing identifiers are kept. When Approval and SAP write are both in the graph, Approval comes first and `decided_by` links them.
4. **Read back.** Save, read again, compare nodes and edges to what was sent. If the hash changed between the read and the write, abandon and read again. If the save differs, fail and do not claim it is done.
5. **Draft test.** Only when the intention allows it. Reuse the existing draft test, not a new engine. The shown result is the run: passage and source, or `sealed` / `called`, or the Approval pause.

Tools: everyone can read the draft and the catalog. `edit` and `edit_and_run` can patch. `run` and `edit_and_run` can start the draft. There is no Publish tool and no tool that approves in place of a person. The Work queue remains the only place `decided_by` is set.

Build order. Each step ships alone. The next step starts only when the previous one fails closed.

1. The catalog and the refusal. Describe the seven blocks and fail a patch that asks for an eighth. No model call.
2. Read and read-back. A mechanical patch, a save, a comparison. Fail if the graph moved in between.
3. Intention in front of the tools. An explanation cannot call the patch. A run request cannot edit.
4. The draft test on this loop. A Retrieve cites or says there is no passage. A SAP write without Approval stays sealed.
5. The chat on the automation Flow page. The turn shows what was read, patched, and verified, and the run when there is one.

Exit: a sentence such as “add a cited search, then an approval before the SAP write” produces a draft whose read-back shows Retrieve, Approval, and SAP write, with `decided_by` linked. The test with no person leaves the write sealed. Publication has not moved.

## Porte 3 — Work et portefeuille

After the edit loop:

- published automation becomes a Work job;
- Hypervisor explains objective, convention, gap and proof;
- exportable run package serves finance/COMEX review.
