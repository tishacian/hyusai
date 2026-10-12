# Runtime release — 16 September 2026

Deployed application: **7532d4491a239d0e2285303cb12447ceac7419c2**, from
`origin/demo/agentic`. Previous runtime: `196164eb5b8098dca49cf54a7c06c4df05cc8b79`.
No database migration or adoption-default change.

- [Local gates](local-gates.json): 1,460 frontend tests, 216 backend tests,
  i18n/navigation/chrome and production build passed. The full local frontend
  attempt exhausted temporary disk space; all 157 spec files then passed in
  40 batches. These are not an independent CI attestation.
- [Concurrent pair](concurrent.json): both Runs overlapped and passed in
  22.604 seconds. Exact arithmetic, two completed Python invocations per Run,
  LLM completion, immutable Flow reference and idempotent replay verified.
- [Restart pair](restart.json): both Runs passed in 35.955 seconds. The recipe
  consumer received a graceful Docker restart from 09:38:24 to 09:38:30 UTC
  while these Runs were active. This is not an abrupt-crash qualification.
- [Five sequential repetitions](sequential.json): all passed, 19–28 seconds.
- [Iteration canaries](canaries.log): 10 passed, 2 intentionally skipped
  local/mock contracts; source and deployed SHA match. Work, Studio,
  Hypervisor, LiveKit, branding isolation and observability navigation passed.
- [Image identities](images.txt), [backend](backend-build-info.json) and
  [frontend](frontend-build-info.json) all identify the candidate.
- [Real Run screenshot](run.png): execution completed; decision and confidence
  absent, rather than inferred approval or 100%. The two Python operations and
  LLM operation remain visible in the timeline.

The native Chrome control tool timed out twice. Visual verification used a
fresh authenticated Chromium session from carakai; its screenshot was reviewed.
The SSH switch client remained open after the remote command was no longer
present; it was closed locally after independent image, health and storage checks.

The consumer queues are `cpu` and `recipes`. Both workers use the same image;
recipe worker beat is disabled. Protected storage checks passed after creation.
Giskard 2.19.2 remains installed: pip check and the three-case mocked SDK
qualification passed during the worker build. A real provider campaign remains
NOT RUN. Runtime logs showed no backend traceback/exception in the inspected
post-switch window; root returned HTTP 200.

Build logs: `/srv/agentium-data/runtime-deployments/2026-09-16-7532d4491a23/`.
Canary artifacts: `/tmp/iteration-canaries-20260916T093933Z.uYmvmm` on carakai.
Raw synthetic qualification states remain in `/tmp/agentium-7532-*.json` there.
The [concurrency script](concurrency-check.py) records keys before dispatch.

## Limits

No human acceptance study or unprepared case was performed. Operational Analysis
still skips automatic semantic evaluation for its fixed inputs; its numerical
check is separate. Historical outcomes are not rewritten. Declared ROI hypotheses
retain their calculation; this release does not attest economic savings. R0
acceptance remains open beyond the qualified concurrency/completion corrections.

Rollback uses the previous immutable tag with compatible data. Drain recipe
executions before removing the dedicated consumer; queued tasks must not be lost.
