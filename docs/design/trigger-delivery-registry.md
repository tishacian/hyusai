# Trigger deliveries: accepted journal and durable registry

The UI/UX plan (lot 5, PL03, pp. 25–26) explicitly separates the first journal
from the later backend registry and replay endpoint. This change implements the
first journal. It does not claim to retain rejected, ignored, or duplicate
attempts. No replay control is shown until that contract exists.

## Implemented contract

`GET /api/v1/systems/{system_id}/trigger-deliveries?limit=50` returns at most 200
records. The System must belong to the selected workspace and the caller must
have `system.read`. Each Run is independently authorized before pagination.
An accepted webhook is a Run with a winning `TriggerEventClaim`; a scheduled
execution is a Run with `trigger=scheduler`.

Rows contain only the Run identifier, source, acceptance timestamp, explicit
`acceptance=accepted`, and the current execution status. Acceptance and execution
success are different facts. Neither a failed nor a pending Run is rendered as a
rejected delivery. The response's `coverage=accepted_only` makes the coverage
limit explicit. Global/workspace enablement, the System circuit breaker, and
runtime mode determine the next-event explanation; historical rows do not
imply that triggers are currently enabled.

The journal is available without entering edit mode at
`/systems/{id}/flow?tab=triggers`. Opening it issues GET requests only. Its rows
link to the actual Run. It also appears in the matching schedule/webhook inspector
when editing. It exposes no input payload, hook signing secret, credential,
raw deduplication key, or requester identity. Existing Run retention controls the
lifetime of these records; this release introduces no new payload copy.

## Durable registry: separate backend implementation

Create an append-only `trigger_deliveries` table with workspace, System, source
kind and optional source id, received timestamp, outcome (`accepted`,
`duplicate`, `ignored`, `rejected`), safe reason code, nullable Run id, parent
delivery id for replay, and a random public id. A duplicate references the
accepted delivery if available. Claim acquisition and the acceptance row must
commit in the same transaction. Failed authorization must not disclose whether a
foreign source or delivery exists.

Do not store raw inputs, headers, signing secrets, email addresses, or raw
idempotency keys in the ledger. The proposal is 30-day retention for delivery
metadata, configurable downward per workspace and bounded by account/workspace
deletion. If reproducing an input becomes necessary, store an encrypted,
separately authorized payload reference with a shorter retention policy; expiry
must make replay unavailable with a reason, never manufacture an empty input.
Retention and legal requirements need an explicit deployment policy before this
second backend change is enabled.

Replay is a new controlled attempt, not an edit to the original record and not a
synonym for replaying a Run. A proposed
`POST /systems/{id}/trigger-deliveries/{delivery_id}/replays` must require an
explicit operation permission, a client idempotency key, an expected published
version, and confirmation of the current mode and execution identity. Recheck
workspace access, source enablement, the circuit breaker, execution authority,
and current publication at request time. Return a receipt identifying the new
delivery and (when created) its Run. A transport timeout remains an unknown
outcome; a status lookup by the client key must reconcile it before resubmission.
The original delivery remains immutable.

Before shipping that extension, test concurrent duplicate arrivals, transaction
rollback, tenant isolation, Run ACL filtering before pagination, invalid/expired
payload references, permission revocation, paused sources, changed publication,
lost replay responses, retention/deletion, and the absence of personal data or
secrets in both API responses and audit records. Those tests do not apply to a
fabricated ledger in the current release: the current UI honestly reports only
persisted acceptance evidence.
