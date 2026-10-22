import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { signal } from '@angular/core';
import { MLAlertInboxComponent } from './ml-alert-inbox.component';

function harness() {
  let currentSystem: string | null = null;
  let workspace = 'one';
  const calls: Array<[string, string]> = [];
  const api = {
    features: async () => ({enabled: true, alerts_enabled: false}),
    alerts: async (scope: string, id: string): Promise<any> => {calls.push([scope, id]); return {items: [], total: 0};},
  };
  const component = Object.assign(Object.create(MLAlertInboxComponent.prototype), {
    initialized: false, generation: 0, destroyed: false, api,
    workspace: {captureRequestScope: () => workspace, isRequestScopeCurrent: (scope: string) => scope === workspace},
    systemId: () => currentSystem, enabled: signal(false), alertsEnabled: signal(false), loading: signal(false),
    failed: signal(false), total: signal(0), items: signal([]), expanded: signal(null),
  }) as any;
  return {component, api, calls, system: (id: string | null) => {currentSystem = id;}, workspace: (id: string) => {workspace = id;}};
}

test('disabled ML operations does not fetch or retain an alert inbox', async () => {
  const h = harness();
  h.component.items.set([{id: 'old-alert'}]);
  h.api.features = async () => ({enabled: false, alerts_enabled: false});
  await h.component.ngOnInit();
  assert.equal(h.component.enabled(), false);
  assert.equal(h.component.loading(), false);
  assert.equal(h.component.failed(), false);
  assert.deepEqual(h.component.items(), []);
  assert.deepEqual(h.calls, []);
});

test('historical alerts remain readable while new alert delivery is disabled', async () => {
  const h = harness();
  await h.component.ngOnInit();
  assert.equal(h.component.enabled(), true);
  assert.equal(h.component.alertsEnabled(), false);
  assert.deepEqual(h.calls, [['workspace', '']]);
});

test('explicit system scope uses the API relation and rejects the previous scope response', async () => {
  const h = harness();
  let finish!: (value: any) => void;
  h.api.alerts = async (scope, id) => {h.calls.push([scope, id]); return new Promise(done => {finish = done;});};
  h.system('system-one');
  const pending = h.component.ngOnInit();
  await Promise.resolve();
  h.system('system-two');
  finish({items: [{id: 'first-system-alert'}], total: 1});
  await pending;
  assert.deepEqual(h.calls, [['system', 'system-one']]);
  assert.deepEqual(h.component.items(), []);
  assert.equal(h.component.total(), 0);
});

test('latest refresh wins when requests resolve out of order', async () => {
  const h = harness();
  const finish: Array<(value: any) => void> = [];
  h.api.alerts = async () => new Promise(done => {finish.push(done);});
  const first = h.component.reload();
  await Promise.resolve();
  const second = h.component.reload();
  await Promise.resolve();
  finish[1]({items: [{id: 'latest'}], total: 1});
  await second;
  finish[0]({items: [{id: 'stale'}], total: 10});
  await first;
  assert.deepEqual(h.component.items(), [{id: 'latest'}]);
  assert.equal(h.component.total(), 1);
  assert.equal(h.component.loading(), false);
});

test('failed or forbidden alert reads remain unavailable instead of an empty success', async () => {
  const h = harness();
  h.api.alerts = async () => {throw new Error('forbidden');};
  await h.component.ngOnInit();
  assert.equal(h.component.failed(), true);
  assert.equal(h.component.loading(), false);
  assert.deepEqual(h.component.items(), []);
});
