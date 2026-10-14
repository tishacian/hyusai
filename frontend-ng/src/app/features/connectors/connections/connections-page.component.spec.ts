import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { Subject, of, throwError } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService, type WorkspaceRequestScope, type WorkspaceContextTransition } from '@app/core/workspace.service';
import { ConnectionsPageComponent } from './connections-page.component';
import type { ConnectionProfile, ConnectionRow } from './connections.models';

const profile: ConnectionProfile = { key: 'postgresql', version: 1, family: 'dbapi', parameters: [], capabilities: { read: true }, certification: 'unverified', driver_status: 'runner_unchecked' };
const row: ConnectionRow = { id: 'conn-a', name: 'ERP', profile_key: 'postgresql', profile_version: 1, revision: 2, values: {}, secret_refs: {}, access: 'read', allowed_schemas: [], allowed_tables: [], certification: 'unverified' };
class WorkspaceStub {
  epoch = 1; currentSlug = () => `workspace-${this.epoch}`; contextEpoch = () => this.epoch;
  resetters = new Set<(value: WorkspaceContextTransition) => void>();
  captureRequestScope(): WorkspaceRequestScope { return { workspaceId: this.currentSlug(), workspaceSlug: this.currentSlug(), epoch: this.epoch }; }
  isRequestScopeCurrent(scope: WorkspaceRequestScope) { return scope.epoch === this.epoch; }
  registerContextReset(reset: (value: WorkspaceContextTransition) => void) { this.resetters.add(reset); return () => this.resetters.delete(reset); }
  switch() { this.resetters.forEach(f => f({ previousSlug: this.currentSlug(), nextSlug: 'workspace-2', previousEpoch: this.epoch, nextEpoch: this.epoch + 1 })); this.epoch++; }
}
function harness() {
  const calls: Array<{ method: string; path: string; body?: any; options?: any }> = [];
  const responses = new Map<string, unknown>([['/connections/profiles', { profiles: [profile] }], ['/connections', { connections: [row], can_configure: true, can_import: true }]]);
  const pending = new Map<string, Subject<any>>(); const failed = new Set<string>(); const workspace = new WorkspaceStub();
  const answer = (path: string) => pending.get(path) ?? (failed.has(path) ? throwError(() => ({ status: 404 })) : of(responses.get(path) ?? {}));
  const api = {
    get(path: string, params: unknown, options: unknown) { calls.push({ method: 'GET', path, options }); return answer(path); },
    post(path: string, body: unknown, options: unknown) { calls.push({ method: 'POST', path, body, options }); return answer(path); },
    put(path: string, body: unknown, options: unknown) { calls.push({ method: 'PUT', path, body, options }); return answer(path); },
    delete(path: string, options: unknown) { calls.push({ method: 'DELETE', path, options }); return answer(path); },
  };
  const injector = Injector.create({ providers: [ConnectionsPageComponent, { provide: ApiService, useValue: api }, { provide: WorkspaceService, useValue: workspace },
    { provide: I18nService, useValue: { t: (key: string) => key } }, { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap({}) } } },
    { provide: Router, useValue: { navigate: async () => true } }] });
  const page = injector.get(ConnectionsPageComponent);
  return { page, calls, responses, pending, failed, workspace, close: () => { page.ngOnDestroy(); injector.destroy(); } };
}
test('multiple connections use the saved revision and workspace scope on update', async () => {
  const h = harness(); try {
    await h.page.load(); h.page.select(row); h.page.name = 'New name'; h.responses.set('/connections/conn-a', { ...row, name: 'New name', revision: 3 });
    await h.page.save(); const sent = h.calls.find(c => c.method === 'PUT')!;
    assert.equal(sent.body.revision, 2); assert.equal(sent.body.profile_key, undefined); assert.equal(sent.options.workspaceSlug, 'workspace-1');
    assert.equal(h.page.selected()?.revision, 3);
  } finally { h.close(); }
});
test('disabled framework does not expose a usable form', async () => {
  const h = harness(); try { h.failed.add('/connections/profiles'); await h.page.load(); assert.equal(h.page.disabled(), true); assert.equal(h.page.canConfigure(), false); } finally { h.close(); }
});
test('late response from a previous workspace cannot repopulate connections or credentials', async () => {
  const h = harness(); try {
    const pending = new Subject<unknown>(); h.pending.set('/connections', pending); const loading = h.page.load();
    h.page.refs = { password: 'secret://workspace/old' }; h.page.writeDataset = 'old-dataset';
    h.workspace.switch(); pending.next({ connections: [row], can_configure: true }); pending.complete(); await loading;
    assert.deepEqual(h.page.connections(), []); assert.deepEqual(h.page.refs, {}); assert.equal(h.page.writeDataset, '');
  } finally { h.close(); }
});
test('diagnostic submits a real asynchronous request and never fabricates a success', async () => {
  const h = harness(); try {
    await h.page.load(); h.page.select(row); h.responses.set('/connections/conn-a/test', { id: 'run-a', connection_id: row.id, operation: 'test', status: 'queued' });
    await h.page.startRun('test'); assert.equal(h.page.run()?.status, 'queued'); assert.equal(h.page.selected()?.certification, 'unverified');
    h.responses.set('/connections/conn-a/runs/run-a', { id: 'run-a', connection_id: row.id, operation: 'test', status: 'failed', error_code: 'CONNECTOR_AUTH_DENIED' });
    await h.page.poll(); assert.equal(h.page.run()?.status, 'failed'); assert.equal(h.page.activeRun(), false);
  } finally { h.close(); }
});
test('delivery approval carries exactly the contract digest being displayed', async () => {
  const h = harness(); try {
    await h.page.load(); h.page.writeContract.set({ id: 'op-a', contract_digest: 'a'.repeat(64), state: 'prepared', preview_ready: true });
    await h.page.writeAction('approve'); const sent = h.calls.find(c => c.path === '/connector-writes/op-a/approve')!;
    assert.deepEqual(sent.body, { contract_digest: 'a'.repeat(64) });
  } finally { h.close(); }
});

test('late write preparation cannot attach an approval to a different connection', async () => {
  const h = harness(); try {
    await h.page.load(); h.page.select({ ...row, access: 'read_write' }); h.page.writeDataset = 'dataset-a';
    const pending = new Subject<any>(); h.pending.set('/connector-writes', pending);
    const preparing = h.page.prepareWrite(); h.page.select({ ...row, id: 'conn-b' });
    pending.next({ id: 'old-operation', contract_digest: 'a'.repeat(64) }); pending.complete(); await preparing;
    assert.equal(h.page.writeContract(), null);
  } finally { h.close(); }
});
test('watch creation is explicit and stays scoped to the selected workspace and connection', async () => {
  const h = harness(); try {
    await h.page.load(); h.page.select(row); h.page.watchSystem = 'system-a'; h.page.prefix = 'approved/'; h.page.watchInterval = 600;
    h.responses.set('/connector-watches', { id: 'watch-a', connection_id: row.id, enabled: true });
    await h.page.createWatch(); const sent = h.calls.find(c => c.path === '/connector-watches' && c.method === 'POST')!;
    assert.deepEqual(sent.body, { connection_id: row.id, system_id: 'system-a', prefix: 'approved/', interval_s: 600 });
    assert.equal(sent.options.workspaceSlug, 'workspace-1'); assert.equal(h.page.watches().length, 1);
    h.workspace.switch(); assert.deepEqual(h.page.watches(), []); assert.equal(h.page.watchSystem, '');
  } finally { h.close(); }
});

test('Iceberg destination pinning preserves an exact int64 snapshot and invalidates old approval', async () => {
  const h = harness(); try {
    await h.page.load(); h.page.select(row); h.page.schema = 'public'; h.page.table = 'scores';
    h.page.writeParameters = '{"keys":["id"]}'; h.page.writeContract.set({ id: 'stale' });
    h.page.run.set({ id: 'read', connection_id: row.id, operation: 'preview', status: 'succeeded', output: { snapshot: { protocol: 'iceberg_rest', table_uuid: 'uuid', snapshot_id: '9223372036854775807', schema_id: 4 } } });
    h.page.useIcebergSnapshot();
    assert.deepEqual(JSON.parse(h.page.writeParameters), { keys: ['id'], schema: 'public', table: 'scores', expected_table_uuid: 'uuid', expected_snapshot_id: '9223372036854775807', expected_schema_id: 4 });
    assert.equal(h.page.writeContract(), null);
  } finally { h.close(); }
});
test('unknown delivery abandonment requires an explicit acknowledgement and a scoped reason', async () => {
  const h = harness(); try {
    await h.page.load(); h.page.select(row); h.page.writeContract.set({ id: 'op-a', contract_digest: 'a'.repeat(64), state: 'unknown' });
    h.page.abandonReason = 'Destination reviewed independently by the owner.';
    await h.page.abandonWrite(); assert.equal(h.calls.filter(c => c.path.endsWith('/abandon')).length, 0);
    h.page.acknowledgePossibleApplication = true;
    h.responses.set('/connector-writes/op-a/abandon', { id: 'op-a', state: 'abandoned' });
    await h.page.abandonWrite();
    const sent = h.calls.find(c => c.path.endsWith('/abandon'))!;
    assert.deepEqual(sent.body, { contract_digest: 'a'.repeat(64), reason: 'Destination reviewed independently by the owner.', acknowledge_possible_application: true });
    assert.equal(sent.options.workspaceSlug, 'workspace-1'); assert.equal(h.page.writeContract()?.['state'], 'abandoned');
    assert.equal(h.page.acknowledgePossibleApplication, false);
  } finally { h.close(); }
});
test('approval stays closed until the server proves the exact preflight succeeded', async () => {
  const h = harness(); try {
    await h.page.load(); h.page.writeContract.set({ id: 'op-a', contract_digest: 'a'.repeat(64), state: 'prepared', preview_ready: false });
    await h.page.writeAction('approve'); assert.equal(h.calls.filter(c => c.path.endsWith('/approve')).length, 0);
  } finally { h.close(); }
});
test('a Flow request can only be resumed on its own selected connection', async () => {
  const h = harness(); try {
    await h.page.load(); h.page.select(row); const id = '00000000-0000-0000-0000-000000000001'; h.page.writeReference = id;
    h.responses.set(`/connector-writes/${id}`, { id, connection_id: 'other', state: 'prepared' });
    await h.page.openWrite(); assert.equal(h.page.writeContract(), null);
    h.responses.set(`/connector-writes/${id}`, { id, connection_id: row.id, state: 'prepared', preview_ready: true });
    await h.page.openWrite(); assert.equal(h.page.writeContract()?.['id'], id);
  } finally { h.close(); }
});
