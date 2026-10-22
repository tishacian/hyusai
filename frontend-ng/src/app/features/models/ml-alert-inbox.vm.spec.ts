import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { MLAlert } from './endpoints.vm';
import { mlAlertEventKey, mlAlertStateKey, summarizeMLAlerts } from './ml-alert-inbox.vm';

const alert = (id: string, state: string, acknowledged_at: string | null = null): MLAlert => ({
  id, state, acknowledged_at, model_id: 'model', workspace_id: 'workspace',
  event: 'monitor_transition', created_at: `2026-10-22T10:00:${id.padStart(2, '0')}Z`,
});

test('unacknowledged count never adopts the API historical total', () => {
  const summary = summarizeMLAlerts([alert('1', 'alert', '2026-10-22T11:00:00Z'), alert('2', 'ok')], 82);
  assert.equal(summary.total, 82);
  assert.equal(summary.loaded, 2);
  assert.equal(summary.partial, true);
  assert.equal(summary.unread, 1);
  assert.equal(summary.severe, 0);
  assert.equal(summary.items[0].id, '2');
});

test('recorded alert and failure events remain visible ahead of recent recoveries', () => {
  const items = [alert('1', 'alert'), alert('2', 'failed'), ...[3, 4, 5, 6, 7, 8].map(n => alert(String(n), 'ok'))];
  const summary = summarizeMLAlerts(items, items.length);
  assert.equal(summary.unread, 8);
  assert.equal(summary.severe, 2);
  assert.deepEqual(summary.items.map(item => item.id), ['2', '1', '8', '7', '6']);
  assert.deepEqual(items.map(item => item.id), ['1', '2', '3', '4', '5', '6', '7', '8']);
});

test('unknown events remain reviewable and are not mislabeled as quota alerts', () => {
  const item = {...alert('1', 'future_state'), event: 'new_event_type'};
  assert.deepEqual(summarizeMLAlerts([item], 1).items, [item]);
  assert.equal(mlAlertEventKey(item.event), null);
  assert.equal(mlAlertStateKey(item.state), null);
  assert.equal(mlAlertEventKey('quota_reached'), 'models.endpoints.quota');
  assert.equal(mlAlertStateKey('ok'), 'models.alert_inbox.state.recovered');
});

test('empty or acknowledged history reports counts without inferring healthy models', () => {
  assert.deepEqual(summarizeMLAlerts([], 0), {loaded: 0, total: 0, partial: false, unread: 0, severe: 0, items: []});
  const summary = summarizeMLAlerts([alert('1', 'failed', '2026-10-22T11:00:00Z')], 1);
  assert.equal(summary.unread, 0);
  assert.equal(summary.severe, 0);
  assert.equal(summary.partial, false);
  assert.deepEqual(summary.items, []);
});
