import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { computed, signal } from '@angular/core';
import { convertToParamMap, DefaultUrlSerializer } from '@angular/router';
import { Subject } from 'rxjs';
import type { RunMandate, SystemMandate } from '@app/features/mandate/mandate.models';
import { SystemMandateCoverageComponent } from './system-mandate-coverage.component';
import { MANDATE_FACETS } from './system-mandate-coverage.vm';

function fixture() {
  const systemResponses: Subject<SystemMandate>[] = [];
  const runResponses: Subject<RunMandate>[] = [];
  let activeScope = true;
  const data = signal<SystemMandate | null>(null);
  const routes: unknown[] = [];
  const view = Object.assign(Object.create(SystemMandateCoverageComponent.prototype), {
    systemId: () => 'system-1', data, facets: MANDATE_FACETS,
    i18n: {t: (key: string) => key, locale: () => 'fr'},
    recentRuns: computed(() => (data()?.recent_runs ?? []).slice(0, 4)),
    loading: signal(false), error: signal(false), selectedRunId: signal(''), selectedRun: signal<RunMandate | null>(null), selectedFacet: signal(null), runLoading: signal(false), runError: signal(false), generation: 0,
    workspace: {captureRequestScope: () => ({}), isRequestScopeCurrent: () => activeScope},
    route: {snapshot: {queryParamMap: convertToParamMap({})}},
    navigation: {objectUrlTree: (_type: string, id: string) => new DefaultUrlSerializer().parse(`/runs/${id}?lens=govern`)},
    router: {navigate: (_: unknown, options: unknown) => {routes.push(options); return Promise.resolve(true);}},
    api: {
      system: () => {const response = new Subject<SystemMandate>(); systemResponses.push(response); return response;},
      run: () => {const response = new Subject<RunMandate>(); runResponses.push(response); return response;},
    },
  }) as SystemMandateCoverageComponent;
  return {view, systemResponses, runResponses, routes, leave: () => {activeScope = false;}};
}

const config = {state: 'explicit', mode: 'enforce', version: 2, policy_id: 'policy', policy_revision: 'current', spec: {}} as const;
const mandate = (): SystemMandate => ({system_id: 'system-1', system_name: 'System', configuration: config, permissions: {can_edit: false}, limitations: [], recent_runs: [
  {run_id: 'run-1', status: 'completed', started_at: null, evidence_state: 'not_recorded', event_count: 0},
  {run_id: 'run-2', status: 'failed', started_at: null, evidence_state: 'recorded', event_count: 1},
]});
const proof = (runId = 'run-1'): RunMandate => ({run_id: runId, system_id: 'system-1', status: 'completed', applied: {state: 'not_recorded', policy_id: null, revision: null, snapshot_at: null, mode: null, version: null, spec: null}, events: [], counts: {recorded_events: 0, blocked: 0, awaiting_human: 0}, limitations: []});

test('System coverage selects a real Run and never fills its missing snapshot from current configuration', () => {
  const {view, systemResponses, runResponses} = fixture();
  view.load(); systemResponses[0].next(mandate()); runResponses[0].next(proof());
  assert.equal(view.selectedRunId(), 'run-1');
  assert.equal(view.selectedRun()?.applied.mode, null);
  assert.equal(view.selectedRun()?.applied.state, 'not_recorded');
  assert.equal(view.data()?.configuration.mode, 'enforce');
});

test('selecting a cell preserves the exact Run and facet in the current route; stale reads cannot replace it', () => {
  const {view, systemResponses, runResponses, routes} = fixture();
  view.load(); systemResponses[0].next(mandate());
  view.selectRun('run-2', 'valves');
  runResponses[0].next(proof()); runResponses[1].next(proof('run-2'));
  assert.equal(view.selectedRun()?.run_id, 'run-2');
  assert.equal(view.selectedFacet(), 'valves');
  assert.deepEqual((routes[0] as {queryParams: unknown}).queryParams, {mandateRun: 'run-2', mandateFacet: 'valves'});
  const proofUrl = view.eventUrl('decision:123');
  assert.deepEqual(proofUrl.queryParams, {lens: 'govern', mandateEvent: 'decision:123'});
  assert.match(new DefaultUrlSerializer().serialize(proofUrl), /^\/runs\/run-2\?/);
  view.selectRun('not-authorized'); assert.equal(runResponses.length, 2);
});

test('wrong System identities, revoked access and late workspace responses never populate proof panels', () => {
  const first = fixture(); first.view.load(); first.systemResponses[0].next({...mandate(), system_id: 'other'});
  assert.equal(first.view.error(), true); assert.equal(first.view.data(), null);
  const second = fixture(); second.view.load(); second.systemResponses[0].next(mandate());
  second.runResponses[0].next({...proof(), system_id: 'other'});
  assert.equal(second.view.runError(), true); assert.equal(second.view.selectedRun(), null);
  second.view.selectRun('run-2'); second.runResponses[1].error(new Error('forbidden'));
  assert.equal(second.view.runError(), true); assert.equal(second.view.selectedRun(), null);
  const third = fixture(); third.view.load(); third.leave(); third.systemResponses[0].next(mandate());
  assert.equal(third.view.data(), null);
});


test('proof dates render in the selected locale without Angular locale bundles', () => {
  const {view} = fixture();
  assert.match(view.eventTime('2026-09-17T09:41:00Z'), /sept/);
  assert.equal(view.eventTime('2026-09-17T09:41:00'), view.eventTime('2026-09-17T09:41:00Z'));
  assert.equal(view.facetLabel('delegation'), 'mandate_system.delegation');
  assert.equal(view.eventTime('invalid'), 'mandate_system.no_time');
  assert.equal(view.eventTime(null), 'mandate_system.no_time');
});


test('a Run response from the previous System is ignored before route effects reload the view', () => {
  const {view, systemResponses, runResponses} = fixture();
  view.load(); systemResponses[0].next(mandate());
  Object.assign(view, {systemId: () => 'system-2'});
  runResponses[0].next(proof());
  assert.equal(view.selectedRun(), null);
});
