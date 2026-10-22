# Human approval: rejection and expiry

An ordinary `hitl` gate no longer invokes its normal task continuation after a
rejection. Without an explicit refusal route, the Run ends as `cancelled` before
any downstream action is called. This applies to both a human refusal and a TTL
whose configured action is `reject`. Acceptance still follows the approved path.

## Compatibility change

Previously, rejection resumed every ordinary continuation with `approved=false`.
Each downstream task had to interpret that flag. A direct `hitl → task` now stops
on rejection, including when that task used to handle refusal internally. Author
an immediate Decision to separate approval and refusal explicitly instead.

The exceptions are:

- A terminal `sink` can retain the verdict without invoking another task. Such a
  Run may complete with `decision_status=rejected`; completion does not mean the
  proposal was approved.
- An immediate Decision can route refusal when its predicates are bound to this
  gate's verdict and the rejected branch has different targets from both the
  `accepted` and `applied` branches. All live successors of the gate must qualify;
  a parallel direct task is not an authorized bypass.

The routing check is deliberately conservative: it accepts predicates using this
gate's `approved`, `rejected` or `decision_status`, including correctly mapped
aliases. Foreign selectors, other predecessors, unrelated conditions, invalid
routes and overwritten verdict namespaces do not qualify. A rejection condition
must actually distinguish rejection from approval. Task-mediated routing and a
default branch alone are insufficient.

For example, this immediate Decision handles both verdicts:

```json
{
  "id": "route.review",
  "kind": "decision",
  "config": {
    "inputs_map": {
      "approved": {
        "node_id": "review",
        "path": ["approved"],
        "required": true
      }
    },
    "branches": [
      {"label": "approved", "condition": "approved == True"},
      {"label": "rejected", "condition": "approved == False"}
    ]
  }
}
```

Connect `review → route.review`, then use `kind=branch` edges labelled `approved`
and `rejected` to different targets, for example the application task and a
refusal receipt. Keep the action's own approval and authorization checks: routing
does not confer permission to perform a business effect.

By contrast, an approval predicate followed only by
`"default_branch": "rejected"`, or a fallback predicate `True`, is not an explicit
refusal condition and stops at the gate. Branch labels without matching routes
also do not qualify.

AgentLoop human gates, delegated child-run pauses, Membrane egress gates and
specialized dataset-label/model-retraining reviews retain their own settlement
rules. This change does not relax their approval requirements or business guards.

## Status and evidence

An ordinary gate stopped without a refusal route records:

| Field | Value |
| --- | --- |
| Run status | `cancelled` |
| Run error after a proved TTL rejection | `hitl_approval_expired` |
| Run error after other rejection | `hitl_approval_rejected` |
| Checkpoint | `hitl_stopped` |
| Checkpoint reason | `approval_expired` or `approval_rejected` |
| Checkpoint routing | `no_explicit_rejection_route` |

The checkpoint also retains the gate's `node_id`, `passage_id`, `decision_id`,
`decision_status=rejected` and `decided_by`. The Run's output retains the verdict;
the existing `hitl_resume` and terminal `run_end` checkpoints remain available.
Expiration attribution requires both `decided_by=system:gate_ttl` and a matching
`gate_ttl_expired` checkpoint for that Decision with `expiry_action=reject`.

## Existing Runs and UI interpretation

Deploying this correction does not rewrite old Runs, change past Decisions,
auto-approve a proposal or replay an action. An old Run that continued after TTL
rejection can therefore remain `failed` with its original business-guard error.

For historical display, correlate the rejected `hitl_resume` to its `hitl_pause`
using the node/passage, then to `gate_ttl_expired` using the exact Decision ID and
`expiry_action=reject`. That evidence supports “approval period expired.” Without
it, show “approval not granted”; neither elapsed wall-clock time nor an approval
guard error alone proves expiration. Do not attribute an old rejection to a
later successful execution or a different gate.

The new terminal Run cannot be resumed through the rejected Decision. Any new
attempt follows the ordinary application controls and creates its own approval
request; existing idempotency and authorization checks still apply.
