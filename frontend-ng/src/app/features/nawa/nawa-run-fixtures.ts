/**
 * Real run traces, captured on the local DAG bench — DO NOT EDIT BY HAND.
 *
 * Regenerate with:
 *   python frontend-ng/scripts/capture_nawa_run_fixtures.py
 *
 * Consumed by `nawa-run-projection.spec.ts`, which asserts the state of the
 * six business steps against what the outcome banner claims. These are the
 * walker's own checkpoints, in its own emission order, so the guard cannot
 * drift towards a trace we imagined.
 */
export const NAWA_RUN_FIXTURES = {
  "ad_unreachable": {
    "checkpoints": [
      {
        "breakpoints": [],
        "debug_mode": null,
        "kind": "run_start",
        "nodes": 28,
        "t": "2026-07-28T11:47:13.468832"
      },
      {
        "kind": "node_start",
        "label": "Service desk request (call · email · walk-in)",
        "node_id": "source.request",
        "node_kind": "source",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.475249"
      },
      {
        "kind": "node_end",
        "node_id": "source.request",
        "node_kind": "source",
        "t": "2026-07-28T11:47:13.476680"
      },
      {
        "kind": "node_start",
        "label": "Simulation bench · which inbound case",
        "node_id": "decision.case_selector",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.477832"
      },
      {
        "chosen_branch": "ad_unreachable",
        "kind": "node_end",
        "node_id": "decision.case_selector",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.479085"
      },
      {
        "kind": "node_start",
        "label": "Case A · Forgotten password, complete evidence",
        "node_id": "task.case_nominal",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.480174"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_nominal",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.481791"
      },
      {
        "kind": "node_start",
        "label": "Case B · 'Reset my password' after three failed sign-ins",
        "node_id": "task.case_ambiguous",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.482778"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_ambiguous",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.484509"
      },
      {
        "kind": "node_start",
        "label": "Case C · Legitimate request, weak identity evidence",
        "node_id": "task.case_weak_identity",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.485510"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_weak_identity",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.488304"
      },
      {
        "kind": "node_start",
        "label": "Case D · Clean request, automation bridge down",
        "node_id": "task.case_ad_unreachable",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.491240"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_ad_unreachable",
        "node_kind": "task",
        "t": "2026-07-28T11:47:13.492560"
      },
      {
        "kind": "node_start",
        "label": "Case E · Confident assessment, empty evidence record",
        "node_id": "task.case_quality_guard",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.493496"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_quality_guard",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.494506"
      },
      {
        "kind": "node_start",
        "label": "Step 3a · Dispatch the reset to the automation bridge",
        "node_id": "task.directory_bridge",
        "node_kind": "task",
        "skill_slug": "rpa_dispatch_v1",
        "t": "2026-07-28T11:47:13.495535"
      },
      {
        "cost": 0.0,
        "error": "RPA Bridge connector is not enabled for this workspace",
        "kind": "node_end",
        "latency_ms": 1.10391597263515,
        "node_id": "task.directory_bridge",
        "node_kind": "task",
        "skill_slug": "rpa_dispatch_v1",
        "status": "failed",
        "t": "2026-07-28T11:47:13.501210"
      },
      {
        "kind": "node_start",
        "label": "Step 1 · Classify the request (model call)",
        "node_id": "task.classify_intent",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:13.503193"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.19820797024294734,
        "node_id": "task.classify_intent",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.507530"
      },
      {
        "kind": "node_start",
        "label": "Step 1 · Intent routing",
        "node_id": "decision.intent_route",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.509093"
      },
      {
        "chosen_branch": "password_reset",
        "kind": "node_end",
        "node_id": "decision.intent_route",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.510310"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Routed to another ITSD use case",
        "node_id": "sink.routed_elsewhere",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.511678"
      },
      {
        "kind": "node_end",
        "node_id": "sink.routed_elsewhere",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.514751"
      },
      {
        "kind": "node_start",
        "label": "Step 2 · Assess the identity evidence (model call)",
        "node_id": "task.verify_identity",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:13.517056"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.19045802764594555,
        "node_id": "task.verify_identity",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.521330"
      },
      {
        "kind": "node_start",
        "label": "Step 2 · Identity verdict",
        "node_id": "decision.identity_gate",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.522983"
      },
      {
        "chosen_branch": "verified",
        "kind": "node_end",
        "node_id": "decision.identity_gate",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.524173"
      },
      {
        "kind": "node_start",
        "label": "Step 2c · Grounding check on the identity assessment",
        "node_id": "task.quality_gate",
        "node_kind": "task",
        "skill_slug": "response_eval_v1",
        "t": "2026-07-28T11:47:13.525412"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.19562500528991222,
        "node_id": "task.quality_gate",
        "node_kind": "task",
        "skill_slug": "response_eval_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.529131"
      },
      {
        "kind": "node_start",
        "label": "Step 2b · Human approval before a privileged reset",
        "node_id": "hitl.identity_gate",
        "node_kind": "hitl",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.533085"
      },
      {
        "kind": "node_end",
        "node_id": "hitl.identity_gate",
        "node_kind": "hitl",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.534926"
      },
      {
        "kind": "node_start",
        "label": "Step 2b · Authorisation to execute",
        "node_id": "decision.execute_reset",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.536547"
      },
      {
        "chosen_branch": "incident",
        "kind": "node_end",
        "node_id": "decision.execute_reset",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.538004"
      },
      {
        "kind": "node_start",
        "label": "Step 3 · Reset the account in the directory (simulated)",
        "node_id": "task.ad_reset",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.539125"
      },
      {
        "kind": "node_end",
        "node_id": "task.ad_reset",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.540260"
      },
      {
        "kind": "node_start",
        "label": "Step 4 · Issue a temporary password, force a change at next sign-in (simulated)",
        "node_id": "task.temporary_credential",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.541366"
      },
      {
        "kind": "node_end",
        "node_id": "task.temporary_credential",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.542565"
      },
      {
        "kind": "node_start",
        "label": "Step 5 · Draft the message to the requester (model call, EN/AR)",
        "node_id": "task.draft_user_notice",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:13.543667"
      },
      {
        "kind": "node_end",
        "node_id": "task.draft_user_notice",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.544737"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Confirm the resolution and close the ticket (simulated)",
        "node_id": "task.close_ticket",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.545852"
      },
      {
        "kind": "node_end",
        "node_id": "task.close_ticket",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.546836"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Write the audit ledger entry",
        "node_id": "task.audit_ledger",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:13.547848"
      },
      {
        "kind": "node_end",
        "node_id": "task.audit_ledger",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.549113"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Record the withheld reset in the audit ledger",
        "node_id": "task.audit_withheld_incident",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:13.550635"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.3327919985167682,
        "node_id": "task.audit_withheld_incident",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.555314"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Record the held reset in the audit ledger",
        "node_id": "task.audit_withheld_quality",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:13.556940"
      },
      {
        "kind": "node_end",
        "node_id": "task.audit_withheld_quality",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.558182"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Incident, automation bridge unreachable",
        "node_id": "sink.incident",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.560443"
      },
      {
        "kind": "node_end",
        "node_id": "sink.incident",
        "node_kind": "sink",
        "t": "2026-07-28T11:47:13.562017"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Held for review, assessment not grounded",
        "node_id": "sink.quality_hold",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.563637"
      },
      {
        "kind": "node_end",
        "node_id": "sink.quality_hold",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.568324"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Closure routing",
        "node_id": "decision.closure_route",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.571228"
      },
      {
        "kind": "node_end",
        "node_id": "decision.closure_route",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.577554"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Human approval refused",
        "node_id": "sink.approval_refused",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.589190"
      },
      {
        "kind": "node_end",
        "node_id": "sink.approval_refused",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.592218"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Ticket closed",
        "node_id": "sink.ticket_closed",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.598341"
      },
      {
        "kind": "node_end",
        "node_id": "sink.ticket_closed",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.605599"
      },
      {
        "kind": "run_end",
        "nodes_executed": 28,
        "status": "completed",
        "t": "2026-07-28T11:47:13.625216"
      }
    ],
    "output_ref": {
      "chosen_branch": "incident",
      "detected_intent": "password_reset",
      "diagnostic_detail": "RPA Bridge connector is not enabled for this workspace",
      "diagnostic_job": "nawa_directory_password_reset",
      "diagnostic_status": "failed",
      "evaluations": [
        {
          "label": "incident",
          "value": true
        },
        {
          "label": "quality_hold",
          "value": false
        },
        {
          "label": "execute",
          "value": true
        },
        {
          "label": "refused",
          "value": false
        }
      ],
      "identity_verdict": "IDENTITY_VERIFIED Staff ID matched the HR record and the line manager confirmed the request.",
      "outcome": {
        "code": "incident_directory_unreachable",
        "label": "Incident - the directory could not be reached, no reset performed",
        "message": "The reset was authorised but could not be applied: the Nawa corporate directory did not accept the request. The account was not modified, no temporary password was issued and the requester was not notified. The ticket stays open and the request can be applied through the manual directory procedure.",
        "remediation": "Relaunch the same request through the manual directory procedure: the reset then completes without going through the automated route.",
        "replay_input": {
          "bridge_fallback": true,
          "scenario": "ad_unreachable"
        },
        "reset_performed": false
      }
    },
    "status": "completed"
  },
  "ad_unreachable_fallback": {
    "checkpoints": [
      {
        "breakpoints": [],
        "debug_mode": null,
        "kind": "run_start",
        "nodes": 28,
        "t": "2026-07-28T11:47:13.652885"
      },
      {
        "kind": "node_start",
        "label": "Service desk request (call · email · walk-in)",
        "node_id": "source.request",
        "node_kind": "source",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.658643"
      },
      {
        "kind": "node_end",
        "node_id": "source.request",
        "node_kind": "source",
        "t": "2026-07-28T11:47:13.661502"
      },
      {
        "kind": "node_start",
        "label": "Simulation bench · which inbound case",
        "node_id": "decision.case_selector",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.663480"
      },
      {
        "chosen_branch": "ad_unreachable_bypass",
        "kind": "node_end",
        "node_id": "decision.case_selector",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.666218"
      },
      {
        "kind": "node_start",
        "label": "Case A · Forgotten password, complete evidence",
        "node_id": "task.case_nominal",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.668506"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_nominal",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.669870"
      },
      {
        "kind": "node_start",
        "label": "Case B · 'Reset my password' after three failed sign-ins",
        "node_id": "task.case_ambiguous",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.671353"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_ambiguous",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.672836"
      },
      {
        "kind": "node_start",
        "label": "Case C · Legitimate request, weak identity evidence",
        "node_id": "task.case_weak_identity",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.674617"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_weak_identity",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.677059"
      },
      {
        "kind": "node_start",
        "label": "Case D · Clean request, automation bridge down",
        "node_id": "task.case_ad_unreachable",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.678329"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_ad_unreachable",
        "node_kind": "task",
        "t": "2026-07-28T11:47:13.679634"
      },
      {
        "kind": "node_start",
        "label": "Case E · Confident assessment, empty evidence record",
        "node_id": "task.case_quality_guard",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.681471"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_quality_guard",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.684378"
      },
      {
        "kind": "node_start",
        "label": "Step 3a · Dispatch the reset to the automation bridge",
        "node_id": "task.directory_bridge",
        "node_kind": "task",
        "skill_slug": "rpa_dispatch_v1",
        "t": "2026-07-28T11:47:13.685837"
      },
      {
        "kind": "node_end",
        "node_id": "task.directory_bridge",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.687608"
      },
      {
        "kind": "node_start",
        "label": "Step 1 · Classify the request (model call)",
        "node_id": "task.classify_intent",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:13.688818"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.25341601576656103,
        "node_id": "task.classify_intent",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.692878"
      },
      {
        "kind": "node_start",
        "label": "Step 1 · Intent routing",
        "node_id": "decision.intent_route",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.694433"
      },
      {
        "chosen_branch": "password_reset",
        "kind": "node_end",
        "node_id": "decision.intent_route",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.695632"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Routed to another ITSD use case",
        "node_id": "sink.routed_elsewhere",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.696791"
      },
      {
        "kind": "node_end",
        "node_id": "sink.routed_elsewhere",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.697810"
      },
      {
        "kind": "node_start",
        "label": "Step 2 · Assess the identity evidence (model call)",
        "node_id": "task.verify_identity",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:13.698980"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.20066602155566216,
        "node_id": "task.verify_identity",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.703090"
      },
      {
        "kind": "node_start",
        "label": "Step 2 · Identity verdict",
        "node_id": "decision.identity_gate",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.706809"
      },
      {
        "chosen_branch": "verified",
        "kind": "node_end",
        "node_id": "decision.identity_gate",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.708296"
      },
      {
        "kind": "node_start",
        "label": "Step 2c · Grounding check on the identity assessment",
        "node_id": "task.quality_gate",
        "node_kind": "task",
        "skill_slug": "response_eval_v1",
        "t": "2026-07-28T11:47:13.709508"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.20575005328282714,
        "node_id": "task.quality_gate",
        "node_kind": "task",
        "skill_slug": "response_eval_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.713243"
      },
      {
        "kind": "node_start",
        "label": "Step 2b · Human approval before a privileged reset",
        "node_id": "hitl.identity_gate",
        "node_kind": "hitl",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.714694"
      },
      {
        "kind": "node_end",
        "node_id": "hitl.identity_gate",
        "node_kind": "hitl",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.716018"
      },
      {
        "kind": "node_start",
        "label": "Step 2b · Authorisation to execute",
        "node_id": "decision.execute_reset",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.717600"
      },
      {
        "chosen_branch": "execute",
        "kind": "node_end",
        "node_id": "decision.execute_reset",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.718953"
      },
      {
        "kind": "node_start",
        "label": "Step 3 · Reset the account in the directory (simulated)",
        "node_id": "task.ad_reset",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.720086"
      },
      {
        "kind": "node_end",
        "node_id": "task.ad_reset",
        "node_kind": "task",
        "t": "2026-07-28T11:47:13.721277"
      },
      {
        "kind": "node_start",
        "label": "Step 4 · Issue a temporary password, force a change at next sign-in (simulated)",
        "node_id": "task.temporary_credential",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.722233"
      },
      {
        "kind": "node_end",
        "node_id": "task.temporary_credential",
        "node_kind": "task",
        "t": "2026-07-28T11:47:13.723529"
      },
      {
        "kind": "node_start",
        "label": "Step 5 · Draft the message to the requester (model call, EN/AR)",
        "node_id": "task.draft_user_notice",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:13.724609"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.17429201398044825,
        "node_id": "task.draft_user_notice",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.728499"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Confirm the resolution and close the ticket (simulated)",
        "node_id": "task.close_ticket",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.729940"
      },
      {
        "kind": "node_end",
        "node_id": "task.close_ticket",
        "node_kind": "task",
        "t": "2026-07-28T11:47:13.731127"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Write the audit ledger entry",
        "node_id": "task.audit_ledger",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:13.733519"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.16970798606052995,
        "node_id": "task.audit_ledger",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.737537"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Record the withheld reset in the audit ledger",
        "node_id": "task.audit_withheld_incident",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:13.739248"
      },
      {
        "kind": "node_end",
        "node_id": "task.audit_withheld_incident",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.740582"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Record the held reset in the audit ledger",
        "node_id": "task.audit_withheld_quality",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:13.741894"
      },
      {
        "kind": "node_end",
        "node_id": "task.audit_withheld_quality",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.743071"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Incident, automation bridge unreachable",
        "node_id": "sink.incident",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.744643"
      },
      {
        "kind": "node_end",
        "node_id": "sink.incident",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.746592"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Held for review, assessment not grounded",
        "node_id": "sink.quality_hold",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.747849"
      },
      {
        "kind": "node_end",
        "node_id": "sink.quality_hold",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.750052"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Closure routing",
        "node_id": "decision.closure_route",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.751727"
      },
      {
        "chosen_branch": "closed",
        "kind": "node_end",
        "node_id": "decision.closure_route",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.753128"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Human approval refused",
        "node_id": "sink.approval_refused",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.754292"
      },
      {
        "kind": "node_end",
        "node_id": "sink.approval_refused",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.755376"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Ticket closed",
        "node_id": "sink.ticket_closed",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.756409"
      },
      {
        "kind": "node_end",
        "node_id": "sink.ticket_closed",
        "node_kind": "sink",
        "t": "2026-07-28T11:47:13.758735"
      },
      {
        "kind": "run_end",
        "nodes_executed": 28,
        "status": "completed",
        "t": "2026-07-28T11:47:13.761924"
      }
    ],
    "output_ref": {
      "audit_event_id": "audit-event-test",
      "chosen_branch": "closed",
      "detected_intent": "password_reset",
      "diagnostic_quality_score": 82.5,
      "directory_action": {
        "mode": "dry_run",
        "note": "No directory is contacted. This step records the privileged gesture it would perform.",
        "operation": "reset_user_password",
        "performed_by": "NAWA WE service account (simulated)",
        "result": "success",
        "target_directory": "Nawa corporate directory (simulated)"
      },
      "evaluations": [
        {
          "label": "closed",
          "value": true
        },
        {
          "label": "refused",
          "value": false
        }
      ],
      "evidence_on_file": 3,
      "human_approval": {},
      "identity_verdict": "IDENTITY_VERIFIED Staff ID matched the HR record and the line manager confirmed the request.",
      "outcome": {
        "code": "ticket_closed",
        "label": "Ticket closed",
        "message": "The account password was reset and a temporary password was issued to the requester, who must change it at the next sign-in. The ticket is closed and the action is recorded in the audit ledger.",
        "reset_performed": true
      },
      "temporary_password_issued": "Nawa-Temp-7431",
      "ticket": {
        "id": "ITSD-2026-0729-0148",
        "queue": "End User Support",
        "resolution": "Password reset completed, temporary password issued, requester guided to set a new password at first sign-in.",
        "state": "closed"
      },
      "user_message": "Your password has been reset. Temporary password: Nawa-Temp-7431. You will be asked to change it at your first sign-in. The service desk never asks for your password: do not share it with anyone."
    },
    "status": "completed"
  },
  "ambiguous": {
    "checkpoints": [
      {
        "breakpoints": [],
        "debug_mode": null,
        "kind": "run_start",
        "nodes": 28,
        "t": "2026-07-28T11:47:12.989867"
      },
      {
        "kind": "node_start",
        "label": "Service desk request (call · email · walk-in)",
        "node_id": "source.request",
        "node_kind": "source",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.995733"
      },
      {
        "kind": "node_end",
        "node_id": "source.request",
        "node_kind": "source",
        "t": "2026-07-28T11:47:13.019538"
      },
      {
        "kind": "node_start",
        "label": "Simulation bench · which inbound case",
        "node_id": "decision.case_selector",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.020887"
      },
      {
        "chosen_branch": "ambiguous",
        "kind": "node_end",
        "node_id": "decision.case_selector",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.022189"
      },
      {
        "kind": "node_start",
        "label": "Case A · Forgotten password, complete evidence",
        "node_id": "task.case_nominal",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.023392"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_nominal",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.024363"
      },
      {
        "kind": "node_start",
        "label": "Case B · 'Reset my password' after three failed sign-ins",
        "node_id": "task.case_ambiguous",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.025337"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_ambiguous",
        "node_kind": "task",
        "t": "2026-07-28T11:47:13.026577"
      },
      {
        "kind": "node_start",
        "label": "Case C · Legitimate request, weak identity evidence",
        "node_id": "task.case_weak_identity",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.027693"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_weak_identity",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.028840"
      },
      {
        "kind": "node_start",
        "label": "Case D · Clean request, automation bridge down",
        "node_id": "task.case_ad_unreachable",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.029856"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_ad_unreachable",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.030852"
      },
      {
        "kind": "node_start",
        "label": "Case E · Confident assessment, empty evidence record",
        "node_id": "task.case_quality_guard",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.042500"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_quality_guard",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.043862"
      },
      {
        "kind": "node_start",
        "label": "Step 3a · Dispatch the reset to the automation bridge",
        "node_id": "task.directory_bridge",
        "node_kind": "task",
        "skill_slug": "rpa_dispatch_v1",
        "t": "2026-07-28T11:47:13.044993"
      },
      {
        "kind": "node_end",
        "node_id": "task.directory_bridge",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.046238"
      },
      {
        "kind": "node_start",
        "label": "Step 1 · Classify the request (model call)",
        "node_id": "task.classify_intent",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:13.047566"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.25695801014080644,
        "node_id": "task.classify_intent",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.053557"
      },
      {
        "kind": "node_start",
        "label": "Step 1 · Intent routing",
        "node_id": "decision.intent_route",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.055152"
      },
      {
        "chosen_branch": "other_use_case",
        "kind": "node_end",
        "node_id": "decision.intent_route",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.056510"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Routed to another ITSD use case",
        "node_id": "sink.routed_elsewhere",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.057735"
      },
      {
        "kind": "node_end",
        "node_id": "sink.routed_elsewhere",
        "node_kind": "sink",
        "t": "2026-07-28T11:47:13.059044"
      },
      {
        "kind": "node_start",
        "label": "Step 2 · Assess the identity evidence (model call)",
        "node_id": "task.verify_identity",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:13.060243"
      },
      {
        "kind": "node_end",
        "node_id": "task.verify_identity",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.061382"
      },
      {
        "kind": "node_start",
        "label": "Step 2 · Identity verdict",
        "node_id": "decision.identity_gate",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.062661"
      },
      {
        "kind": "node_end",
        "node_id": "decision.identity_gate",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.090079"
      },
      {
        "kind": "node_start",
        "label": "Step 2c · Grounding check on the identity assessment",
        "node_id": "task.quality_gate",
        "node_kind": "task",
        "skill_slug": "response_eval_v1",
        "t": "2026-07-28T11:47:13.091887"
      },
      {
        "kind": "node_end",
        "node_id": "task.quality_gate",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.093301"
      },
      {
        "kind": "node_start",
        "label": "Step 2b · Human approval before a privileged reset",
        "node_id": "hitl.identity_gate",
        "node_kind": "hitl",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.094569"
      },
      {
        "kind": "node_end",
        "node_id": "hitl.identity_gate",
        "node_kind": "hitl",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.096075"
      },
      {
        "kind": "node_start",
        "label": "Step 2b · Authorisation to execute",
        "node_id": "decision.execute_reset",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.158697"
      },
      {
        "kind": "node_end",
        "node_id": "decision.execute_reset",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.175500"
      },
      {
        "kind": "node_start",
        "label": "Step 3 · Reset the account in the directory (simulated)",
        "node_id": "task.ad_reset",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.346105"
      },
      {
        "kind": "node_end",
        "node_id": "task.ad_reset",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.361692"
      },
      {
        "kind": "node_start",
        "label": "Step 4 · Issue a temporary password, force a change at next sign-in (simulated)",
        "node_id": "task.temporary_credential",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.374183"
      },
      {
        "kind": "node_end",
        "node_id": "task.temporary_credential",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.380157"
      },
      {
        "kind": "node_start",
        "label": "Step 5 · Draft the message to the requester (model call, EN/AR)",
        "node_id": "task.draft_user_notice",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:13.386707"
      },
      {
        "kind": "node_end",
        "node_id": "task.draft_user_notice",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.390675"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Confirm the resolution and close the ticket (simulated)",
        "node_id": "task.close_ticket",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.394561"
      },
      {
        "kind": "node_end",
        "node_id": "task.close_ticket",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.397001"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Write the audit ledger entry",
        "node_id": "task.audit_ledger",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:13.400376"
      },
      {
        "kind": "node_end",
        "node_id": "task.audit_ledger",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.402434"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Record the withheld reset in the audit ledger",
        "node_id": "task.audit_withheld_incident",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:13.403949"
      },
      {
        "kind": "node_end",
        "node_id": "task.audit_withheld_incident",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.406099"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Record the held reset in the audit ledger",
        "node_id": "task.audit_withheld_quality",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:13.407552"
      },
      {
        "kind": "node_end",
        "node_id": "task.audit_withheld_quality",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.409699"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Incident, automation bridge unreachable",
        "node_id": "sink.incident",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.411535"
      },
      {
        "kind": "node_end",
        "node_id": "sink.incident",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.412978"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Held for review, assessment not grounded",
        "node_id": "sink.quality_hold",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.415325"
      },
      {
        "kind": "node_end",
        "node_id": "sink.quality_hold",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.418996"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Closure routing",
        "node_id": "decision.closure_route",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.421941"
      },
      {
        "kind": "node_end",
        "node_id": "decision.closure_route",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.423537"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Human approval refused",
        "node_id": "sink.approval_refused",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.426219"
      },
      {
        "kind": "node_end",
        "node_id": "sink.approval_refused",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.427759"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Ticket closed",
        "node_id": "sink.ticket_closed",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.444510"
      },
      {
        "kind": "node_end",
        "node_id": "sink.ticket_closed",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.447433"
      },
      {
        "kind": "run_end",
        "nodes_executed": 28,
        "status": "completed",
        "t": "2026-07-28T11:47:13.454745"
      }
    ],
    "output_ref": {
      "chosen_branch": "other_use_case",
      "detected_intent": "unlock_ad_account",
      "evaluations": [
        {
          "label": "password_reset",
          "value": false
        },
        {
          "label": "other_use_case",
          "value": true
        }
      ],
      "outcome": {
        "code": "routed_to_other_use_case",
        "label": "Routed to another ITSD use case - no reset performed",
        "message": "This request is not a password reset: the account is locked out after repeated failed sign-in attempts. It has been routed to the account unlock procedure and no password was changed.",
        "reset_performed": false,
        "target_use_case": "Account unlock (UC-02)"
      },
      "request_text": "mon compte est bloque depuis ce matin, j'ai tape trois fois et maintenant ca ne veut plus rien savoir, il faut me remettre le mot de passe"
    },
    "status": "completed"
  },
  "nominal": {
    "checkpoints": [
      {
        "breakpoints": [],
        "debug_mode": null,
        "kind": "run_start",
        "nodes": 28,
        "t": "2026-07-28T11:47:12.829709"
      },
      {
        "kind": "node_start",
        "label": "Service desk request (call · email · walk-in)",
        "node_id": "source.request",
        "node_kind": "source",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.833737"
      },
      {
        "kind": "node_end",
        "node_id": "source.request",
        "node_kind": "source",
        "t": "2026-07-28T11:47:12.836225"
      },
      {
        "kind": "node_start",
        "label": "Simulation bench · which inbound case",
        "node_id": "decision.case_selector",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.837948"
      },
      {
        "chosen_branch": "nominal",
        "kind": "node_end",
        "node_id": "decision.case_selector",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:12.840355"
      },
      {
        "kind": "node_start",
        "label": "Case A · Forgotten password, complete evidence",
        "node_id": "task.case_nominal",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.841673"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_nominal",
        "node_kind": "task",
        "t": "2026-07-28T11:47:12.842923"
      },
      {
        "kind": "node_start",
        "label": "Case B · 'Reset my password' after three failed sign-ins",
        "node_id": "task.case_ambiguous",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.844258"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_ambiguous",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:12.845599"
      },
      {
        "kind": "node_start",
        "label": "Case C · Legitimate request, weak identity evidence",
        "node_id": "task.case_weak_identity",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.846664"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_weak_identity",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:12.847694"
      },
      {
        "kind": "node_start",
        "label": "Case D · Clean request, automation bridge down",
        "node_id": "task.case_ad_unreachable",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.848649"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_ad_unreachable",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:12.849674"
      },
      {
        "kind": "node_start",
        "label": "Case E · Confident assessment, empty evidence record",
        "node_id": "task.case_quality_guard",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.850669"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_quality_guard",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:12.851693"
      },
      {
        "kind": "node_start",
        "label": "Step 3a · Dispatch the reset to the automation bridge",
        "node_id": "task.directory_bridge",
        "node_kind": "task",
        "skill_slug": "rpa_dispatch_v1",
        "t": "2026-07-28T11:47:12.852635"
      },
      {
        "kind": "node_end",
        "node_id": "task.directory_bridge",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:12.853554"
      },
      {
        "kind": "node_start",
        "label": "Step 1 · Classify the request (model call)",
        "node_id": "task.classify_intent",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:12.854545"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.814041995909065,
        "node_id": "task.classify_intent",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:12.861368"
      },
      {
        "kind": "node_start",
        "label": "Step 1 · Intent routing",
        "node_id": "decision.intent_route",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.863011"
      },
      {
        "chosen_branch": "password_reset",
        "kind": "node_end",
        "node_id": "decision.intent_route",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:12.864313"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Routed to another ITSD use case",
        "node_id": "sink.routed_elsewhere",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.865952"
      },
      {
        "kind": "node_end",
        "node_id": "sink.routed_elsewhere",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:12.884105"
      },
      {
        "kind": "node_start",
        "label": "Step 2 · Assess the identity evidence (model call)",
        "node_id": "task.verify_identity",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:12.885347"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.1694579841569066,
        "node_id": "task.verify_identity",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:12.891677"
      },
      {
        "kind": "node_start",
        "label": "Step 2 · Identity verdict",
        "node_id": "decision.identity_gate",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.895202"
      },
      {
        "chosen_branch": "verified",
        "kind": "node_end",
        "node_id": "decision.identity_gate",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:12.896668"
      },
      {
        "kind": "node_start",
        "label": "Step 2c · Grounding check on the identity assessment",
        "node_id": "task.quality_gate",
        "node_kind": "task",
        "skill_slug": "response_eval_v1",
        "t": "2026-07-28T11:47:12.897902"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.16995903570204973,
        "node_id": "task.quality_gate",
        "node_kind": "task",
        "skill_slug": "response_eval_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:12.903061"
      },
      {
        "kind": "node_start",
        "label": "Step 2b · Human approval before a privileged reset",
        "node_id": "hitl.identity_gate",
        "node_kind": "hitl",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.905503"
      },
      {
        "kind": "node_end",
        "node_id": "hitl.identity_gate",
        "node_kind": "hitl",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:12.907646"
      },
      {
        "kind": "node_start",
        "label": "Step 2b · Authorisation to execute",
        "node_id": "decision.execute_reset",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.908674"
      },
      {
        "chosen_branch": "execute",
        "kind": "node_end",
        "node_id": "decision.execute_reset",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:12.910099"
      },
      {
        "kind": "node_start",
        "label": "Step 3 · Reset the account in the directory (simulated)",
        "node_id": "task.ad_reset",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.911248"
      },
      {
        "kind": "node_end",
        "node_id": "task.ad_reset",
        "node_kind": "task",
        "t": "2026-07-28T11:47:12.912592"
      },
      {
        "kind": "node_start",
        "label": "Step 4 · Issue a temporary password, force a change at next sign-in (simulated)",
        "node_id": "task.temporary_credential",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.913583"
      },
      {
        "kind": "node_end",
        "node_id": "task.temporary_credential",
        "node_kind": "task",
        "t": "2026-07-28T11:47:12.914639"
      },
      {
        "kind": "node_start",
        "label": "Step 5 · Draft the message to the requester (model call, EN/AR)",
        "node_id": "task.draft_user_notice",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:12.916007"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.16008404782041907,
        "node_id": "task.draft_user_notice",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:12.919357"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Confirm the resolution and close the ticket (simulated)",
        "node_id": "task.close_ticket",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.920591"
      },
      {
        "kind": "node_end",
        "node_id": "task.close_ticket",
        "node_kind": "task",
        "t": "2026-07-28T11:47:12.921623"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Write the audit ledger entry",
        "node_id": "task.audit_ledger",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:12.922535"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.1496669719927013,
        "node_id": "task.audit_ledger",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:12.925835"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Record the withheld reset in the audit ledger",
        "node_id": "task.audit_withheld_incident",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:12.927181"
      },
      {
        "kind": "node_end",
        "node_id": "task.audit_withheld_incident",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:12.928147"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Record the held reset in the audit ledger",
        "node_id": "task.audit_withheld_quality",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:12.929088"
      },
      {
        "kind": "node_end",
        "node_id": "task.audit_withheld_quality",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:12.929960"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Incident, automation bridge unreachable",
        "node_id": "sink.incident",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.930861"
      },
      {
        "kind": "node_end",
        "node_id": "sink.incident",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:12.941213"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Held for review, assessment not grounded",
        "node_id": "sink.quality_hold",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.942685"
      },
      {
        "kind": "node_end",
        "node_id": "sink.quality_hold",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:12.943996"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Closure routing",
        "node_id": "decision.closure_route",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.945629"
      },
      {
        "chosen_branch": "closed",
        "kind": "node_end",
        "node_id": "decision.closure_route",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:12.947260"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Human approval refused",
        "node_id": "sink.approval_refused",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.969008"
      },
      {
        "kind": "node_end",
        "node_id": "sink.approval_refused",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:12.970255"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Ticket closed",
        "node_id": "sink.ticket_closed",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:12.971677"
      },
      {
        "kind": "node_end",
        "node_id": "sink.ticket_closed",
        "node_kind": "sink",
        "t": "2026-07-28T11:47:12.973182"
      },
      {
        "kind": "run_end",
        "nodes_executed": 28,
        "status": "completed",
        "t": "2026-07-28T11:47:12.981035"
      }
    ],
    "output_ref": {
      "audit_event_id": "audit-event-test",
      "chosen_branch": "closed",
      "detected_intent": "password_reset",
      "diagnostic_quality_score": 82.5,
      "directory_action": {
        "mode": "dry_run",
        "note": "No directory is contacted. This step records the privileged gesture it would perform.",
        "operation": "reset_user_password",
        "performed_by": "NAWA WE service account (simulated)",
        "result": "success",
        "target_directory": "Nawa corporate directory (simulated)"
      },
      "evaluations": [
        {
          "label": "closed",
          "value": true
        },
        {
          "label": "refused",
          "value": false
        }
      ],
      "evidence_on_file": 3,
      "human_approval": {},
      "identity_verdict": "IDENTITY_VERIFIED Staff ID matched the HR record and the line manager confirmed the request.",
      "outcome": {
        "code": "ticket_closed",
        "label": "Ticket closed",
        "message": "The account password was reset and a temporary password was issued to the requester, who must change it at the next sign-in. The ticket is closed and the action is recorded in the audit ledger.",
        "reset_performed": true
      },
      "temporary_password_issued": "Nawa-Temp-7431",
      "ticket": {
        "id": "ITSD-2026-0729-0148",
        "queue": "End User Support",
        "resolution": "Password reset completed, temporary password issued, requester guided to set a new password at first sign-in.",
        "state": "closed"
      },
      "user_message": "Your password has been reset. Temporary password: Nawa-Temp-7431. You will be asked to change it at your first sign-in. The service desk never asks for your password: do not share it with anyone."
    },
    "status": "completed"
  },
  "quality_guard": {
    "checkpoints": [
      {
        "breakpoints": [],
        "debug_mode": null,
        "kind": "run_start",
        "nodes": 28,
        "t": "2026-07-28T11:47:13.770294"
      },
      {
        "kind": "node_start",
        "label": "Service desk request (call · email · walk-in)",
        "node_id": "source.request",
        "node_kind": "source",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.773467"
      },
      {
        "kind": "node_end",
        "node_id": "source.request",
        "node_kind": "source",
        "t": "2026-07-28T11:47:13.774641"
      },
      {
        "kind": "node_start",
        "label": "Simulation bench · which inbound case",
        "node_id": "decision.case_selector",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.775698"
      },
      {
        "chosen_branch": "quality_guard",
        "kind": "node_end",
        "node_id": "decision.case_selector",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.776883"
      },
      {
        "kind": "node_start",
        "label": "Case A · Forgotten password, complete evidence",
        "node_id": "task.case_nominal",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.777922"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_nominal",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.778969"
      },
      {
        "kind": "node_start",
        "label": "Case B · 'Reset my password' after three failed sign-ins",
        "node_id": "task.case_ambiguous",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.779914"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_ambiguous",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.780882"
      },
      {
        "kind": "node_start",
        "label": "Case C · Legitimate request, weak identity evidence",
        "node_id": "task.case_weak_identity",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.781825"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_weak_identity",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.783595"
      },
      {
        "kind": "node_start",
        "label": "Case D · Clean request, automation bridge down",
        "node_id": "task.case_ad_unreachable",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.784714"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_ad_unreachable",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.785703"
      },
      {
        "kind": "node_start",
        "label": "Case E · Confident assessment, empty evidence record",
        "node_id": "task.case_quality_guard",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.786632"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_quality_guard",
        "node_kind": "task",
        "t": "2026-07-28T11:47:13.787666"
      },
      {
        "kind": "node_start",
        "label": "Step 3a · Dispatch the reset to the automation bridge",
        "node_id": "task.directory_bridge",
        "node_kind": "task",
        "skill_slug": "rpa_dispatch_v1",
        "t": "2026-07-28T11:47:13.788557"
      },
      {
        "kind": "node_end",
        "node_id": "task.directory_bridge",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.789499"
      },
      {
        "kind": "node_start",
        "label": "Step 1 · Classify the request (model call)",
        "node_id": "task.classify_intent",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:13.790471"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.19500002963468432,
        "node_id": "task.classify_intent",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.794297"
      },
      {
        "kind": "node_start",
        "label": "Step 1 · Intent routing",
        "node_id": "decision.intent_route",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.796795"
      },
      {
        "chosen_branch": "password_reset",
        "kind": "node_end",
        "node_id": "decision.intent_route",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.798338"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Routed to another ITSD use case",
        "node_id": "sink.routed_elsewhere",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.799939"
      },
      {
        "kind": "node_end",
        "node_id": "sink.routed_elsewhere",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.801036"
      },
      {
        "kind": "node_start",
        "label": "Step 2 · Assess the identity evidence (model call)",
        "node_id": "task.verify_identity",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:13.802060"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.1556669594720006,
        "node_id": "task.verify_identity",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.805445"
      },
      {
        "kind": "node_start",
        "label": "Step 2 · Identity verdict",
        "node_id": "decision.identity_gate",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.806793"
      },
      {
        "chosen_branch": "verified",
        "kind": "node_end",
        "node_id": "decision.identity_gate",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.807941"
      },
      {
        "kind": "node_start",
        "label": "Step 2c · Grounding check on the identity assessment",
        "node_id": "task.quality_gate",
        "node_kind": "task",
        "skill_slug": "response_eval_v1",
        "t": "2026-07-28T11:47:13.808962"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.16133300960063934,
        "node_id": "task.quality_gate",
        "node_kind": "task",
        "skill_slug": "response_eval_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.812424"
      },
      {
        "kind": "node_start",
        "label": "Step 2b · Human approval before a privileged reset",
        "node_id": "hitl.identity_gate",
        "node_kind": "hitl",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.813722"
      },
      {
        "kind": "node_end",
        "node_id": "hitl.identity_gate",
        "node_kind": "hitl",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.814710"
      },
      {
        "kind": "node_start",
        "label": "Step 2b · Authorisation to execute",
        "node_id": "decision.execute_reset",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.815817"
      },
      {
        "chosen_branch": "quality_hold",
        "kind": "node_end",
        "node_id": "decision.execute_reset",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.817179"
      },
      {
        "kind": "node_start",
        "label": "Step 3 · Reset the account in the directory (simulated)",
        "node_id": "task.ad_reset",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.818333"
      },
      {
        "kind": "node_end",
        "node_id": "task.ad_reset",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.819509"
      },
      {
        "kind": "node_start",
        "label": "Step 4 · Issue a temporary password, force a change at next sign-in (simulated)",
        "node_id": "task.temporary_credential",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.820442"
      },
      {
        "kind": "node_end",
        "node_id": "task.temporary_credential",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.821464"
      },
      {
        "kind": "node_start",
        "label": "Step 5 · Draft the message to the requester (model call, EN/AR)",
        "node_id": "task.draft_user_notice",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:13.822819"
      },
      {
        "kind": "node_end",
        "node_id": "task.draft_user_notice",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.823884"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Confirm the resolution and close the ticket (simulated)",
        "node_id": "task.close_ticket",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.825004"
      },
      {
        "kind": "node_end",
        "node_id": "task.close_ticket",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.826120"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Write the audit ledger entry",
        "node_id": "task.audit_ledger",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:13.827075"
      },
      {
        "kind": "node_end",
        "node_id": "task.audit_ledger",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.828062"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Record the withheld reset in the audit ledger",
        "node_id": "task.audit_withheld_incident",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:13.828968"
      },
      {
        "kind": "node_end",
        "node_id": "task.audit_withheld_incident",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.829913"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Record the held reset in the audit ledger",
        "node_id": "task.audit_withheld_quality",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:13.831004"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.5810830043628812,
        "node_id": "task.audit_withheld_quality",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.841036"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Incident, automation bridge unreachable",
        "node_id": "sink.incident",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.843102"
      },
      {
        "kind": "node_end",
        "node_id": "sink.incident",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.844306"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Held for review, assessment not grounded",
        "node_id": "sink.quality_hold",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.845435"
      },
      {
        "kind": "node_end",
        "node_id": "sink.quality_hold",
        "node_kind": "sink",
        "t": "2026-07-28T11:47:13.846685"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Closure routing",
        "node_id": "decision.closure_route",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.847909"
      },
      {
        "kind": "node_end",
        "node_id": "decision.closure_route",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.849558"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Human approval refused",
        "node_id": "sink.approval_refused",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.851088"
      },
      {
        "kind": "node_end",
        "node_id": "sink.approval_refused",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.852279"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Ticket closed",
        "node_id": "sink.ticket_closed",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.853586"
      },
      {
        "kind": "node_end",
        "node_id": "sink.ticket_closed",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.855574"
      },
      {
        "kind": "run_end",
        "nodes_executed": 28,
        "status": "completed",
        "t": "2026-07-28T11:47:13.859047"
      }
    ],
    "output_ref": {
      "chosen_branch": "quality_hold",
      "detected_intent": "password_reset",
      "diagnostic_hallucination_rate": 1.0,
      "diagnostic_quality_score": 0.0,
      "evaluations": [
        {
          "label": "incident",
          "value": false
        },
        {
          "label": "quality_hold",
          "value": true
        },
        {
          "label": "execute",
          "value": true
        },
        {
          "label": "refused",
          "value": false
        }
      ],
      "evidence_on_file": 0,
      "identity_verdict": "IDENTITY_VERIFIED Staff ID matched the HR record and the line manager confirmed the request.",
      "outcome": {
        "code": "quality_hold_ungrounded_assessment",
        "label": "Held for review - the identity assessment is not backed by any filed evidence",
        "message": "The reset was held before any change was made. The assessment concluded that the requester was identified, but no verifiable proof was on file to support it, and Nawa ITSD policy does not allow an unattended privileged reset on an unsupported assessment. The account was not modified. Record the proofs the caller stated, or route the request to a supervisor for approval.",
        "remediation": "File the evidence the caller asserted (HR match, line-manager confirmation), then re-run. Nothing was written to the directory.",
        "reset_performed": false
      }
    },
    "status": "completed"
  },
  "weak_identity": {
    "checkpoints": [
      {
        "breakpoints": [],
        "debug_mode": null,
        "kind": "run_start",
        "nodes": 28,
        "t": "2026-07-28T11:47:13.873794"
      },
      {
        "kind": "node_start",
        "label": "Service desk request (call · email · walk-in)",
        "node_id": "source.request",
        "node_kind": "source",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.877556"
      },
      {
        "kind": "node_end",
        "node_id": "source.request",
        "node_kind": "source",
        "t": "2026-07-28T11:47:13.878818"
      },
      {
        "kind": "node_start",
        "label": "Simulation bench · which inbound case",
        "node_id": "decision.case_selector",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.879970"
      },
      {
        "chosen_branch": "weak_identity",
        "kind": "node_end",
        "node_id": "decision.case_selector",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.881991"
      },
      {
        "kind": "node_start",
        "label": "Case A · Forgotten password, complete evidence",
        "node_id": "task.case_nominal",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.883338"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_nominal",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.884420"
      },
      {
        "kind": "node_start",
        "label": "Case B · 'Reset my password' after three failed sign-ins",
        "node_id": "task.case_ambiguous",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.885406"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_ambiguous",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.886920"
      },
      {
        "kind": "node_start",
        "label": "Case C · Legitimate request, weak identity evidence",
        "node_id": "task.case_weak_identity",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.887860"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_weak_identity",
        "node_kind": "task",
        "t": "2026-07-28T11:47:13.889017"
      },
      {
        "kind": "node_start",
        "label": "Case D · Clean request, automation bridge down",
        "node_id": "task.case_ad_unreachable",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.889933"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_ad_unreachable",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.890931"
      },
      {
        "kind": "node_start",
        "label": "Case E · Confident assessment, empty evidence record",
        "node_id": "task.case_quality_guard",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.891867"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_quality_guard",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.893052"
      },
      {
        "kind": "node_start",
        "label": "Step 3a · Dispatch the reset to the automation bridge",
        "node_id": "task.directory_bridge",
        "node_kind": "task",
        "skill_slug": "rpa_dispatch_v1",
        "t": "2026-07-28T11:47:13.894122"
      },
      {
        "kind": "node_end",
        "node_id": "task.directory_bridge",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.895138"
      },
      {
        "kind": "node_start",
        "label": "Step 1 · Classify the request (model call)",
        "node_id": "task.classify_intent",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:13.896384"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.29799999902024865,
        "node_id": "task.classify_intent",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.901130"
      },
      {
        "kind": "node_start",
        "label": "Step 1 · Intent routing",
        "node_id": "decision.intent_route",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.902719"
      },
      {
        "chosen_branch": "password_reset",
        "kind": "node_end",
        "node_id": "decision.intent_route",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.904320"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Routed to another ITSD use case",
        "node_id": "sink.routed_elsewhere",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.905604"
      },
      {
        "kind": "node_end",
        "node_id": "sink.routed_elsewhere",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.906743"
      },
      {
        "kind": "node_start",
        "label": "Step 2 · Assess the identity evidence (model call)",
        "node_id": "task.verify_identity",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:13.907837"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.16774999676272273,
        "node_id": "task.verify_identity",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.911631"
      },
      {
        "kind": "node_start",
        "label": "Step 2 · Identity verdict",
        "node_id": "decision.identity_gate",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.913119"
      },
      {
        "chosen_branch": "insufficient",
        "kind": "node_end",
        "node_id": "decision.identity_gate",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.914425"
      },
      {
        "kind": "node_start",
        "label": "Step 2c · Grounding check on the identity assessment",
        "node_id": "task.quality_gate",
        "node_kind": "task",
        "skill_slug": "response_eval_v1",
        "t": "2026-07-28T11:47:13.916229"
      },
      {
        "kind": "node_end",
        "node_id": "task.quality_gate",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.917741"
      },
      {
        "kind": "node_start",
        "label": "Step 2b · Human approval before a privileged reset",
        "node_id": "hitl.identity_gate",
        "node_kind": "hitl",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.918988"
      },
      {
        "kind": "node_end",
        "node_id": "hitl.identity_gate",
        "node_kind": "hitl",
        "pause": true,
        "t": "2026-07-28T11:47:13.926840"
      },
      {
        "correlation_key": null,
        "decision_id": "0755be12-b3f8-4d82-b75c-f9597d8e8c86",
        "expires_at": "2026-07-29T11:47:13.923993",
        "expiry_action": "reject",
        "kind": "hitl_pause",
        "membrane_egress": false,
        "node_id": "hitl.identity_gate",
        "prompt": "Identity evidence is insufficient for an automated password reset. Approve the privileged reset (simulated) for this requester?",
        "t": "2026-07-28T11:47:13.930089"
      },
      {
        "decision_status": "accepted",
        "kind": "hitl_resume",
        "node_id": "hitl.identity_gate",
        "t": "2026-07-28T11:47:13.944055"
      },
      {
        "kind": "node_start",
        "label": "Step 2b · Authorisation to execute",
        "node_id": "decision.execute_reset",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.945689"
      },
      {
        "chosen_branch": "execute",
        "kind": "node_end",
        "node_id": "decision.execute_reset",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.947330"
      },
      {
        "kind": "node_start",
        "label": "Step 3 · Reset the account in the directory (simulated)",
        "node_id": "task.ad_reset",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.949424"
      },
      {
        "kind": "node_end",
        "node_id": "task.ad_reset",
        "node_kind": "task",
        "t": "2026-07-28T11:47:13.951692"
      },
      {
        "kind": "node_start",
        "label": "Step 4 · Issue a temporary password, force a change at next sign-in (simulated)",
        "node_id": "task.temporary_credential",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.953268"
      },
      {
        "kind": "node_end",
        "node_id": "task.temporary_credential",
        "node_kind": "task",
        "t": "2026-07-28T11:47:13.954939"
      },
      {
        "kind": "node_start",
        "label": "Step 5 · Draft the message to the requester (model call, EN/AR)",
        "node_id": "task.draft_user_notice",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:13.956515"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.20899996161460876,
        "node_id": "task.draft_user_notice",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.960977"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Confirm the resolution and close the ticket (simulated)",
        "node_id": "task.close_ticket",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.962974"
      },
      {
        "kind": "node_end",
        "node_id": "task.close_ticket",
        "node_kind": "task",
        "t": "2026-07-28T11:47:13.966816"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Write the audit ledger entry",
        "node_id": "task.audit_ledger",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:13.968460"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.1829169923439622,
        "node_id": "task.audit_ledger",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.972857"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Record the withheld reset in the audit ledger",
        "node_id": "task.audit_withheld_incident",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:13.975029"
      },
      {
        "kind": "node_end",
        "node_id": "task.audit_withheld_incident",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.977028"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Record the held reset in the audit ledger",
        "node_id": "task.audit_withheld_quality",
        "node_kind": "task",
        "skill_slug": "audit_log_v1",
        "t": "2026-07-28T11:47:13.981707"
      },
      {
        "kind": "node_end",
        "node_id": "task.audit_withheld_quality",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.985811"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Incident, automation bridge unreachable",
        "node_id": "sink.incident",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.987662"
      },
      {
        "kind": "node_end",
        "node_id": "sink.incident",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.989426"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Held for review, assessment not grounded",
        "node_id": "sink.quality_hold",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.991162"
      },
      {
        "kind": "node_end",
        "node_id": "sink.quality_hold",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.992995"
      },
      {
        "kind": "node_start",
        "label": "Step 6 · Closure routing",
        "node_id": "decision.closure_route",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.994763"
      },
      {
        "chosen_branch": "closed",
        "kind": "node_end",
        "node_id": "decision.closure_route",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.996680"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Human approval refused",
        "node_id": "sink.approval_refused",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.998420"
      },
      {
        "kind": "node_end",
        "node_id": "sink.approval_refused",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:14.000087"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Ticket closed",
        "node_id": "sink.ticket_closed",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:14.001659"
      },
      {
        "kind": "node_end",
        "node_id": "sink.ticket_closed",
        "node_kind": "sink",
        "t": "2026-07-28T11:47:14.003357"
      },
      {
        "kind": "run_end",
        "nodes_executed": 28,
        "status": "completed",
        "t": "2026-07-28T11:47:14.007511"
      }
    ],
    "output_ref": {
      "audit_event_id": "audit-event-test",
      "chosen_branch": "closed",
      "detected_intent": "password_reset",
      "directory_action": {
        "mode": "dry_run",
        "note": "No directory is contacted. This step records the privileged gesture it would perform.",
        "operation": "reset_user_password",
        "performed_by": "NAWA WE service account (simulated)",
        "result": "success",
        "target_directory": "Nawa corporate directory (simulated)"
      },
      "evaluations": [
        {
          "label": "closed",
          "value": true
        },
        {
          "label": "refused",
          "value": false
        }
      ],
      "human_approval": {
        "approved": true,
        "decision_id": "0755be12-b3f8-4d82-b75c-f9597d8e8c86",
        "decision_status": "accepted",
        "rejected": false
      },
      "identity_verdict": "IDENTITY_INSUFFICIENT No line-manager confirmation and no staff ID matched against the HR record.",
      "outcome": {
        "code": "ticket_closed",
        "label": "Ticket closed",
        "message": "The account password was reset and a temporary password was issued to the requester, who must change it at the next sign-in. The ticket is closed and the action is recorded in the audit ledger.",
        "reset_performed": true
      },
      "temporary_password_issued": "Nawa-Temp-7431",
      "ticket": {
        "id": "ITSD-2026-0729-0148",
        "queue": "End User Support",
        "resolution": "Password reset completed, temporary password issued, requester guided to set a new password at first sign-in.",
        "state": "closed"
      },
      "user_message": "Your password has been reset. Temporary password: Nawa-Temp-7431. You will be asked to change it at your first sign-in. The service desk never asks for your password: do not share it with anyone."
    },
    "status": "completed"
  },
  "weak_identity_pending": {
    "checkpoints": [
      {
        "breakpoints": [],
        "debug_mode": null,
        "kind": "run_start",
        "nodes": 28,
        "t": "2026-07-28T11:47:13.873794"
      },
      {
        "kind": "node_start",
        "label": "Service desk request (call · email · walk-in)",
        "node_id": "source.request",
        "node_kind": "source",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.877556"
      },
      {
        "kind": "node_end",
        "node_id": "source.request",
        "node_kind": "source",
        "t": "2026-07-28T11:47:13.878818"
      },
      {
        "kind": "node_start",
        "label": "Simulation bench · which inbound case",
        "node_id": "decision.case_selector",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.879970"
      },
      {
        "chosen_branch": "weak_identity",
        "kind": "node_end",
        "node_id": "decision.case_selector",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.881991"
      },
      {
        "kind": "node_start",
        "label": "Case A · Forgotten password, complete evidence",
        "node_id": "task.case_nominal",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.883338"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_nominal",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.884420"
      },
      {
        "kind": "node_start",
        "label": "Case B · 'Reset my password' after three failed sign-ins",
        "node_id": "task.case_ambiguous",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.885406"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_ambiguous",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.886920"
      },
      {
        "kind": "node_start",
        "label": "Case C · Legitimate request, weak identity evidence",
        "node_id": "task.case_weak_identity",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.887860"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_weak_identity",
        "node_kind": "task",
        "t": "2026-07-28T11:47:13.889017"
      },
      {
        "kind": "node_start",
        "label": "Case D · Clean request, automation bridge down",
        "node_id": "task.case_ad_unreachable",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.889933"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_ad_unreachable",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.890931"
      },
      {
        "kind": "node_start",
        "label": "Case E · Confident assessment, empty evidence record",
        "node_id": "task.case_quality_guard",
        "node_kind": "task",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.891867"
      },
      {
        "kind": "node_end",
        "node_id": "task.case_quality_guard",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.893052"
      },
      {
        "kind": "node_start",
        "label": "Step 3a · Dispatch the reset to the automation bridge",
        "node_id": "task.directory_bridge",
        "node_kind": "task",
        "skill_slug": "rpa_dispatch_v1",
        "t": "2026-07-28T11:47:13.894122"
      },
      {
        "kind": "node_end",
        "node_id": "task.directory_bridge",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.895138"
      },
      {
        "kind": "node_start",
        "label": "Step 1 · Classify the request (model call)",
        "node_id": "task.classify_intent",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:13.896384"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.29799999902024865,
        "node_id": "task.classify_intent",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.901130"
      },
      {
        "kind": "node_start",
        "label": "Step 1 · Intent routing",
        "node_id": "decision.intent_route",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.902719"
      },
      {
        "chosen_branch": "password_reset",
        "kind": "node_end",
        "node_id": "decision.intent_route",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.904320"
      },
      {
        "kind": "node_start",
        "label": "Outcome · Routed to another ITSD use case",
        "node_id": "sink.routed_elsewhere",
        "node_kind": "sink",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.905604"
      },
      {
        "kind": "node_end",
        "node_id": "sink.routed_elsewhere",
        "node_kind": "sink",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.906743"
      },
      {
        "kind": "node_start",
        "label": "Step 2 · Assess the identity evidence (model call)",
        "node_id": "task.verify_identity",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "t": "2026-07-28T11:47:13.907837"
      },
      {
        "cost": 0.0,
        "kind": "node_end",
        "latency_ms": 0.16774999676272273,
        "node_id": "task.verify_identity",
        "node_kind": "task",
        "skill_slug": "azure_llm_v1",
        "status": "completed",
        "t": "2026-07-28T11:47:13.911631"
      },
      {
        "kind": "node_start",
        "label": "Step 2 · Identity verdict",
        "node_id": "decision.identity_gate",
        "node_kind": "decision",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.913119"
      },
      {
        "chosen_branch": "insufficient",
        "kind": "node_end",
        "node_id": "decision.identity_gate",
        "node_kind": "decision",
        "t": "2026-07-28T11:47:13.914425"
      },
      {
        "kind": "node_start",
        "label": "Step 2c · Grounding check on the identity assessment",
        "node_id": "task.quality_gate",
        "node_kind": "task",
        "skill_slug": "response_eval_v1",
        "t": "2026-07-28T11:47:13.916229"
      },
      {
        "kind": "node_end",
        "node_id": "task.quality_gate",
        "node_kind": "task",
        "skipped_reason": "all_inputs_dead",
        "status": "skipped",
        "t": "2026-07-28T11:47:13.917741"
      },
      {
        "kind": "node_start",
        "label": "Step 2b · Human approval before a privileged reset",
        "node_id": "hitl.identity_gate",
        "node_kind": "hitl",
        "skill_slug": null,
        "t": "2026-07-28T11:47:13.918988"
      },
      {
        "kind": "node_end",
        "node_id": "hitl.identity_gate",
        "node_kind": "hitl",
        "pause": true,
        "t": "2026-07-28T11:47:13.926840"
      },
      {
        "correlation_key": null,
        "decision_id": "0755be12-b3f8-4d82-b75c-f9597d8e8c86",
        "expires_at": "2026-07-29T11:47:13.923993",
        "expiry_action": "reject",
        "kind": "hitl_pause",
        "membrane_egress": false,
        "node_id": "hitl.identity_gate",
        "prompt": "Identity evidence is insufficient for an automated password reset. Approve the privileged reset (simulated) for this requester?",
        "t": "2026-07-28T11:47:13.930089"
      }
    ],
    "output_ref": {},
    "status": "hitl_pending"
  }
} as const;
