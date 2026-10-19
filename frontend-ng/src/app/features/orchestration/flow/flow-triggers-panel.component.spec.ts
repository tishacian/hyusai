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
  const patches: Array<{ path: string; body: Record<string, unknown>; response: Subject<any> }> = [];
  const system = signal('system-one');
  const kind = signal<'schedule' | 'webhook'>('schedule');
  const errors: string[] = [];
  const injector = Injector.create({ providers: [
    { provide: ApiService, useValue: {
      get: () => of({ schedules: [], hooks: [] }),
      post: (path: string, body: Record<string, unknown>) => {
        const response = new Subject<any>();
        posts.push({ path, body, response });
        return response;
      },
      patch: (path: string, body: Record<string, unknown>) => {
        const response = new Subject<any>();
        patches.push({ path, body, response });
        return response;
      },
    } },
    { provide: ToastrService, useValue: { success() {}, error(message: string) { errors.push(message); } } },
    { provide: I18nService, useValue: { locale: () => 'en', t: (key: string) => (FLOW_EN as Record<string, string>)[key] ?? key } },
    { provide: ChangeDetectionScheduler, useValue: { notify() {}, runningTick: false } },
    { provide: EffectScheduler, useValue: { add() {}, schedule() {}, flush() {}, remove() {} } },
  ] });
  const component = runInInjectionContext(injector, () => new FlowTriggersPanelComponent());
  Object.defineProperty(component, 'systemId', { value: system });
  Object.defineProperty(component, 'kind', { value: kind });
  return { component, posts, patches, system, kind, errors, injector };
}

const delegatedIdentity = {
  kind: 'delegated_user' as const,
  user_id: 'user-one',
  display_name: 'Camille',
  granted_at: '2026-10-19T12:00:00Z',
};
const schedule = {
  id: 'schedule-one', name: 'Daily check', cron_expr: '0 9 * * *', timezone: 'UTC',
  enabled: false, execution_identity: null,
};
const hook = {
  id: 'hook-one', name: 'Inbound event', event_type: 'webhook.received', enabled: false,
  execution_identity: null,
};

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

test('delegation is opt-in for both new trigger kinds and consent resets after saving', () => {
  for (const kind of ['schedule', 'webhook'] as const) {
    const h = harness();
    try {
      h.kind.set(kind);
      assert.equal(h.component.newSchedUseMyAccess, false);
      assert.equal(h.component.newHookUseMyAccess, false);
      if (kind === 'schedule') {
        h.component.newSchedUseMyAccess = true;
        h.component.createSchedule();
      } else {
        h.component.newHookUseMyAccess = true;
        h.component.createHook();
      }
      assert.equal(h.posts[0].body['execution_identity'], 'current_user');
      assert.equal(h.posts[0].body['enabled'], false);
      assert.equal('user_id' in h.posts[0].body, false, 'the client cannot choose another user');
      h.posts[0].response.next({
        ...(kind === 'schedule' ? schedule : hook), execution_identity: delegatedIdentity,
      });
      assert.equal(h.component.newSchedUseMyAccess, false);
      assert.equal(h.component.newHookUseMyAccess, false);
      const rows = kind === 'schedule' ? h.component.schedules() : h.component.hooks();
      assert.deepEqual(rows[0].execution_identity, delegatedIdentity);
    } finally { h.injector.destroy(); }
  }
});

test('assigning and removing execution access do not activate or reconfigure the trigger', () => {
  for (const kind of ['schedule', 'webhook'] as const) {
    const h = harness();
    try {
      h.kind.set(kind);
      h.component.schedules.set([schedule]);
      h.component.hooks.set([hook]);
      const id = kind === 'schedule' ? schedule.id : hook.id;
      const assign = () => kind === 'schedule'
        ? h.component.setScheduleIdentity(schedule, 'current_user')
        : h.component.setHookIdentity(hook, 'current_user');
      assign();
      assign();
      assert.equal(h.patches.length, 1, 'busy controls prevent duplicate consent requests');
      assert.deepEqual(h.patches[0].body, { execution_identity: 'current_user' });
      assert.equal(h.patches[0].path, `/systems/system-one/${kind === 'schedule' ? 'schedules' : 'hooks'}/${id}`);
      assert.equal(h.component.identityPending(), id);
      const saved = { ...(kind === 'schedule' ? schedule : hook), execution_identity: delegatedIdentity };
      h.patches[0].response.next(saved);
      assert.equal(h.component.busy(), false);
      assert.equal(h.component.identityPending(), null);
      if (kind === 'schedule') h.component.setScheduleIdentity(h.component.schedules()[0], 'none');
      else h.component.setHookIdentity(h.component.hooks()[0], 'none');
      assert.deepEqual(h.patches[1].body, { execution_identity: 'none' });
      h.patches[1].response.next({ ...saved, execution_identity: null });
      const rows = kind === 'schedule' ? h.component.schedules() : h.component.hooks();
      assert.equal(rows[0].execution_identity, null);
      assert.equal(rows[0].enabled, false);
    } finally { h.injector.destroy(); }
  }
});

test('a refused delegation keeps the recorded identity and offers a retry with safe guidance', () => {
  const h = harness();
  try {
    const saved = { ...schedule, execution_identity: delegatedIdentity };
    h.component.schedules.set([saved]);
    h.component.setScheduleIdentity(saved, 'none');
    h.patches[0].response.error({ status: 403, error: { detail: 'private server detail' } });
    assert.deepEqual(h.component.schedules()[0].execution_identity, delegatedIdentity);
    assert.equal(h.component.busy(), false);
    assert.equal(h.component.identityPending(), null);
    assert.deepEqual(h.component.identityError(), { id: schedule.id, key: 'flow.triggers.identity.forbidden' });
    h.component.setScheduleIdentity(saved, 'none');
    assert.equal(h.component.identityError(), null);
    h.patches[1].response.error({ status: 409 });
    assert.equal(h.component.identityError()?.key, 'flow.triggers.identity.update_failed');
  } finally { h.injector.destroy(); }
});

test('publication refusals explain publishing or renewed consent instead of generic permission failure', () => {
  for (const [code, key] of [
    ['EXECUTION_PRINCIPAL_PUBLICATION_CHANGED', 'flow.triggers.identity.publication_changed'],
    ['EXECUTION_PRINCIPAL_PUBLICATION_REQUIRED', 'flow.triggers.identity.publication_required'],
  ]) {
    const h = harness();
    try {
      const failure = { status: 403, error: { detail: { code } } };
      h.component.schedules.set([schedule]);
      h.component.setScheduleIdentity(schedule, 'current_user');
      h.patches[0].response.error(failure);
      assert.deepEqual(h.component.identityError(), { id: schedule.id, key });
      assert.equal(h.component.schedules()[0].execution_identity, null);
      h.component.newSchedUseMyAccess = true;
      h.component.createSchedule();
      h.posts[0].response.error(failure);
      assert.equal(h.component.scheduleError(), key);
      assert.equal(h.component.newSchedUseMyAccess, true, 'failed save retains the explicit choice for correction');
      h.kind.set('webhook');
      h.component.newHookUseMyAccess = true;
      h.component.createHook();
      h.posts[1].response.error(failure);
      assert.equal(h.errors.at(-1), (FLOW_EN as Record<string, string>)[key]);
      assert.equal(h.component.busy(), false);
    } finally { h.injector.destroy(); }
  }
});

test('late identity responses cannot populate a different System or trigger inspector', () => {
  for (const destination of ['system', 'kind'] as const) {
    const h = harness();
    try {
      h.component.schedules.set([schedule]);
      h.component.setScheduleIdentity(schedule, 'current_user');
      if (destination === 'system') h.system.set('system-two');
      else h.kind.set('webhook');
      h.patches[0].response.next({ ...schedule, execution_identity: delegatedIdentity });
      assert.equal(h.component.schedules()[0].execution_identity, null);
      assert.equal(h.component.identityError(), null);
    } finally { h.injector.destroy(); }
  }
  const h = harness();
  h.component.schedules.set([schedule]);
  h.component.setScheduleIdentity(schedule, 'current_user');
  h.injector.destroy();
  h.patches[0].response.next({ ...schedule, execution_identity: delegatedIdentity });
  assert.equal(h.component.schedules()[0].execution_identity, null);
});

test('enabling an existing trigger never grants or replaces execution access', () => {
  const h = harness();
  try {
    h.component.toggleSchedule({ ...schedule, execution_identity: delegatedIdentity });
    assert.deepEqual(h.patches[0].body, { enabled: true });
    h.patches[0].response.next({ ...schedule, enabled: true, execution_identity: delegatedIdentity });
    h.component.toggleHook(hook);
    assert.deepEqual(h.patches[1].body, { enabled: true });
  } finally { h.injector.destroy(); }
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
    'flow.triggers.identity.label', 'flow.triggers.identity.none', 'flow.triggers.identity.use_mine',
    'flow.triggers.identity.consent', 'flow.triggers.identity.note', 'flow.triggers.identity.remove',
    'flow.triggers.identity.remove_note', 'flow.triggers.identity.saving', 'flow.triggers.identity.forbidden',
    'flow.triggers.identity.update_failed',
    'flow.triggers.identity.publication_note', 'flow.triggers.identity.publication_changed',
    'flow.triggers.identity.publication_required',
  ]) {
    assert.ok((FLOW_FR as Record<string, string>)[key]);
    assert.ok((FLOW_EN as Record<string, string>)[key]);
  }
});
