import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { computed, signal } from '@angular/core';
import { Subject, Subscription } from 'rxjs';
import { MandateEditorComponent } from './mandate-editor.component';
import type { MandateDraftState, MandateSpec, MandateValidation } from './mandate.models';
import { MANDATE_LIST_FIELDS, MANDATE_NUMBER_FIELDS, mandateJson } from './mandate-editor.vm';
import { MANDATE_SYSTEM_FR, MANDATE_SYSTEM_EN } from '../../core/i18n/mandate-system.dict';

const spec = (): MandateSpec => ({version: 1, inbound: {collection_allowlist: ['allowed', 'hidden']}, outbound: {expert_review_required: false}, capabilities: {allowed_actions: ['existing-action'], allowed_delegations: [{system_id: 'child', input_contract: {type: 'object', additionalProperties: false}, output_contract: {type: 'object'}, branches: ['ok']}]}, valves: {max_cost_per_decision: .2, circuit_breaker: {failure_threshold: 3}}});
const state = (binding: 'frozen' | 'legacy_current' = 'legacy_current'): MandateDraftState => ({
  system_id: 'system-a', permissions: {can_edit: true}, draft: {revision: 5, flow_sha256: 'flow', snapshot_sha256: 'policy-a', base_published_version_id: 'v2', spec: spec(), policy_binding: binding},
  published: {version_id: 'v2', version_number: 2, spec: spec(), snapshot_sha256: null, policy_revision: null, policy_binding: 'legacy'},
  options: {collections: [{id: 'allowed', label: 'Authorized manual'}], skills: [], models: [], delegations: [{system_id: 'child', label: 'Child System', input_contract: {type: 'object', additionalProperties: false}, output_contract: {type: 'object'}, branches: ['ok']}]},
  validation: {valid: false, checks: [{code: 'runtime_tests', status: 'not_run'}]},
});
function harness() {
  const reads: Subject<MandateDraftState>[] = [], writes: Subject<MandateDraftState>[] = [], validations: Subject<MandateValidation>[] = [];
  const writeCalls: unknown[][] = [], validationCalls: unknown[][] = [];
  let currentScope = true;
  const model = signal<MandateDraftState | null>(null), draft = signal<MandateSpec | null>(null), loading = signal(false), saving = signal(false), validating = signal(false), reviewed = signal(false), conflict = signal(false), revoked = signal(false), validation = signal<MandateValidation | null>(null);
  const busy = computed(() => loading() || saving() || validating());
  const editable = computed(() => model()?.permissions.can_edit === true && !conflict() && !revoked());
  const dirty = computed(() => !!model() && mandateJson(draft()) !== mandateJson(model()!.draft.spec));
  const needsSave = computed(() => dirty() || model()?.draft.policy_binding !== 'frozen' || model()?.draft.spec_is_seed === true);
  const view = Object.assign(Object.create(MandateEditorComponent.prototype), {
    systemId: () => 'system-a', state: model, draft, loading, saving, validating, reviewed, conflict, revoked, validation,
    error: signal<string | null>(null), saved: signal(false), readOnly: signal(false), generation: 0, requests: new Subscription(),
    busy, editable, dirty, needsSave, canSave: computed(() => editable() && !busy() && needsSave() && reviewed() && !!draft()),
    canPublish: computed(() => editable() && !busy() && !needsSave() && validation()?.valid === true),
    modes: ['compat', 'shadow', 'enforce'], listFields: MANDATE_LIST_FIELDS, numbers: MANDATE_NUMBER_FIELDS,
    delegations: computed(() => draft()?.capabilities?.allowed_delegations ?? []),
    i18n: {t: (key: string) => key, locale: () => 'en'},
    workspace: {captureRequestScope: () => ({workspaceSlug: 'showcase'}), isRequestScopeCurrent: () => currentScope},
    api: {
      draft: () => {const r = new Subject<MandateDraftState>(); reads.push(r); return r;},
      saveDraft: (...args: unknown[]) => {writeCalls.push(args); const r = new Subject<MandateDraftState>(); writes.push(r); return r;},
      validateDraft: (...args: unknown[]) => {validationCalls.push(args); const r = new Subject<MandateValidation>(); validations.push(r); return r;},
    },
  }) as MandateEditorComponent;
  return {view, reads, writes, validations, writeCalls, validationCalls, leave: () => {currentScope = false;}};
}
const checkbox = (checked: boolean) => ({target: {checked}} as unknown as Event);
const numberInput = (value: string) => ({target: {value, validity: {badInput: false}}} as unknown as Event);

test('mandate editing saves only after reviewed changes with both draft and snapshot CAS', () => {
  const h = harness(); h.view.load(); h.reads[0].next(state());
  h.view.setNumber('valves.max_cost_per_decision', 1, numberInput('0.1'));
  h.view.save(); assert.equal(h.writeCalls.length, 0);
  h.view.reviewed.set(true); h.view.save(); h.view.save();
  assert.equal(h.writeCalls.length, 1);
  const body = h.writeCalls[0][1] as {expected_revision: number; expected_snapshot_sha256: string; spec: MandateSpec};
  assert.equal(body.expected_revision, 5); assert.equal(body.expected_snapshot_sha256, 'policy-a');
  assert.equal(body.spec.version, 1); assert.equal(body.spec.valves?.max_cost_per_decision, .1);
  assert.deepEqual(body.spec.capabilities, spec().capabilities); assert.deepEqual(body.spec.valves?.circuit_breaker, {failure_threshold: 3});
  assert.equal(h.view.state()?.published.spec?.valves?.max_cost_per_decision, .2);
  h.view.setNumber('valves.max_cost_per_decision', 1, numberInput('9'));
  assert.equal(h.view.draft()?.valves?.max_cost_per_decision, .1, 'form edits are frozen during a save');
});

test('resource edits preserve unavailable references and typed delegation contracts; mode upgrade is explicit', () => {
  const h = harness(); h.view.load(); h.reads[0].next(state());
  assert.deepEqual(h.view.retainedReferences('collections', 'inbound.collection_allowlist'), ['hidden']);
  h.view.toggleReference('inbound.collection_allowlist', 'allowed', checkbox(false));
  assert.deepEqual(h.view.draft()?.inbound?.collection_allowlist, ['hidden']);
  assert.equal(h.view.draft()?.version, 1);
  const rule = state().options.delegations[0];
  h.view.toggleDelegation(rule, checkbox(false)); h.view.toggleDelegation(rule, checkbox(true));
  assert.deepEqual(h.view.draft()?.capabilities?.allowed_delegations, spec().capabilities?.allowed_delegations);
  h.view.reviewed.set(true); h.view.setMode({target: {value: 'enforce'}} as unknown as Event);
  assert.equal(h.view.draft()?.version, 2); assert.equal(h.view.draft()?.enforcement_mode, 'enforce'); assert.equal(h.view.reviewed(), false);
  assert.notEqual(h.view.displayValue(.000001, 'valves.max_cost_per_decision'), '0');
});

test('validation applies to the saved revision and never reports runtime tests as executed', () => {
  const h = harness(); h.view.load(); h.reads[0].next(state()); h.view.validate(); assert.equal(h.validationCalls.length, 0);
  h.view.reviewed.set(true); h.view.save();
  h.writes[0].next({...state('frozen'), draft: {...state('frozen').draft, revision: 6, snapshot_sha256: 'policy-b'}});
  assert.equal(h.view.saved(), true); h.view.validate();
  assert.deepEqual(h.validationCalls[0][1], {expected_revision: 6, expected_snapshot_sha256: 'policy-b'});
  h.validations[0].next({valid: true, checks: [{code: 'mandate_schema', status: 'passed'}, {code: 'runtime_tests', status: 'not_run'}]});
  assert.equal(h.view.canPublish(), true); assert.equal(h.view.validation()?.checks[1].status, 'not_run');
  h.view.setBoolean('outbound.expert_review_required', checkbox(true));
  assert.equal(h.view.validation(), null); assert.equal(h.view.canPublish(), false);
});

test('conflicts retain user changes and require reload, denied access disables mutation', () => {
  const h = harness(); h.view.load(); h.reads[0].next(state());
  h.view.setBoolean('provenance.require_citations', checkbox(true)); h.view.reviewed.set(true); h.view.save(); h.writes[0].error({status: 409});
  assert.equal(h.view.error(), 'conflict'); assert.equal(h.view.draft()?.provenance?.require_citations, true); assert.equal(h.view.canSave(), false);
  h.view.load(); h.reads[1].next(state()); h.view.reviewed.set(true); h.view.save(); h.writes[1].error({status: 403});
  assert.equal(h.view.error(), 'denied'); assert.equal(h.view.editable(), false);
});

test('late workspace or System responses cannot replace a mandate, and validation failure blocks publication', () => {
  const h = harness(); h.view.load(); h.leave(); h.reads[0].next(state()); assert.equal(h.view.state(), null);
  const other = harness(); other.view.load(); other.reads[0].next({...state(), system_id: 'other'}); assert.equal(other.view.state(), null);
  const failed = harness(); failed.view.load(); failed.reads[0].next(state('frozen')); failed.view.validate(); failed.validations[0].error({status: 500});
  assert.equal(failed.view.error(), 'validation_error'); assert.equal(failed.view.validation(), null); assert.equal(failed.view.canPublish(), false);
});

test('failed checks retain actionable compiler details and localize known correction reasons', () => {
  const h = harness();
  const failure = {code: 'flow_contract', status: 'failed' as const, reason_code: 'SKILL_CONTRACT_MISMATCH', message: 'Skill contract differs from node contract.', details: {node_id: 'summarize', path: 'nodes/summarize'}};
  for (const dictionary of [MANDATE_SYSTEM_FR, MANDATE_SYSTEM_EN]) {
    h.view.i18n.t = (key: string) => dictionary[key as keyof typeof dictionary] ?? key;
    assert.equal(h.view.checkReason(failure), dictionary['mandate_system.editor.reason.SKILL_CONTRACT_MISMATCH']);
    assert.equal(h.view.checkReason({...failure, reason_code: 'NEW_COMPILER_REASON'}), failure.message);
  }
  h.view.load(); h.reads[0].next(state('frozen')); h.view.validate();
  h.validations[0].next({valid: false, checks: [failure]});
  assert.deepEqual(h.view.validation()?.checks[0].details, failure.details);
  assert.equal(h.view.canPublish(), false);
});

test('an unavailable versioned draft retains the existing read-only mandate surface', () => {
  for (const code of ['FLOW_PUBLICATION_DISABLED', 'FLOW_DRAFT_STATE_MISSING']) {
    const h = harness(); h.view.load(); h.reads[0].error({status: 404, error: {detail: {code}}});
    assert.equal(h.view.readOnly(), true); assert.equal(h.view.state(), null); assert.equal(h.view.canSave(), false);
  }
  const inaccessible = harness(); inaccessible.view.load(); inaccessible.reads[0].error({status: 404, error: {detail: 'System not found'}});
  assert.equal(inaccessible.view.readOnly(), false); assert.equal(inaccessible.view.error(), 'load_error');
});

test('credential projection rejection explains the required fix without exposing server details', () => {
  const h = harness(); h.view.load();
  h.reads[0].error({status: 422, error: {detail: {code: 'MANDATE_POLICY_CONTAINS_CREDENTIALS', message: 'secret-should-not-be-shown'}}});
  assert.equal(h.view.error(), 'reason.MANDATE_POLICY_CONTAINS_CREDENTIALS');
  const unknown = harness(); unknown.view.load(); unknown.reads[0].error({status: 422, error: {detail: {code: 'UNKNOWN', message: 'private-details'}}});
  assert.equal(unknown.view.error(), 'load_error');
});

test('a v2 seed over a frozen absence must be explicitly saved before validation', () => {
  const h = harness(); const original = state('frozen');
  h.view.load(); h.reads[0].next({...original, draft: {...original.draft, spec_is_seed: true}});
  assert.equal(h.view.needsSave(), true); h.view.validate(); assert.equal(h.validationCalls.length, 0);
  h.view.reviewed.set(true); h.view.save();
  h.writes[0].next({...original, draft: {...original.draft, revision: 6, snapshot_sha256: 'saved-explicit-seed', spec_is_seed: false}});
  h.view.validate(); assert.equal(h.validationCalls.length, 1);
  assert.equal((h.validationCalls[0][1] as {expected_snapshot_sha256:string}).expected_snapshot_sha256, 'saved-explicit-seed');
});
