# Flow triggers: setup and operational checks

The Flow inspector manages cron schedules and signed inbound webhooks for the
selected System. Selecting a schedule shows its schedule setup; selecting a
webhook shows delivery controls and webhook setup. SFTP and connection watches
keep their own source controls.

New schedules and webhooks created from the inspector are **paused**. Configure
the published entry point first, check its input contract, then enable the
configured trigger. Schedule setup accepts a time zone and a JSON input object.
The next execution is displayed in that time zone, with a link to the last Run.

## Execution identity for protected operations

An unattended trigger does not imply a human initiator. For ML scoring, document
access or same-Run Judge evidence, explicitly choose **Use my access** in the
trigger setup. This control is unchecked at creation. API create/PATCH accepts
`execution_identity: "current_user"` to delegate the authenticated caller's own
current rights, or `"none"` to revoke the delegation; an omitted field preserves
the current configuration. Arbitrary user identifiers are not accepted.

The delegate must be active, still a member of this workspace and allowed to run
this System. A global administrator without membership is not selected implicitly.
The grant is limited to the current immutable published Flow version and execution
contract. After a new publication, choose **Use my access** again to review and
renew it. Legacy Systems without immutable publication cannot receive a grant.
The new consent invalidates the old grant; previously accepted Runs that still
use the old grant must not continue. A publication alone does not rewrite already
accepted Runs or expand their authority.

The source records the delegation; the Run records a separate
`execution_principal` and keeps `initiated_by_user_id: null`. The signed payload
cannot select an actor, workspace, Run or System. The Run API exposes the principal
and its publication references for review, without the internal grant identifier.
Rights, membership, the source and grant are checked again before each protected
invocation, at resume and before finalization; Judge also checks after its provider
call. Revoking the source grant, deleting the source, disabling the user or removing
membership stops later execution. Already incurred provider usage remains recorded.
Pausing a source stops new deliveries/ticks; it does not revoke an existing grant.

Only the delegate or an effective workspace administrator may mutate or delete a
source that carries a grant. Existing broad legacy source-editing rules cannot
borrow another person's authority. Resource-specific document/model ACLs still
apply. A delegated Run cannot start a subflow in this release: it fails with
`EXECUTION_PRINCIPAL_SUBFLOW_UNSUPPORTED` before creating a child, because authority
for another System has not been delegated.
The optional native Temporal execution profile does not yet support delegated
triggers: its authority check still requires a human initiator and refuses this
case before execution. Qualification here covers the published DAG runtime;
it is not a claim that every execution family supports delegation.

### Deployment and qualification

Migration `141_event_execution_principal`, after `140_mlops_prod_explanations`,
adds nullable JSON columns on hooks, schedules and Runs. It does not backfill any
identity or alter existing permissions. Deploy API, all execution workers and the
frontend from the same revision. In the existing Compose stack, use its usual
env-file and overlays, then run the candidate `agentium-migrate` service
(`alembic upgrade head`) before starting the candidate `agentium-backend`,
`agentium-worker-cpu` and `agentium-frontend`. Update the scheduler arrangement
already in use: embedded beat on the CPU worker, or the separate `agentium-beat`
service. When enabled, update
`agentium-worker-control`, `agentium-scheduler-control` and other workers consuming
the same application models to that revision as well. Do not run two beat schedulers.
No new environment flag or credential is needed for delegation.

Keep the new source paused through migration and version checks. Read back its
published ingress, opt into delegation, then qualify one signed delivery or one
bounded tick. Check the Run's machine trigger, null human initiator, explicit
principal, publication identity and subsequent ML/Judge evidence. Test a duplicate
delivery and a revoked grant separately; no second effect or permissive fallback
is acceptable. Local qualification uses isolated test databases and mocked model
providers; it does not constitute a production receipt.

For recovery, pause the affected sources, revoke their grants and retain the
recorded Runs. The migration downgrade refuses to discard any non-null grant or
Run principal. Leave the additive columns in place when reverting application
images; do not erase runtime evidence to make a downgrade pass.

## Published entry points

Both adapters require an active System with a valid published Flow when Flow
publication is enabled for the workspace. `GET /systems/{system_id}/ingresses`
returns the effective published entries and their input schemas.

| Adapter | Source node type | Published ingress kind |
| --- | --- | --- |
| Signed inbound webhook | `source.webhook` | `http` |
| Cron schedule | `source.schedule` | `schedule` |

A source must be a root, with `kind: "source"`. Its identifier is also its ingress
identifier. Define `config.input_schema` to match the data the adapter delivers;
connect the source to the steps it should start. Manual Work entry points can
coexist in the same System.

Current adapters infer the matching entry. Use one published webhook source and
one published schedule source per System. Multiple candidates of the same kind
are refused as ambiguous rather than selecting an arbitrary branch. Schedule and
hook records do not yet carry an explicit `ingress_id` selector.

## Signed webhook

1. `POST /systems/{system_id}/hooks` with `name`,
   `event_type: "webhook.received"` and `enabled: false`. The response includes
   the path and a secret returned only at creation. Install that secret at the
   sender; do not include it in the Flow or event payload.
2. Opt the workspace into event dispatch with
   `settings.features.enable_event_triggers: true` (or
   `settings.event_triggers.enabled: true`). A platform-wide flag is not required.
3. Inspect `GET /systems/{system_id}/event-trigger`. Use its PATCH endpoint to set
   `mode: "live"` for real Runs or `mode: "dry_run"` for a simulated journal.
   `disabled: false` explicitly re-arms a tripped circuit breaker.
4. Enable the hook through `PATCH /systems/{system_id}/hooks/{hook_id}`.
5. POST the JSON body to the returned `/api/v1/hooks/{hook_id}` path. Compute
   HMAC SHA-256 over the **exact request body bytes**, using the hook secret, and
   send `X-Agentium-Signature: sha256=<hex digest>`.

The receiver adds `_webhook: {hook_id, system_id, event_type}` to the JSON object
before the published ingress validates it. A strict input schema must therefore
accept that server-owned object, as well as the business fields. The original
business fields remain at the root; they are not wrapped under `payload`.

Read the response body even when HTTP is 200. Top-level delivery status is
`accepted`, `rejected`, `ignored` or `partial`; each result gives the target outcome
and its Run or inbox identifier when applicable. `accepted` means durable custody
of the delivery, **not** successful completion of the business workflow.

Deduplication uses System, event kind and a hash of the complete canonical JSON
payload, including hook metadata. Resending the same object through the same hook
returns the existing accepted Run/inbox instead of executing it again. An
`event_id` field alone is not an idempotency key: changing any payload content
changes the delivery key. Keep retries byte-equivalent in content; JSON key order
does not matter to the canonical hash.

The default limit is 10 real triggered Runs per System per rolling hour. Three
consecutive failed triggered Runs trip the circuit breaker. Business side effects
remain subject to the Flow's existing governance and human review gates.

### New work versus evidence for a waiting Run

An inbound event without a correlation key starts its own Run through the normal
published ingress and execution guards. It does not belong to whichever human
review happens to be waiting in that System.

To add evidence to an existing Run, include a non-empty `correlation_key`,
`correlation_id` or `transaction_id` accepted by the published input schema.
The value must match exactly one eligible Run in the same System and workspace:
a Run waiting for human review, or a running AgentLoop. Receiving evidence adds
an inbox entry; it never approves or resumes a human gate. A different or unknown
key follows the new-Run path. Multiple eligible matches are rejected with
`inbox_correlation_ambiguous`; the sender must not retry with a changed key merely
to bypass that refusal.

The input contract and delegated publication authority are checked before an
inbox write, as they are before creating a Run. An out-of-contract correlation
field is not a way to target a waiting Run. When publication is enabled, the
target Run must carry the same frozen version, Flow hash, execution contract
and ingress as the accepted delivery. A new publication cannot feed an older
Run through its new contract: `inbox_target_publication_mismatch` or
`inbox_target_ingress_mismatch` rejects that delivery without consuming its
deduplication key. Review the waiting Run rather than changing the correlation
key to force another route. Inbox delivery remains deduplicated and
transactional. Existing dry-run/live, governance and dispatch rules remain in place.

This replaces the earlier **open buffer** behavior, which routed missing or
unmatched keys to the most recent waiting Run. Integrations relying on that
fallback must publish an explicit correlation field and send the same business
key on the initial request and its later evidence. Uncorrelated Runs no longer
receive the historical shared `_default` memory. That internal key is reserved
and refused for inbound correlation; historical inbox and memory records remain
available for audit.

## Cron schedule

`POST /systems/{system_id}/schedules` accepts `name`, `cron_expr`, `timezone`,
`input_payload` (a JSON object) and `enabled`. The UI creates it with
`enabled: false`; PATCH the schedule to enable it after checking its published
entry and inputs. The API validates cron and time zone when saving. Input schema
validation happens at dispatch.

The existing Celery beat task `agentium.scheduler_tick` evaluates due schedules.
It requires the scheduler and execution worker to be running. The schedule's
`last_run_id`, `last_fired_at` and `next_fire_at` distinguish the last created Run
from a future due time. The configured time zone is applied across DST changes.

**Cron launches real Runs independently of the event trigger dry-run switch and
circuit breaker.** Disable the schedule itself to stop recurring execution. For a
bounded qualification, observe one due tick and disable the schedule afterward.

## Recovery and evidence

- A duplicate accepted delivery keeps its original Run, even when that Run later
  failed. Diagnose that Run before deciding to start a new business attempt; a
  changed payload is a new delivery, not a harmless transport retry.
- Publication, schema, governance, rate-limit and circuit-breaker refusals are
  visible in delivery results. Check the returned reason and correct the cause
  before resending. Do not infer successful processing from an HTTP status alone.
- A refused cron tick advances to the next scheduled occurrence. Inspect worker
  logs for the refusal and the published entry contract; do not assume that a
  future `next_fire_at` proves the previous tick succeeded.
- Existing Run traces, Activities and durable trigger claims provide execution
  and dedup evidence. There is no dedicated user-facing delivery ledger/replay
  screen in this release. Repeated delivery attempts that resolve to the same
  claim must not be counted as distinct business outcomes.

The inspector changes are generic. Applying these adapters to a showcase does
not require another business System or a demonstration-specific event endpoint.
