import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mandateInitialEvent, mandateLane, mandateReviewConfigured, mandateRunSummary, mandateSnapshotNote, type MandateEvent, type RunMandate, type SystemMandate } from './mandate.models';

function event(id: string, status: MandateEvent['status'], facet = 'capabilities'): MandateEvent {
  return {id,status,facet,kind:'policy_shadow',at:null,node_id:null,invocation_id:null,decision_id:null,rule:null,details:{}};
}
function run(events: MandateEvent[], status = 'completed'): RunMandate {
  return {run_id:'run-1',system_id:'system-1',status,applied:{state:'recorded',policy_id:'policy-1',revision:'a',snapshot_at:null,mode:'enforce',version:2,spec:null},events,counts:{recorded_events:events.length,blocked:0,awaiting_human:0},limitations:[]};
}

test('configured/applied enforce and a completed Run do not fabricate exercised checks', () => {
  assert.equal(mandateRunSummary(run([])), 'not_recorded');
  assert.equal(mandateRunSummary(run([event('observation','observed')])), 'recorded');
  assert.equal(mandateRunSummary(run([event('refusal','blocked')])), 'blocked');
});

test('a historical human pause is not presented as a current approval request', () => {
  const pending = event('gate','awaiting_human','outbound');
  assert.equal(mandateRunSummary(run([pending],'hitl_pending')), 'awaiting_human');
  assert.equal(mandateRunSummary(run([pending],'completed')), 'recorded');
  assert.equal(mandateRunSummary(run([event('human','approved','outbound')])), 'recorded');
});

test('linked selection restores the exact persisted event and falls back to an actual reservation', () => {
  const events = [event('source','recorded','inbound'),event('refusal','blocked'),event('gate','awaiting_human','outbound')];
  assert.equal(mandateInitialEvent(events,'source')?.id, 'source');
  assert.equal(mandateInitialEvent(events,'removed')?.id, 'refusal');
  assert.equal(mandateInitialEvent([],null), null);
});

test('evidence lanes follow recorded facets without inventing a successful source or delegation', () => {
  assert.equal(mandateLane(event('1','recorded','inbound')), 'sources');
  assert.equal(mandateLane(event('2','blocked','valves')), 'operations');
  assert.equal(mandateLane(event('3','recorded','delegation')), 'operations');
  assert.equal(mandateLane(event('4','approved','outbound')), 'review');
  assert.equal(mandateLane(event('5','recorded','provenance')), 'review');
});

test('derived defaults and unconfigured facets never advertise a configured human gate', () => {
  const config: SystemMandate['configuration'] = {state:'derived',mode:'compat',policy_id:'p',policy_revision:'r',version:1,configured_facets:['capabilities'],spec:{outbound:{expert_review_required:true}}};
  assert.equal(mandateReviewConfigured(config), false);
  assert.equal(mandateReviewConfigured({...config,state:'explicit'}), false);
  assert.equal(mandateReviewConfigured({...config,state:'explicit',configured_facets:['outbound']}), true);
  assert.equal(mandateReviewConfigured({...config,state:'explicit',configured_facets:['valves'],spec:{valves:{mandatory_hitl_if_confidence_below:0.8}}}), true);
});

test('snapshot notes distinguish missing history, an absent policy and an invalid frozen identity', () => {
  const value = run([]);
  assert.equal(mandateSnapshotNote(value), 'mandate.run.snapshot_missing_hint');
  assert.equal(mandateSnapshotNote({...value, limitations: ['no_policy_at_first_start']}), 'mandate.limitation.no_policy_at_first_start');
  for (const reason of ['frozen_mandate_invalid', 'mandate_start_identity_mismatch'] as const) {
    assert.equal(mandateSnapshotNote({...value, applied: {...value.applied, not_recorded_reason: reason}}), `mandate.limitation.${reason}`);
  }
  assert.equal(mandateSnapshotNote({...value, applied: {...value.applied, spec: {}, policy_binding: 'legacy_first_start'}}), 'mandate.limitation.legacy_first_start');
  assert.equal(mandateSnapshotNote({...value, applied: {...value.applied, spec: {}, policy_binding: 'frozen'}}), null);
});
