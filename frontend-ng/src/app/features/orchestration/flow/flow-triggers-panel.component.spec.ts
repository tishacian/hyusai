import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  Injector, runInInjectionContext, signal,
  ɵChangeDetectionScheduler as ChangeDetectionScheduler,
  ɵEffectScheduler as EffectScheduler,
} from '@angular/core';
import { Subject, of } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { FLOW_EN, FLOW_FR } from '@app/core/i18n/flow.dict';
import { FlowTriggersPanelComponent } from './flow-triggers-panel.component';
import { scheduleInstant } from './flow-triggers.vm';

function harness() {
  const posts: Array<{ path: string; body: Record<string, unknown>; response: Subject<any> }> = [];
  const system = signal('system-one');
  const injector = Injector.create({ providers: [
    { provide: ApiService, useValue: {
      get: () => of({ schedules: [], hooks: [] }),
      post: (path: string, body: Record<string, unknown>) => {
        const response = new Subject<any>();
        posts.push({ path, body, response });
        return response;
      },
    } },
    { provide: ToastrService, useValue: { success() {}, error() {} } },
    { provide: I18nService, useValue: { locale: () => 'en', t: (key: string) => (FLOW_EN as Record<string, string>)[key] ?? key } },
    { provide: ChangeDetectionScheduler, useValue: { notify() {}, runningTick: false } },
    { provide: EffectScheduler, useValue: { add() {}, schedule() {}, flush() {}, remove() {} } },
  ] });
  const component = runInInjectionContext(injector, () => new FlowTriggersPanelComponent());
  Object.defineProperty(component, 'systemId', { value: system });
  return { component, posts, system, injector };
}

test('schedule setup preserves business inputs and time zone without starting recurring work', () => {
  const h = harness();
  try {
    h.component.newSchedName = 'Queue refresh';
    h.component.newSchedCron = '0 9 * * 1-5';
    h.component.newSchedTimezone = 'Europe/Paris';
    h.component.newSchedPayload = '{"queue":"priority","limit":25}';
    h.component.createSchedule();
    h.component.createSchedule();
    assert.equal(h.posts.length, 1, 'in-flight save cannot be submitted twice');
    assert.deepEqual(h.posts[0].body, {
      name: 'Queue refresh', cron_expr: '0 9 * * 1-5', timezone: 'Europe/Paris',
      input_payload: { queue: 'priority', limit: 25 }, enabled: false,
    });
    h.posts[0].response.next({ id: 's1', ...h.posts[0].body });
    assert.equal(h.component.schedules()[0].enabled, false);
  } finally { h.injector.destroy(); }
});

test('malformed or non-object JSON and unknown time zones give a recoverable form error', () => {
  const h = harness();
  try {
    for (const input of ['[1]', 'null', '{', '"data"']) {
      h.component.newSchedPayload = input;
      h.component.createSchedule();
      assert.equal(h.component.scheduleError(), 'flow.triggers.schedules.payload_invalid');
    }
    h.component.newSchedPayload = '{}';
    h.component.newSchedTimezone = 'Mars/Olympus';
    h.component.createSchedule();
    assert.equal(h.component.scheduleError(), 'flow.triggers.schedules.timezone_invalid');
    assert.equal(h.posts.length, 0);
    h.component.newSchedTimezone = 'UTC';
    h.component.createSchedule();
    h.posts[0].response.error({ status: 400 });
    assert.equal(h.component.scheduleError(), 'flow.triggers.schedules.cron_invalid');
    assert.equal(h.component.busy(), false);
  } finally { h.injector.destroy(); }
});

test('new webhook stays paused until the signing secret has been installed', () => {
  const h = harness();
  try {
    h.component.createHook();
    assert.deepEqual(h.posts[0].body, { name: 'Inbound event', event_type: 'webhook.received', enabled: false });
    h.posts[0].response.next({ id: 'h1', ...h.posts[0].body, secret: 'one-time-test-secret' });
    assert.equal(h.component.lastSecret(), 'one-time-test-secret');
    assert.equal(h.component.hooks()[0].enabled, false);
  } finally { h.injector.destroy(); }
});

test('a previous System response cannot reveal its webhook secret on the new System', () => {
  const h = harness();
  try {
    h.component.createHook();
    h.system.set('system-two');
    h.posts[0].response.next({ id: 'h1', secret: 'other-system-secret' });
    assert.equal(h.component.lastSecret(), null);
    assert.deepEqual(h.component.hooks(), []);
  } finally { h.injector.destroy(); }
});

test('leaving the inspector cancels pending setup subscriptions', () => {
  const h = harness();
  h.component.createHook();
  h.injector.destroy();
  h.posts[0].response.next({ id: 'h1', secret: 'late-secret' });
  assert.equal(h.component.lastSecret(), null);
});

test('UTC-naive API instants display in the schedule zone including daylight saving', () => {
  assert.equal(scheduleInstant('2026-10-17T07:00:00', 'en-GB', 'Europe/Paris'), '17 Oct 2026, 09:00');
  assert.equal(scheduleInstant('2026-11-17T07:00:00Z', 'en-GB', 'Europe/Paris'), '17 Nov 2026, 08:00');
  assert.equal(scheduleInstant('invalid', 'en-GB', 'UTC'), '—');
});

test('trigger safety and recovery guidance is available in both languages', () => {
  for (const key of [
    'flow.triggers.schedules.execution_note', 'flow.triggers.schedules.payload_invalid',
    'flow.triggers.schedules.timezone_invalid', 'flow.triggers.schedules.cron_invalid',
    'flow.triggers.webhooks.delivery_note', 'flow.triggers.webhooks.signature_note', 'flow.triggers.save_paused',
  ]) {
    assert.ok((FLOW_FR as Record<string, string>)[key]);
    assert.ok((FLOW_EN as Record<string, string>)[key]);
  }
});
