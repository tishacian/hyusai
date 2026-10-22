import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { WorkspaceFetchService, type WorkspaceFetchInit } from '@app/core/workspace-fetch.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { FlowObservationDatasetService, flowObservationDatasetReference, type FlowObservationDatasetSelection } from './flow-observation-dataset.service';

function selection(runId = 'run-A', nodeId = 'forecast', attemptId = 'call-A', output: Record<string, unknown> = { dataset_id: 'dataset-A', version: 3 }): FlowObservationDatasetSelection {
  const invocation: any = { id: attemptId, status: 'completed', skill_slug: 'ml_forecast_v1', trace: { node_id: nodeId }, output_ref: output };
  return {
    run: { id: runId, system_id: 'system-A', status: 'completed', skill_invocations: [invocation] }, nodeId,
    attempt: { id: attemptId, nodeId, passageId: 'passage-A', attemptIndex: null, iteration: null,
      skillSlug: 'ml_forecast_v1', status: 'completed', startedAt: null, completedAt: null, latencyMs: null,
      input: {}, output, outputState: 'available', invocation },
  };
}
function harness(fetch?: (path: string, init: WorkspaceFetchInit) => Promise<Response>) {
  let workspaceEpoch = 1, authEpoch = 1;
  const workspaceReset = new Set<() => void>(), authReset = new Set<() => void>();
  const calls: Array<{ path: string; init: WorkspaceFetchInit }> = [];
  const injector = Injector.create({ providers: [FlowObservationDatasetService,
    { provide: WorkspaceFetchService, useValue: { fetch: async (path: string, init: WorkspaceFetchInit) => {
      calls.push({ path, init });
      return fetch ? fetch(path, init) : path.includes('/preview?')
        ? Response.json({ dataset_id: 'dataset-A', schema: [{ name: 'pred', kind: 'float' }], rows: [{ pred: 42 }], offset: 0, limit: 50, total: 121 })
        : Response.json({ dataset: { id: 'dataset-A', version: 3, status: 'ready', name: 'Forecast', run_id: 'producer-A', node_id: 'producer-node' } });
    } } },
    { provide: WorkspaceService, useValue: {
      captureRequestScope: () => ({ workspaceSlug: 'workspace-A', epoch: workspaceEpoch }),
      isRequestScopeCurrent: (scope: any) => scope.epoch === workspaceEpoch,
      registerContextReset: (callback: () => void) => { workspaceReset.add(callback); return () => workspaceReset.delete(callback); },
    } },
    { provide: AuthStore, useValue: {
      captureRequestScope: () => ({ epoch: authEpoch }), isRequestScopeCurrent: (scope: any) => scope.epoch === authEpoch,
      registerContextReset: (callback: () => void) => { authReset.add(callback); return () => authReset.delete(callback); },
    } },
  ] });
  return { service: injector.get(FlowObservationDatasetService), calls,
    switchWorkspace: () => { workspaceReset.forEach(reset => reset()); workspaceEpoch++; },
    switchPrincipal: () => { authReset.forEach(reset => reset()); authEpoch++; },
    destroy: () => injector.destroy() };
}

test('dataset selection performs no IO; explicit preview verifies an immutable version and bounded rows', async () => {
  const h = harness(); h.service.setSelection(selection());
  assert.equal(h.service.available(), true); assert.deepEqual(h.calls, []);
  await h.service.load();
  assert.equal(h.service.status(), 'ready'); assert.equal(h.calls.length, 2);
  assert.equal(h.calls[0].path, '/api/v1/datasets/dataset-A');
  assert.equal(h.calls[1].path, '/api/v1/datasets/dataset-A/preview?offset=0&limit=50');
  for (const call of h.calls) {
    assert.equal(call.init.method, 'GET'); assert.equal(call.init.body, undefined);
    assert.equal(call.init.workspaceSlug, 'workspace-A'); assert.equal(call.init.cache, 'no-store');
  }
  assert.deepEqual(h.service.preview()?.rows, [{ pred: 42 }]);
  assert.equal(h.service.preview()?.total_rows, 121); assert.equal(h.service.preview()?.truncated, true);
  assert.deepEqual(h.service.preview()?.provenance, {
    dataset_id: 'dataset-A', dataset_version: 3, dataset_name: 'Forecast', immutable: true,
    observed_run_id: 'run-A', observed_node_id: 'forecast', observed_invocation_id: 'call-A',
    producer_run_id: 'producer-A', producer_node_id: 'producer-node', offset: 0, limit: 50, first_row: 1, last_row: 1,
  }); h.destroy();
});

test('held, unavailable, uncorrelated and unpinned references cannot cause a dataset read', async () => {
  const values = [selection(), selection(), selection(), selection(), selection(), selection('A', 'n', 'i', { dataset_slug: 'latest-forecast' })];
  values[0].run.result_held = true;
  values[1].attempt!.outputState = 'missing';
  values[2].attempt!.outputState = 'pending';
  values[3].attempt!.nodeId = 'different-node';
  values[4].run.skill_invocations = [];
  for (const selected of values) {
    const h = harness(); h.service.setSelection(selected); await h.service.load();
    assert.equal(h.service.available(), false); assert.deepEqual(h.calls, []); assert.equal(h.service.preview(), null); h.destroy();
  }
  assert.equal(flowObservationDatasetReference({ model_id: 'dataset-A' }), null);
  assert.equal(flowObservationDatasetReference({ dataset_id: 'A', dataset: { id: 'B' } }), null);
  assert.equal(flowObservationDatasetReference({ dataset_id: 'A', dataset_version: 3, dataset: { id: 'A', version: 4 } }), null);
  assert.equal(flowObservationDatasetReference({ dataset_id: 'A', dataset_version: 'latest' }), null);
  assert.deepEqual(flowObservationDatasetReference({ dataset: { id: 'A', version: 4 } }), { datasetId: 'A', version: 4 });
});

test('foreign dataset identity, version mismatch and non-ready datasets stop before reading bytes', async () => {
  for (const metadata of [{ id: 'other', version: 3, status: 'ready' }, { id: 'dataset-A', version: 4, status: 'ready' }, { id: 'dataset-A', version: 3, status: 'pending' }]) {
    const h = harness(async () => Response.json({ dataset: metadata })); h.service.setSelection(selection()); await h.service.load();
    assert.equal(h.calls.length, 1); assert.equal(h.service.status(), 'error'); assert.equal(h.service.preview(), null); h.destroy();
  }
});

test('an immutable id without a recorded version may use its verified metadata, never latest resolution', async () => {
  const h = harness(); h.service.setSelection(selection('run-A', 'forecast', 'call-A', { dataset_id: 'dataset-A' }));
  await h.service.load(); assert.equal(h.service.preview()?.provenance?.['dataset_version'], 3);
  assert.equal(h.service.reference()?.version, null); assert.equal(h.service.status(), 'ready'); h.destroy();
});

test('workspace, principal, Run, node and attempt changes discard a late preview and clear retained rows', async () => {
  for (const change of ['workspace', 'principal', 'run', 'node', 'attempt', 'held', 'closed', 'destroyed']) {
    let finish!: (value: Response) => void;
    const h = harness(async path => path.includes('/preview?') ? new Promise(resolve => { finish = resolve; })
      : Response.json({ dataset: { id: 'dataset-A', version: 3, status: 'ready' } }));
    h.service.setSelection(selection()); const promise = h.service.load();
    for (let turns = 0; turns < 12 && !finish; turns++) await Promise.resolve();
    assert.ok(finish, 'preview read reached');
    if (change === 'workspace') h.switchWorkspace();
    else if (change === 'principal') h.switchPrincipal();
    else if (change === 'closed') h.service.setSelection(null);
    else if (change === 'destroyed') h.destroy();
    else if (change === 'held') { const held = selection(); held.run.result_held = true; h.service.setSelection(held); }
    else h.service.setSelection(selection(change === 'run' ? 'run-B' : 'run-A', change === 'node' ? 'node-B' : 'forecast', change === 'attempt' ? 'call-B' : 'call-A'));
    finish(Response.json({ dataset_id: 'dataset-A', rows: [{ secret: 'old scope' }], schema: [], offset: 0, limit: 50, total: 1 }));
    await promise;
    assert.equal(h.service.preview(), null); assert.notEqual(h.service.status(), 'ready');
    assert.equal(h.calls[1].init.signal?.aborted, true);
    if (change !== 'destroyed') h.destroy();
  }
});

test('denial and malformed preview are errors, not successful empty data', async () => {
  for (const code of [403, 404, 409]) {
    const h = harness(async () => Response.json({ detail: 'unavailable' }, { status: code }));
    h.service.setSelection(selection()); await h.service.load();
    assert.equal(h.service.error(), code === 403 ? 'forbidden' : code === 404 ? 'missing' : 'not-ready');
    assert.equal(h.service.preview(), null); h.destroy();
  }
  for (const page of [
    { dataset_id: 'other', rows: [], schema: [], offset: 0, limit: 50, total: 0 },
    { dataset_id: 'dataset-A', rows: [{ value: 1 }], schema: [], offset: 0, limit: 50, total: 0 },
    { dataset_id: 'dataset-A', rows: [], schema: [], offset: 2, limit: 50, total: 0 },
  ]) {
    const h = harness(async path => Response.json(path.includes('/preview?') ? page : { dataset: { id: 'dataset-A', version: 3, status: 'ready' } }));
    h.service.setSelection(selection()); await h.service.load();
    assert.equal(h.service.status(), 'error'); assert.equal(h.service.preview(), null); h.destroy();
  }
});
