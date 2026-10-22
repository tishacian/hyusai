import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DestroyRef, Injector } from '@angular/core';
import { Subject, of, throwError, type Observable } from 'rxjs';
import { CanonicalApiService, type Run } from '@app/core/canonical-api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { STRICT } from '@app/shared/ui/load-state';
import { FlowObservationService } from './flow-observation.service';
import type { FlowObservationRun } from './flow-observation.vm';

function run(id = 'r1', extra: Partial<FlowObservationRun> = {}): FlowObservationRun {
  return { id, system_id: 's1', status: 'completed', started_at: '2026-10-22T08:00:00Z', ...extra };
}
function outputRun(id = 'r1', nodeId = 'forecast'): FlowObservationRun {
  return run(id, { skill_invocations: [{ id: `${id}-i`, status: 'completed', trace: { node_id: nodeId }, output_ref: { result: id } }] });
}

function fixture() {
  const lists: Subject<Run[]>[] = [], reads: Array<{ id: string; policy: unknown; result: Subject<Run | null> }> = [];
  let handler: ((id: string) => Observable<Run | null>) | null = null;
  const api = {
    listRuns(params: { system_id: string }) { assert.ok(params.system_id); const result = new Subject<Run[]>(); lists.push(result); return result; },
    getRun(id: string, policy: unknown) {
      const result = new Subject<Run | null>(); reads.push({ id, policy, result });
      return handler ? handler(id) : result;
    },
  };
  function scope() {
    let epoch = 0;
    const resetters = new Set<() => void>();
    return {
      captureRequestScope: () => ({ epoch }), isRequestScopeCurrent: (captured: { epoch: number }) => captured.epoch === epoch,
      registerContextReset(callback: () => void) { resetters.add(callback); return () => { resetters.delete(callback); }; },
      change() { for (const reset of [...resetters]) reset(); epoch++; },
      silentChange() { epoch++; },
    };
  }
  const workspace = scope(), auth = scope();
  const injector = Injector.create({ providers: [FlowObservationService,
    { provide: CanonicalApiService, useValue: api }, { provide: WorkspaceService, useValue: workspace },
    { provide: AuthStore, useValue: auth }, { provide: DestroyRef, useValue: { onDestroy: () => () => {} } },
  ] });
  const service = injector.get(FlowObservationService);
  service.bindSystem('s1');
  return { service, lists, reads, workspace, auth, setHandler: (value: typeof handler) => { handler = value; } };
}

test('observation service: opening reads recent Runs then a completed Run; inspecting is local', () => {
  const { service, lists, reads } = fixture();
  assert.equal(lists.length, 0);
  service.open(); lists[0].next([run()]);
  assert.equal(reads[0].id, 'r1'); assert.equal(reads[0].policy, STRICT);
  reads[0].result.next(outputRun()); service.inspectNode('forecast');
  assert.equal(service.currentAttempt()?.output?.['result'], 'r1');
  service.inspectNode('unexecuted');
  assert.equal(service.currentNode(), null); assert.equal(reads.length, 1);
  service.dispose();
});

test('observation service: selecting another Run cancels reads and clears previous payload immediately', () => {
  const { service, lists, reads } = fixture();
  service.open(); lists[0].next([run()]); reads[0].result.next(outputRun());
  service.selectRun('r2');
  assert.equal(service.currentRun(), null); assert.equal(service.detailStatus(), 'loading');
  assert.equal(reads[0].result.observed, false);
  reads[0].result.next(outputRun('r1')); assert.equal(service.currentRun(), null);
  reads[1].result.next(outputRun('r2')); assert.equal(service.currentRun()?.id, 'r2');
  service.dispose();
});

test('observation service: system/workspace/principal transitions clear all retained data and increment pin epoch', () => {
  for (const kind of ['system', 'workspace', 'auth'] as const) {
    const { service, lists, reads, workspace, auth } = fixture();
    service.open(); lists[0].next([run()]); reads[0].result.next(outputRun()); service.inspectNode('forecast');
    const before = service.scopeEpoch();
    if (kind === 'system') service.bindSystem('s2'); else (kind === 'workspace' ? workspace : auth).change();
    assert.equal(service.currentRun(), null); assert.equal(service.currentAttempt(), null);
    assert.equal(service.runs().length, 0); assert.equal(service.enabled(), false);
    assert.ok(service.scopeEpoch() > before);
    reads[0].result.next(outputRun()); assert.equal(service.currentRun(), null);
    service.dispose();
  }
});

test('observation service: response fences reject principal changes even without a reset callback', () => {
  const { service, lists, reads, auth } = fixture();
  service.open(); lists[0].next([run()]); auth.silentChange();
  reads[0].result.next(outputRun()); assert.equal(service.currentRun(), null);
  service.dispose();
});

test('observation service: denied/mismatched reads never masquerade as an empty successful Run', () => {
  const { service, lists, reads } = fixture();
  service.open(); lists[0].next([run()]); reads[0].result.error({ status: 403 });
  assert.equal(service.detailStatus(), 'error'); assert.equal(service.detailError(), 'forbidden');
  service.selectRun('r2'); reads[1].result.next(run('r2', { system_id: 'foreign' }));
  assert.equal(service.detailStatus(), 'error'); assert.equal(service.currentRun(), null);
  service.dispose();
});

test('observation service: list failure clears observations and remains retryable', () => {
  const { service, lists } = fixture(); service.open(); lists[0].error({ status: 503 });
  assert.equal(service.listStatus(), 'error'); assert.deepEqual(service.runs(), []);
  service.refresh(); lists[1].next([]);
  assert.equal(service.listStatus(), 'ready'); assert.equal(service.selectedRunId(), null);
  service.dispose();
});

test('observation service: attempts select one retained payload without combining passages', () => {
  const { service, lists, reads } = fixture(); service.open(); lists[0].next([run()]);
  reads[0].result.next(run('r1', { skill_invocations: [
    { id: 'a', status: 'completed', trace: { node_id: 'forecast', passage_id: 'one' }, output_ref: { a: 1 } },
    { id: 'b', status: 'completed', trace: { node_id: 'forecast', passage_id: 'two' }, output_ref: { b: 2 } },
  ] }));
  service.inspectNode('forecast'); assert.equal(service.currentAttempt(), null);
  service.selectAttempt('b'); assert.deepEqual(service.currentAttempt()?.output, { b: 2 });
  service.selectAttempt('foreign'); assert.equal(service.currentAttempt()?.id, 'b');
  service.closeNode(); assert.equal(service.currentNode(), null); assert.equal(service.currentRun()?.id, 'r1');
  service.dispose();
});

test('observation service: latest-node search changes the whole selected Run, never blends outputs', () => {
  const { service, lists, reads, setHandler } = fixture(); service.open();
  lists[0].next([run('recent', { started_at: '2026-10-22T09:00:00Z' }), run('older')]);
  reads[0].result.next(outputRun('recent', 'other'));
  setHandler(id => of(outputRun(id, id === 'recent' ? 'other' : 'forecast')));
  service.findLatestForNode('forecast');
  assert.equal(service.searchStatus(), 'found'); assert.equal(service.selectedRunId(), 'older');
  assert.deepEqual(Object.keys(service.nodes()), ['forecast']);
  assert.equal(service.currentAttempt()?.output?.['result'], 'older');
  service.dispose();
});

test('observation service: latest-node search is bounded and a failed newer read does not certify an older result', () => {
  const { service, lists, reads, setHandler } = fixture(); service.open();
  lists[0].next(Array.from({ length: 15 }, (_, i) => run(`r${String(i).padStart(2, '0')}`)));
  reads[0].result.next(run('r00')); setHandler(id => of(run(id)));
  const before = reads.length; service.findLatestForNode('missing');
  assert.equal(reads.length - before, 10); assert.equal(service.searchStatus(), 'not-found');
  setHandler(() => throwError(() => ({ status: 503 })));
  const beforeFailure = reads.length; service.findLatestForNode('forecast');
  assert.equal(reads.length - beforeFailure, 1); assert.equal(service.searchStatus(), 'error');
  service.dispose();
});

test('observation service: changing node or closing cancels an in-flight search', () => {
  const { service, lists, reads } = fixture(); service.open(); lists[0].next([run()]); reads[0].result.next(run());
  service.findLatestForNode('forecast'); const pending = reads.at(-1)!;
  service.inspectNode('other'); pending.result.next(outputRun());
  assert.equal(service.selectedNodeId(), 'other'); assert.equal(service.searchStatus(), 'idle');
  const before = service.scopeEpoch(); service.close();
  assert.equal(service.currentRun(), null); assert.ok(service.scopeEpoch() > before);
  assert.equal(pending.result.observed, false); service.dispose();
});

test('observation service: superseded loading states settle when another read operation takes over', () => {
  const { service, lists, reads } = fixture(); service.open();
  service.selectRun('r2');
  assert.equal(lists[0].observed, false); assert.equal(service.listStatus(), 'idle');
  service.findLatestForNode('forecast');
  assert.equal(reads[0].result.observed, false); assert.equal(service.detailStatus(), 'idle');
  assert.equal(service.searchStatus(), 'not-found'); service.dispose();
});

test('observation service: revocations retain every held or denied Run even when notifications coalesce', () => {
  const { service, lists, reads, setHandler } = fixture(); service.open();
  lists[0].next([run('r1', { result_held: true }), run('r2', { result_held: true }), run('r3')]);
  assert.deepEqual(service.revocation()?.runIds, ['r1', 'r2']);
  reads[0].result.error({ status: 404 });
  service.selectRun('r3'); reads[1].result.error({ status: 403 });
  assert.deepEqual(service.revocation()?.runIds, ['r1', 'r2', 'r3']);
  assert.ok(service.revocation()!.events['r1'] < service.revocation()!.events['r3'], 'consumers can purge only new events, retaining pins recreated after a successful reauthorization');
  setHandler(id => id === 'r1' ? of(run('r1', { result_held: true })) : throwError(() => ({ status: 404 })));
  service.findLatestForNode('forecast');
  assert.equal(service.searchStatus(), 'error'); assert.equal(service.revocation()?.runId, 'r2');
  service.close(); assert.equal(service.revocation(), null); service.dispose();
});
