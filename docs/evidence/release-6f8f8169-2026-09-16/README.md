# Release 6f8f8169 — source cells and server Golden verdicts

16 September 2026. **Deployed from pushed `demo/agentic`:**
`6f8f81696db0a736c2facfa32e97976d4d55db09`.

## Delivered / livré

Excel citations open the referenced worksheet and cell range, including rows
beyond the first 40. Original coordinates and selection remain visible. Missing
or invalid locators fail explicitly. Preview actions and states are FR/EN; its
surfaces follow existing light/dark tokens. PDF/OCR page aliases are consistent.

Golden verdicts come from the server. A completed execution without an expected
value remains **unevaluated**; a failed assertion is distinct from an execution
failure; human/debug waits remain pending. Existing unmarked historical cases
are not retroactively scored.

Les citations Excel ouvrent leurs cellules d’origine. Les résultats Golden
séparent exécution terminée, contrôle réussi/échoué et absence de référence.
Aucune publication de System, décision humaine ou bascule de flag n’a été faite.

## Gates and deployment

- [131 scoped backend tests](backend.log) passed on the grouped candidate.
- [1,479 frontend tests](../document-cell-preview-2026-09-16/frontend-unit.log)
  passed, plus the final [7-test Chat rerun](../document-cell-preview-2026-09-16/frontend-focused.log).
- i18n **8,015 keys**, fail-closed navigation, UI chrome guard and
  [production build](../document-cell-preview-2026-09-16/frontend-build.log) passed.
  Existing bundle/CommonJS warnings remain.
- All three [immutable images and revision labels](images.log) were built on
  omnirag-demo with the required args, including `INSTALL_GISKARD_RAGET=true`
  for the worker. Giskard SDK 2.19.2, `pip check` and mocked offline qualification
  passed. This is **not** a live provider campaign.
- No migration. [Storage checks before/after](storage.log) passed.
  [Six application services switched](deploy.log); infrastructure untouched.
- Exact [backend](public-build-info.json) and [frontend](frontend-build-info.json)
  public revisions verified, [homepage HTTP 200](home-http.log),
  [backend/frontend healthy and zero startup exception matches](runtime-health.log).
  The initial startup probe returned 502 while backend health was starting;
  subsequent public revision and health checks passed without restarting it.
- [Carakai canaries](canaries.log): **10 passed, 2 intentional local-contract
  skips**, 2.0 minutes. Includes Work, Studio, branding isolation, LiveKit config,
  Hypervisor and exact-Run chart/evaluation links. Artifact directory:
  `/tmp/iteration-canaries-20260916T202721Z.BF559u`.

The runner first stopped before tests because the source SHA marker lacked its
required newline; the next attempt stopped because sudo PATH lacked the pinned
Node binary. Restoring the exact marker format and selecting the existing
`node-current/bin` runtime resolved both. No guard, dependency lock or test was
relaxed, and neither failed preflight executed application tests.

Build logs live on the VM at
`/srv/agentium-data/roadmap-deployments/2026-09-16-6f8f81696db0/`.
The root disk reached 658 MB free during the build. Two inspected, untagged,
unreferenced frontend build stages from 15 September were removed without force;
[cleanup log](build-cache-cleanup.log). Tagged images, rollback versions and all
volumes were retained. Approximately 2.8 GB remained afterward; capacity still
needs attention before further large builds.

## Three real Golden previews

The [qualification script](qualify_golden.py) freezes all three expectations
before submission, uses the retained Operational Analysis graph with SHA
`f1cdd9b755357f0960c334129f09e9106c63c4a49d9fa1937829dc01ae59d14d`,
and submits one idempotent batch in Showcase. It changes no draft or publication.

| Case | Actual server result | Run |
|---|---|---|
| Fixed numerical reference | completed · passed | [116f940a](https://agentium.papai.ai/runs/116f940a-5415-47cf-b112-798ef1638e21) |
| Deliberately wrong expected overrun of −1 | completed · failed | [89e386e2](https://agentium.papai.ai/runs/89e386e2-9a11-4235-8eb4-ee92a0a1d2e8) |
| No expected value | completed · unevaluated | [45373f9c](https://agentium.papai.ai/runs/45373f9c-9ac4-434f-af27-4c7144290827) |

All three produced the canonical four-order result: **120 planned, 155 actual,
+35 minutes, 3 late orders, NF-04 +25**. Each retains two completed Python
invocations and one real OpenAI invocation. Durations were about 20.9, 20.3 and
17.5 seconds. The [retained result and invocation evidence](golden-verdicts.json)
includes provider-reported tokens and qualified costs: LLM cost is calculated
from catalog unit pricing, not an invoice or measured business saving.

The same request key returns exactly the same three Run IDs. The negative
control is intentionally false; it is not a regression in the arithmetic, and
its expected value was never adjusted after observing output. These are Golden
previews (`flow_version_id: null`) compiled from the retained graph, not new
published-version executions or a baseline/candidate improvement comparison.

## Remaining acceptance

The [local real-component screenshots](../document-cell-preview-2026-09-16/README.md)
cover FR/light desktop and EN/dark mobile. Live source retrieval → Excel preview,
OCR/ingestion recovery, five complete R2 repetitions and Capture voice reuse
remain open. The authenticated human browser is still at sign-in, so no current
manual Work/PIH/Quality walkthrough or video is claimed here. R0 baseline remains
0/5 business and 0/5 developer sessions; R1 human approval/publication/second-user
acceptance is unchanged. Technical release success does not close those gates.

Rollback: `b4fde677a75a`. Use the documented `up` with that immutable tag; no
rollback of database writes and no moving-tag change. Native NAWA theme files,
permissions and adoption defaults were not changed.
