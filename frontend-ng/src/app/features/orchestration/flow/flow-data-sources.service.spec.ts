import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { Subject } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { FlowCollectionsService } from './flow-collections.service';
import { FlowDataSourcesService } from './flow-data-sources.service';

function harness() {
  let epoch = 1;
  let reset = (_transition: any) => {};
  const responses: Subject<any>[] = [];
  const api = { get: () => { const response = new Subject<any>(); responses.push(response); return response.asObservable(); } };
  const workspace = {
    captureRequestScope: () => ({ epoch }), isRequestScopeCurrent: (scope: any) => scope.epoch === epoch,
    contextEpoch: () => epoch, registerContextReset: (callback: any) => { reset = callback; return () => {}; },
  };
  const collections = { collections: signal(['luma-regles']), state: signal('loaded'), ensureLoaded: () => {}, retry: () => {} };
  const injector = Injector.create({ providers: [FlowDataSourcesService,
    { provide: ApiService, useValue: api }, { provide: WorkspaceService, useValue: workspace },
    { provide: FlowCollectionsService, useValue: collections }] });
  return { service: injector.get(FlowDataSourcesService), responses,
    switch: () => { epoch++; collections.collections.set([]); reset({ nextEpoch: epoch }); }, destroy: () => injector.destroy() };
}

test('source catalogue strips credentials and separates saved configuration from inspection rights', () => {
  const h = harness();
  h.responses[0].next({ can_configure: false, connectors: [{ id: 'postgresql', configured: true,
    values: { database: 'Luma', username: 'reader', password: 'do-not-copy' }, secrets: { password: 'do-not-copy' } }] });
  assert.equal(h.service.canInspect(), false);
  assert.deepEqual(h.service.connectors(), [{ id: 'postgresql', configured: true, values: { database: 'Luma' } }]);
  assert.equal(h.service.items().length, 2);
  assert.equal(JSON.stringify(h.service.items()).includes('do-not-copy'), false); h.destroy();
});

test('workspace reset removes references and rejects a late response from the previous tenant', async () => {
  const h = harness();
  h.responses[0].next({ can_configure: true, connectors: [{ id: 'postgresql', configured: true, values: { database: 'old-tenant' } }] });
  h.switch();
  assert.deepEqual(h.service.connectors(), []); assert.equal(h.service.canInspect(), false);
  h.responses[0].next({ can_configure: true, connectors: [{ id: 'postgresql', configured: true, values: { database: 'late-old-tenant' } }] });
  await Promise.resolve();
  h.responses[1].next({ can_configure: false, connectors: [] });
  assert.deepEqual(h.service.items(), []); assert.equal(h.service.canInspect(), false); h.destroy();
});

test('a failed catalogue is explicit and does not invent configured sources', () => {
  const h = harness(); h.responses[0].error(new Error('offline'));
  assert.equal(h.service.state(), 'error'); assert.deepEqual(h.service.connectors(), []);
  assert.equal(h.service.items()[0].label, 'luma-regles'); h.destroy();
});
