# Porte 0 — SPARK-365 human run

Checked 22 September 2026 on https://agentium.papai.ai, release
`d4a75119faa4a50ced08a959505023dc2fac3db5` (`revision_verified: true`).
Account: `thibaud.ishacian@datategy.net` (builder session, not a fresh
process-owner account).

## URLs

- System: https://agentium.papai.ai/systems/2302c304-01ee-4bbd-9514-4fc57c167b43/flow
- Run: https://agentium.papai.ai/runs/8591bc37-fd79-4cd1-806a-b13d3032b1b6
- API: `GET /api/v1/runs/8591bc37-fd79-4cd1-806a-b13d3032b1b6`
- Stream: `GET /api/v1/runs/8591bc37-fd79-4cd1-806a-b13d3032b1b6/stream`

The run was dispatched at 08:18:58 local (06:18:58Z) and the terminal closed
`DONE` at 08:19:12. Input was a synthetic transcript (Maya / Omar / Lina).

## Result

The run completed. The agent output was not meeting minutes. It returned the
retrieval fallback: “No relevant knowledge base context is available for this
question.” The bound skill on the canvas is `llm_rag_answer_v1`, not a minutes
prompt. Porte 0’s “green minutes” acceptance is therefore not met.

## Porte 1 visual check on the same screen

Visible, as required: **Run**, **Publish**, canvas controls (fit, undo), save
pill **SAVED**.

Still visible before the result, contrary to the acceptance list:

- card copy “Test draft runs this saved revision”;
- badge **SERVER DRAFT R2**;
- button **WORKBENCH**;
- Run dialog still says “JSON object”, “Draft entry point”, “Request authority”,
  “Debug metadata”.

Save, Operate and More are absent from the automation bar. The Run button’s
visible label is Run (aria-label remains “Execute on backend”).

Screenshot: [toolbar.png](./toolbar.png).
