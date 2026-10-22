import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { signal } from '@angular/core';
import { EndpointsComponent } from './endpoints.component';
import { MLAlertInboxComponent } from './ml-alert-inbox.component';

function harness() {
  let active = true, finish!: (value: any) => void, calls = 0;
  const api = {endpoints: () => new Promise(done => {finish = done;}), alerts: async () => ({items: [], total: 0}),
    channels: async () => ({items: []}), saveChannel: () => {++calls; return new Promise(done => {finish = done;});}};
  const component = Object.assign(Object.create(EndpointsComponent.prototype), {
    generation: 0, destroyed: false, workspace: {captureRequestScope: () => ({}), isRequestScopeCurrent: () => active}, api,
    features: signal({enabled: true, can_manage_channels: true}), items: signal([]), alerts: signal([]), channels: signal([]),
    loading: signal(false), saving: signal(false), error: signal(false), total: signal(0), offset: signal(0),
    scope: 'workspace', systemId: '', channelName: 'name', channelKind: 'email', email: 'test@example.invalid', urlRef: '', keyRef: '',
  }) as any;
  return {component, api, switchWorkspace: () => {active = false;}, resolve: (value: any) => finish(value), calls: () => calls};
}

test('endpoints never adopt an old workspace response', async () => {
  const h = harness(); const pending = h.component.reload(); h.switchWorkspace();
  h.resolve({items: [{id: 'private-old-model'}], total: 1}); await pending;
  assert.deepEqual(h.component.items(), []); assert.equal(h.component.total(), 0);
});

test('channel creation ignores late responses and prevents double submission', async () => {
  const h = harness(); const pending = h.component.createChannel(); await h.component.createChannel();
  assert.equal(h.calls(), 1); h.switchWorkspace(); h.resolve({id: 'old-channel'}); await pending;
  assert.equal(h.component.channelName, 'name'); assert.deepEqual(h.component.channels(), []);
});

test('read-only endpoint users cannot submit channel mutations', async () => {
  const h = harness(); h.component.features.set({enabled: true, can_manage_channels: false});
  await h.component.createChannel(); await h.component.toggle({id: 'one'}); await h.component.acknowledge('alert');
  assert.equal(h.calls(), 0);
});

test('Hypervisor inbox discards alerts after a workspace switch', async () => {
  let active = true, finish!: (value: any) => void;
  const component = Object.assign(Object.create(MLAlertInboxComponent.prototype), {
    destroyed: false, workspace: {captureRequestScope: () => ({}), isRequestScopeCurrent: () => active},
    api: {features: async () => ({enabled: true}), alerts: () => new Promise(done => {finish = done;})},
    generation: 0, systemId: () => null, alertsEnabled: signal(false), loading: signal(false), expanded: signal(null),
    enabled: signal(false), failed: signal(false), total: signal(0), items: signal([]),
  }) as any;
  const pending = component.ngOnInit(); await Promise.resolve(); active = false;
  finish({items: [{id: 'old-private-alert'}], total: 1}); await pending;
  assert.deepEqual(component.items(), []); assert.equal(component.total(), 0);
});
