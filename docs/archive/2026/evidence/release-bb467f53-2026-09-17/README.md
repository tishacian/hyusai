# bb467f53 — the actual retrieved spreadsheet citation is readable

Deployed pushed `demo/agentic` SHA `bb467f534d40b2bfa1faf624b32d726f8e405e4c`,
immutable tag `bb467f534d40`, 17 September 2026 Europe/Paris.

- [Local qualification](../wide-citation-preview-2026-09-17/README.md): 66 backend
  tests, 1,487 frontend tests, FR/EN 8,048 keys, navigation/chrome guards,
  production build and FR/light + EN/dark mobile component captures passed.
- Three [VM-built images](images.log), [build completion](image-build.log),
  [worker dependency and offline Giskard checks](worker-gates.log).
- [Storage checks](storage.log) passed before and after the switch. No migration.
  Preflight found no queued/running recipes, WorkerJobs or WorkspaceJobs; both
  Celery consumers were idle. Infrastructure and retained Runs unchanged.
- [Exact backend](backend-build-info.json) and [frontend](frontend-build-info.json)
  SHA, [healthy services](health.log) and homepage 200. Initial 502 while starting
  resolved without restarting; zero backend exception matches before QA.
- [Carakai](canaries.log): **10 passed, 2 intentional local-contract skips**, 2.1m.
  Artifacts: `/tmp/iteration-canaries-20260916T223355Z.1DEiky`.
- Rollback: **`37056391d6cc`**, preserving writes. Full build/switch logs:
  `/srv/agentium-data/roadmap-deployments/2026-09-17-bb467f534d40/`.

## Same retrieval hit, same original, readable cells

[Read-only recheck](citation-recheck.json) and [helper](recheck-citation.py)
use the exact rank-1 hit that [failed on 37056391](../release-37056391-2026-09-17/README.md).
No narrower citation, new upload or replacement job was used.

- Job `5fe4e00b-79d7-467a-82ba-ec42da735513` and its serialized state are unchanged.
- Hit `b563926c-8123-5b92-8893-d1f67b1f86e9_chunk_3` still cites
  `Interventions & notes!A830:O831`.
- The preview now includes column O: N830=`NF-04`, O830=`55`, N831=`NF-05`, O831=`0`.
  The selected range is complete; the surrounding workbook remains an excerpt.
- Downloaded original SHA-256 still matches the uploaded fixture.

The native PDF page/original qualification from 37056391 is retained at its own
SHA.

## Image-only scan: real OCR and retrieval

The [scan fixture](Invoice_INV-8834_Synthetic_Scan.pdf) rasterizes the same
explicitly synthetic repository invoice; it does not introduce another business
dataset. [Fixture checks](ocr-fixture.json): one image-only page, zero native text
characters; rendered page visually inspected before upload.

[Real API evidence](ocr-qualification.json), [qualification script](qualify-ocr.py),
[completed check](ocr-after-canaries.log):

- Dedicated collection `qa-document-ocr-bb467f53`; job
  `a5d9f323-8571-48c6-90c4-03ea0376dcbe`, real Celery task
  `e0717ebd-f8b6-43b6-9b50-b959780bb818`, completed in 23.7 seconds.
- One indexed chunk; retrieval contains `INV-8834` and `9,860.00`, with page 1.
- A persisted `document_ocr_text` fact records `tesseract_local`, model
  `tesseract:eng+fra`, page 1. This is actual OCR, not native text extraction or
  a mocked provider. PP-OCR and OpenAI vision are not qualified by this result.
- PDF preview resolves; downloaded original matches the uploaded scan's SHA-256.
- The first attempt failed at authentication with 401 before any upload or state
  creation, while canaries were running ([original log](ocr.log)). After canaries
  finished, login and the single upload succeeded. No credential/security setting
  was changed. The cause of the transient authentication failure is not established.

This qualifies the exact reference identifiers, amount and page of one clean
scan. It does not establish broad OCR accuracy, table reconstruction, poor-scan
performance or five repeated user journeys.

Current authenticated manual smoke, human baseline (0/5 business, 0/5 developers),
voice/text Capture reuse, R1 human review/publication and second-user acceptance
remain open. This release does not close R0/R1/R2. NAWA and adoption defaults unchanged.
