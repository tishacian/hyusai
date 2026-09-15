# Observability live qualification

The script `scripts/qualification/observability_live.py` exercises real model calls, Runs, evaluations, reviewed draft corrections and persisted comparisons in **agentium-showcase**. It creates only dedicated `OBS QA` assets. It never modifies an existing PIH, Andritz, NAWA or Workspace Chat System, a shared Skill, a client application, workspace permissions or model configuration.

This is **agent-assisted technical QA**, separate from human acceptance, a HITL decision and the five-person usability study. The script does not publish its candidate or claim business savings.

## Actual reference corpus

Collection `5c0f10fa-c7ff-499a-bd99-6efda2a98fb1`, `agentium-showcase-notices`, currently has nine synthetic Markdown notices and eleven indexed chunks. A read-only inspection retrieved:

- `northforge-pmp-700-operating-manual.md`: **700 bar** continuous duty; relief valve **735 bar**.
- `northforge-pmp-700-maintenance.md`: maintenance every **2000 operating hours**, **LUB-40**, **18 g per bearing**.

The script retrieves these actual chunks again and verifies their content, source IDs and fingerprints before proceeding. It records that retrieval occurred through `/documents/search`, outside the System. The Run contains frozen source inputs; no retrieval invocation is invented. This qualification proves source-backed generation and the correction/comparison connection, not an autonomous in-Flow RAG retrieval route.

## Execution

Run from the exact released checkout on carakai. Credentials are read within the process from `/root/.attestation-username` and `/root/.attestation-password`, or explicit file arguments. Never copy them into commands, reports or logs.

```sh
sudo python3 scripts/qualification/observability_live.py --report /tmp/obs-preflight.json
sudo python3 scripts/qualification/observability_live.py --prepare --report /tmp/obs-live-qualification.json
```

`--prepare` creates one isolated authored prompt Skill, one dedicated draft System and a three-case suite. It executes the baseline and its evaluation, then persists the first correction proposal **without applying it**. The report retains every created identifier, even after a failure.

Review the report's baseline result, evaluation, proposed diff and `candidate_template_sha256`. The candidate adds citation, fidelity and missing-information instructions while preserving both input placeholders. It does not insert pressure, maintenance or other expected answers. If the baseline is already correct, record that fact; do not force an incorrect response for the demonstration.

Choose an additional question **after** reviewing the patch, outside the three stored cases. Resume using the reviewed hash:

```sh
sudo python3 scripts/qualification/observability_live.py --qualify \
  --report /tmp/obs-live-qualification.json \
  --reviewed-template-sha256 '<reviewed hash from report>' \
  --holdout-question '<newly chosen question>'
```

The five cycles each run the baseline, evaluate it, apply the same reviewed bounded template change to the dedicated draft and compare three identical cases through canonical Runs. Only the dedicated QA draft is reset between cycles. Applied proposals retain their historical revisions. Finally, a new holdout Run and evaluation are preserved, and saved-proposal discovery is checked through the API.

Every unavailable evaluator, stopped worker, unsupported provider, schema refusal, timeout, failed assertion or corpus drift stops qualification and remains in the report. A completed campaign with zero results cannot pass. Improvements and unchanged results are counted separately. Contains-based assertions check exact quantities, citation tokens and the agreed absence phrase; they are limited controls, not a comprehensive assessment of the answer.

## Manual interface acceptance

Use the persisted identifiers to complete this checklist without copying identifiers between product screens:

1. Open the baseline Run from its result. Explain execution, evaluation and human-decision states separately.
2. Select an examined claim and open its supporting passage. Confirm its real filename and preserved source content. Record any missing association.
3. Open the correction, inspect the two templates and diff. Confirm the Skill and published version remain unchanged.
4. Open Flow. Confirm the referenced node is selected and the source Run remains accessible. Make an unsaved edit and verify a server correction cannot overwrite it.
5. Open the comparison. Read improved, unchanged and regressed cases individually, including the absent-information case.
6. Open a second browser session and return through Quality or the plain Run route. Discover the saved proposal and reopen the comparison.
7. Review the holdout answer against the sources; record a human verdict separately. Its automatic evaluation is not that verdict.
8. Repeat with keyboard navigation, zoom, narrow viewport, FR/EN and dark/light themes.

Record each result as PASS, FAIL or NOT RUN, with timestamp, served SHA, workspace, actor role, Run/proposal/campaign references and a screenshot when relevant. User-study timings and unaided task completion remain **NOT RUN** until actual participants perform them.
