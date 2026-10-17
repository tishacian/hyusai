# Flow triggers: setup and operational checks

The Flow inspector manages cron schedules and signed inbound webhooks for the
selected System. Selecting a schedule shows its schedule setup; selecting a
webhook shows delivery controls and webhook setup. SFTP and connection watches
keep their own source controls.

New schedules and webhooks created from the inspector are **paused**. Configure
the published entry point first, check its input contract, then enable the
configured trigger. Schedule setup accepts a time zone and a JSON input object.
The next execution is displayed in that time zone, with a link to the last Run.

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
