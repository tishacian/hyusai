import assert from 'node:assert/strict';
import { test } from 'node:test';
import { newPrepDraft, type PrepExecution } from './dataops.models';
import {
  clearStoredDraft, executionIdFromQuery, plannedOutputKind, prepIsActive, prepPhase, preparedOutputs,
  readStoredDraft, sampleSize, writeStoredDraft,
} from './data-preparation.vm';

const run = (over: Partial<PrepExecution>): PrepExecution => ({ id: 'exec-1', status: 'running', ...over });

class MemoryStorage implements Storage {
  private data = new Map<string, string>();
  get length(): number { return this.data.size; }
  clear(): void { this.data.clear(); }
  getItem(key: string): string | null { return this.data.get(key) ?? null; }
  key(index: number): string | null { return [...this.data.keys()][index] ?? null; }
  removeItem(key: string): void { this.data.delete(key); }
  setItem(key: string, value: string): void { this.data.set(key, value); }
}

test('a cancel asked for stays requested while the server still runs the execution', () => {
  assert.equal(prepPhase(run({ cancel_requested: true })), 'cancel_requested');
  assert.equal(prepIsActive(run({ cancel_requested: true })), true);
  assert.equal(prepPhase(run({ status: 'cancelled', cancel_requested: true })), 'cancelled');
  assert.equal(prepIsActive(run({ status: 'cancelled' })), false);
});

test('a cancelled or failed execution is never ready, even with an output envelope', () => {
  const output_json = { outputs: { out: { dataset_id: 'ds-1', version: 1, name: 'Orders' } } };
  assert.deepEqual(preparedOutputs(run({ status: 'cancelled', output_json })), []);
  assert.deepEqual(preparedOutputs(run({ status: 'failed', output_json })), []);
  assert.equal(prepPhase(run({ status: 'failed' })), 'failed');
  assert.equal(prepPhase(run({ status: 'timed_out' })), 'timed_out');
});

test('a succeeded execution without a returned dataset is incomplete', () => {
  assert.equal(prepPhase(run({ status: 'succeeded', output_json: null })), 'incomplete');
  assert.equal(prepPhase(run({ status: 'succeeded', output_json: { outputs: { out: { name: 'x' } } } })), 'incomplete');
});

test('the output says whether it created a dataset or a version', () => {
  const execution = run({ status: 'succeeded', output_json: { outputs: {
    out: { dataset_id: 'ds-1', version: 1, name: 'Orders' },
    test: { dataset_id: 'ds-2', version: 4, name: 'Orders test' },
  } } });
  assert.equal(prepPhase(execution), 'succeeded');
  assert.deepEqual(preparedOutputs(execution).map((o) => [o.port, o.kind, o.version]), [['out', 'dataset', 1], ['test', 'version', 4]]);
});

test('the planned output follows the draft before any run', () => {
  const draft = newPrepDraft();
  assert.equal(plannedOutputKind(draft.spec, 'out'), 'dataset');
  draft.spec.outputs[0].append_version_of = 'ds-9';
  assert.equal(plannedOutputKind(draft.spec, 'out'), 'version');
});

test('the sample size is the server figure, or unknown', () => {
  assert.equal(sampleSize(null), null);
  assert.deepEqual(sampleSize({ rows: [], schema: [], sample: true, sample_info: { rows: 5000, of_rows: 120000, version: {} } }), { rows: 5000, of: 120000 });
  assert.equal(sampleSize({ rows: [], schema: [], sample: true }), null);
});

test('the draft is kept per workspace in the session and survives a reload', () => {
  const storage = new MemoryStorage();
  const draft = newPrepDraft(); draft.spec.outputs[0].name = 'orders_clean';
  assert.equal(writeStoredDraft(storage, 'ws-a', draft, 1000), true);
  assert.equal(readStoredDraft(storage, 'ws-b'), null);
  assert.deepEqual(readStoredDraft(storage, 'ws-a'), { draft, savedAt: 1000 });
  clearStoredDraft(storage, 'ws-a');
  assert.equal(readStoredDraft(storage, 'ws-a'), null);
});

test('a corrupt or blocked storage never breaks the page', () => {
  const storage = new MemoryStorage();
  storage.setItem('agentium.dataprep.draft.ws-a', '{not json');
  assert.equal(readStoredDraft(storage, 'ws-a'), null);
  storage.setItem('agentium.dataprep.draft.ws-a', JSON.stringify({ draft: { spec: {} } }));
  assert.equal(readStoredDraft(storage, 'ws-a'), null);
  const blocked = { setItem() { throw new Error('quota'); }, getItem() { throw new Error('denied'); } } as unknown as Storage;
  assert.equal(writeStoredDraft(blocked, 'ws-a', newPrepDraft()), false);
  assert.equal(readStoredDraft(blocked, 'ws-a'), null);
  assert.equal(readStoredDraft(null, 'ws-a'), null);
});

test('only a server id is read from the URL', () => {
  assert.equal(executionIdFromQuery('3f2a9c1e-5b7d'), '3f2a9c1e-5b7d');
  assert.equal(executionIdFromQuery('../x'), null);
  assert.equal(executionIdFromQuery(null), null);
});
