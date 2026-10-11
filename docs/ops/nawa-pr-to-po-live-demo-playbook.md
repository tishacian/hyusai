# Nawa PR to PO — live desk playbook (Fayçal)

**Audience:** Fayçal (handout) and the presenter.  
**Language of the desk:** English.  
**Last verified:** 31 August 2026 on live SHA `34731192`. English desk copy uses **brief** (not dossier). Hard-reload the tab (`Ctrl+Shift+R` / `Cmd+Shift+R`).

| Give this | To whom |
|---|---|
| This markdown (or the Word) | Fayçal — the four proofs and the walkthrough |
| [`nawa-pr-to-po-live-demo-presenter-fr.md`](nawa-pr-to-po-live-demo-presenter-fr.md) | Presenter — one French page to hold during the talk |
| [`nawa-pr-to-po-live-demo-playbook.docx`](nawa-pr-to-po-live-demo-playbook.docx) | Same content, illustrated, for a printed / emailed handout |

This is the **operator desk**. It is not a numbered demo script. The four proofs live **in this document**. On screen you only see work.

---

## 1. Open this URL

```
https://agentium.papai.ai/work/pr-to-po?workspace=nawa&lang=en
```

Hard-reload (`Ctrl+Shift+R` / `Cmd+Shift+R`) so the browser does not keep an old bundle.

| Field | Value |
|---|---|
| Page title | **PR to PO** |
| Eyebrow | NAWA · AI factory |
| Workspace | `nawa` |
| Login (presenter) | `thibaud.ishacian@datategy.net` |
| Live SHA | `347311924faba4fc6686a05c3318cb5d2415fa2a` |
| System | `PR to PO` (`28345b5a-0824-4f2b-a420-ebe0aa7cd34f`) |
| Binding | `procurement.pr_to_po.run` → published v2 (`b9217063-b512-48e8-a444-835867a3de76`) |
| SAP | Live Hikma MCP. **No HANA.** |
| Write | **Sealed.** The BAPI package is composed, never sent. TESTRUN is banned. |

Subtitle on the desk: *System → Flow → Run → Decision. The factory reads Hikma, compiles a brief, and writes nothing to SAP until you decide.*

---

## 2. What Fayçal must see (four proofs)

The screen does **not** number these. You point at the matching card.

| # | Proof | Where you point | What must be true |
|---|---|---|---|
| 1 | Live SAP MCP | KPI row, stations, then **Read selected requisition** and the brief facts | `get_A_PurchaseRequisitionItem` returns open **ZNPR** items. `get_A_PurchaseRequisitionItem_by_key` / `get_A_PurchaseReqnItemText` feed the text. `listTaskCollection` feeds the approval task. `fi_Validate` and `get_A_PurReqnAcctAssgmt` feed budget. `get_A_PurchaseOrder` filtered by plant purch org (`orderby=PurchaseOrderDate desc`) feeds the most recent supplier. Compile station shows `python_recipe_v1`. |
| 2 | Small agentic task | **Summarise** in the compiled brief | `azure_llm_v1` `POST /chat/completion` `prompt_type: factual` turns the live justification into two clear sentences. Invent nothing. |
| 3 | PO POST package | **Draft / Purchase order composed for SAP** | Server `bapi_po`, tool `BAPI_PO_CREATE1`, method POST, type **ZLPO**, Send **Sealed**. JSON: `sealed: true`, `called: false`, `testrun: false`. Purch org and company code = plant. Currency from the PR. Delivery date overridden to a future workday. Success = honest composed BAPI package, not a live create. |
| 4 | Nice-to-have | **Ask the factory** and **Open the portal** | Read-only. Chips: Plant supplier, Orders read, Next step, Write status. The write stays sealed. |

If the Write station says **Sealed**, that is correct.

---

## 3. Walkthrough (about three minutes)

1. Hard-reload the URL. Header reads **PR to PO**. Four counts. Five stations. Write = **Sealed**.
2. Click **Run the factory**. Wait until Compile is **Done** and the hero reads something like *Brief compiled on STICKER WHITE — plant supplier 1000000018.*
3. **Proof 1.** Point at the counts and the tools under the stations. Click **Read selected requisition** if justification is empty. The brief facts name the live tools.
4. **Proof 2.** Click **Summarise**. Two sentences appear via `azure_llm_v1`.
5. **Proof 3.** Scroll to **Draft / Purchase order composed for SAP**. Read the row: POST · bapi_po · `BAPI_PO_CREATE1` · Send **Sealed**. Open the JSON. Say: *this is the BAPI we would send; it is not sent. Type ZLPO. TESTRUN is banned.*
6. **Proof 4.** Chip **Write status**. Answer: the write stays sealed.

There is no button that posts a purchase order.

**Talk track:** *This is the PR to PO factory. It reads Hikma through MCP, compiles a brief, and writes nothing until a human decides.*

---

## 4. Screen map

### Top of the desk

Lineage (Application · System · Run), briefing, counts, stations, compiled brief. Actions sit in the brief header: **Read selected requisition**, **Summarise**.

![Top of the desk](nawa-pr-to-po-playbook-figures/desk-top.png)

### Compiled brief (proofs 1 and 2)

Facts name their tools. Justification via `get_A_PurchaseRequisitionItem_by_key`. Summary via `azure_llm_v1`.

![Compiled brief](nawa-pr-to-po-playbook-figures/dossier.png)

### Draft purchase order (proof 3)

Kicker **Draft**. Title **Purchase order composed for SAP**.  
Hint: *Draft purchase order. It is not sent; the write stays sealed.*  
Row: Method POST · Server bapi_po · Tool `BAPI_PO_CREATE1` · Send **Sealed**.  
Footnote: *Write stays sealed. The live path is BAPI_PO_CREATE1 type ZLPO then BAPI_TRANSACTION_COMMIT. TESTRUN is banned.*

![Draft POST](nawa-pr-to-po-playbook-figures/post.png)

### Ask the factory (proof 4)

Hint: *Questions about the live reads. The write stays sealed.*  
Placeholder: *Who is the plant supplier?*

![Ask the factory](nawa-pr-to-po-playbook-figures/ask.png)

### Portal

Hint: *Answers from the requisitions and orders just read. The write stays sealed.*  
Stay on get-PR / get-PO questions. Older summarise prompts in the portal thread are session history, not a second write.

![Portal](nawa-pr-to-po-playbook-figures/portal.png)

---

## 5. Live example (31 August 2026, SHA `34731192`)

| Field | Value |
|---|---|
| Headline | Brief compiled on **PAPER BAG** — plant supplier `1000000018`. |
| Voice | The factory read open ZNPR requisitions, approvals and plant orders. It keeps PAPER BAG, proposes the most recent plant supplier and type **ZLPO**. The SAP write stays sealed. |
| Counts | Requisitions 50 · Tasks 2 · Orders 20 · Receipts 0 |
| Stations | Connect **Done** · Read **Done** (`get_A_PurchaseRequisitionItem`) · Compile **Done** (`python_recipe_v1`) · Decide **Ready** · Write **Sealed** |
| Selected requisition | PAPER BAG via `get_A_PurchaseRequisitionItem` |
| Approval task | Release TR transaction 1000008 56B 200 via `listTaskCollection` |
| PR id (in the POST) | `2000276449` item `00020` |
| Justification | STICKER WHITE via `get_A_PurchaseRequisitionItem_by_key` (item text on this PR is not always the selected line) |
| Summary | *The request is to purchase white stickers. No further justification details are provided in the text.* via `azure_llm_v1` |
| Supplier | Most recent `get_A_PurchaseOrder` on purch org = plant (`1000000018`). Not the material-group majority. |
| Order type | **ZLPO** for ZNPR. Never NB. Do not take `ZSVO` from plant history. |
| Budget | ok via `fi_Validate` |
| POST | `bapi_po` `BAPI_PO_CREATE1`, `DOC_TYPE` **ZLPO**, `PURCH_ORG` = `COMP_CODE` = `1000`, `CURRENCY` QAR, `INCOTERMS2L` Doha, `DELIVERY_DATE` `20260914`, `sealed: true`, `called: false`, `testrun: false` |

**Ask → Write status:** *No. The write station stays sealed. A cycle can compile a brief; SAP is not written until you decide.*

The exact PR can move on a later read. The **tools** and the **sealed POST** must not.

---

## 6. Exact labels on the desk

Taken from `frontend-ng/src/app/core/i18n/experience.dict.ts` (English).

| Place | English |
|---|---|
| Title | PR to PO |
| Primary | Run the factory |
| Secondary | Start a cycle |
| Sources | Connections |
| Brief | Compiled brief / Compiled from the live SAP reads. |
| Brief facts | Selected requisition · Approval task · Plant supplier · Order type · Justification · Justification summary · Budget |
| Brief actions | Read selected requisition · Summarise |
| Draft card | Draft · Purchase order composed for SAP |
| Draft row | Method · Server · Tool · Send |
| Ask | Ask the factory · Ask · Plant supplier · Orders read · Next step · Write status |
| Portal | Open the portal · Factory portal · Close the portal |
| Stations | Connect · Read · Compile · Decide · Write |
| Station status | Done · Ready · Blocked · Sealed |
| KPIs | Requisitions · Tasks · Orders · Receipts |

Banned on this desk: pipeline, workflow, job.  
Removed from this desk: Success criteria, numbered beats 1–4, Shown / Play / Waiting, *Compose the POST is the success of this demo*.

---

## 7. Seven-minute script

| Time | Do | Say |
|---|---|---|
| 0:00 | URL, `nawa`, English, hard-reload | “Operator desk. Not a slide.” |
| 0:30 | Counts + stations | “Live SAP, through MCP. No HANA.” |
| 1:30 | Brief + **Read selected requisition** + **Summarise** | “One short model call. Two sentences. Nothing invented. Nothing written.” |
| 3:00 | Draft card | “Type ZLPO, BAPI_PO_CREATE1, sealed, not sent. TESTRUN is banned.” |
| 5:00 | Chip **Write status**, then **Open the portal** if there is time | “Questions on the reads we just did.” |
| 6:30 | Stop | Write still **Sealed**. Offer **Start a cycle** only if they ask. |

---

## 8. If something looks wrong

| Symptom | What to do |
|---|---|
| Old tiles “1 Live SAP / 2 Agentic / Shown / Play” or a Success criteria strip | Hard-reload. Those tiles were removed on `cd40fe33`. |
| Blank desk / login loop | Login, then hard-reload **this** desk URL. Do not open `/` first in an automated session (it clears the token). |
| `token expired` or HTTP 407 on MCP | Restart the Hikma Cloud Foundry MCP apps. This is **not** an Agentium password problem. |
| Counts at 0 | Click **Run the factory** once and wait. A timeout on `tools/call` often recovers on the next run. |
| Empty justification | **Read selected requisition** once, then **Summarise** once. Do not spam. |
| No draft card | Need a live ZNPR line and a plant supplier. Run the factory again. |
| Write station still Sealed after Run | Correct. |
| Goods receipts 0 / Limited read | Expected. `sap_gr` is often 403. Do not dwell. |
| Portal shows older summarise prompts | Session history. Ask a get-PR / get-PO question. Do not treat it as a write. |
| Someone asks to create the PO live | Refuse. The write stays sealed until a human approves in NAWA. Do not call `BAPI_PO_CREATE1` or `BAPI_TRANSACTION_COMMIT` from the desk. The composed package is the artefact. |

---

## 9. Do not

- Do not post a purchase order. No `tools/call` on `BAPI_PO_CREATE1`, `BAPI_TRANSACTION_COMMIT`, or `post_A_PurchaseOrder`. TESTRUN is banned.
- Do not call `fi_EnableForPurchasing` or `fi_Discard`.
- Do not invent MCP aliases (`A_*`, `YY1_*`).
- Do not turn HANA on (`sap_hana_connector` stays off).
- Do not seed the `nawa` workspace on this VM.
- Do not move the `demo-agentic` tag for this slice.
- Do not put the four proofs back on the screen as numbered tiles.
- Do not put a password or an OAuth secret on a slide.

---

## 10. Technical anchors

| Item | Value |
|---|---|
| Studio route | `/work/pr-to-po?workspace=nawa&lang=en` (`/work/pr-to-po/desk` redirects here) |
| Studio | `frontend-ng/src/app/features/experience/work/pr-to-po-studio.component.ts` |
| Run projection | `frontend-ng/src/app/features/experience/work/pr-to-po-studio.ts` (client of the server run — no SAP call from the browser) |
| Server runtime | `backend/app/services/connectors/mcp/flow.py` (DAG `pr_to_po_flow`), write gate `backend/app/services/connectors/mcp/write.py` |
| Behavioural contract | `frontend-ng/e2e/tests/18-nawa-agent-studio-canary.spec.ts` |
| Copy | `frontend-ng/src/app/core/i18n/experience.dict.ts` |
| Images | `agentium-{backend,worker,frontend}:347311924fab` |
| Rollback of this desk slice | `AGENTIUM_IMAGE_TAG=cd40fe337285` |
| Writes via `/read` | HTTP 400 `not a read` |
| Presenter card (FR) | `docs/ops/nawa-pr-to-po-live-demo-presenter-fr.md` |
| Illustrated Word | `docs/ops/nawa-pr-to-po-live-demo-playbook.docx` |
| Word builder | `docs/ops/build-nawa-pr-to-po-playbook.py` |
| Figures | `docs/ops/nawa-pr-to-po-playbook-figures/` |
