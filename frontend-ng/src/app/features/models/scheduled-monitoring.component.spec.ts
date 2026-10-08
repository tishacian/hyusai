import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { signal } from '@angular/core';
import { ScheduledMonitoringComponent } from './scheduled-monitoring.component';
import type { MonitoringReport } from './models.vm';

function harness(canConfigure = true) {
  let active = true, resolve!: (report: MonitoringReport) => void;
  const changed: MonitoringReport[] = [], requests: unknown[] = [];
  const component = Object.assign(Object.create(ScheduledMonitoringComponent.prototype), {
    modelId: () => 'v1', generation: 0, busy: signal(false), saved: signal(false), error: signal(''), forbidden: signal(false),
    editable: () => canConfigure, config: () => ({ enabled: true, propose_retraining: true, interval_minutes: 60 }),
    workspace: { captureRequestScope: () => 'workspace', isRequestScopeCurrent: () => active },
    changed: { emit: (report: MonitoringReport) => changed.push(report) },
    models: { configureMonitoringPolicy: (id: string, config: unknown) => { requests.push({ id, config }); return new Promise<MonitoringReport>(done => { resolve = done; }); } },
  }) as ScheduledMonitoringComponent;
  return { component, requests, changed, complete: () => resolve({ scheduled: { policy: { enabled: true } } } as MonitoringReport), switchWorkspace: () => { active = false; } };
}

test('read-only users cannot submit, and an in-flight save cannot submit twice', async () => {
  const readOnly = harness(false); await readOnly.component.save(); assert.equal(readOnly.requests.length, 0);
  const edit = harness(); const first = edit.component.save(); await edit.component.save();
  assert.equal(edit.requests.length, 1); assert.equal(edit.changed.length, 0);
  edit.complete(); await first; assert.equal(edit.changed.length, 1); assert.equal(edit.component.saved(), true);
});

test('a settings response from a previous workspace cannot update the card', async () => {
  const h = harness(); const request = h.component.save(); h.switchWorkspace(); h.complete(); await request;
  assert.equal(h.changed.length, 0); assert.equal(h.component.saved(), false);
});
