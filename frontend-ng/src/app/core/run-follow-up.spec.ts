import assert from 'node:assert/strict';
import { test } from 'node:test';
import { RUNS_EN, RUNS_FR } from './i18n/runs.dict';
import { runStatusKey, runStatusLabel, stoppedAtReviewBoundary, type RunFollowUp } from './run-follow-up';

const boundary: RunFollowUp = {
  native_status: 'cancelled',
  business_state: 'stopped_at_review_boundary',
  cause: { code: 'evaluation_stopped_at_review_boundary', boundary: 'human_gate' },
};
const fr = (key: string) => (RUNS_FR as Record<string, string>)[key] ?? key;
const en = (key: string) => (RUNS_EN as Record<string, string>)[key] ?? key;

test('a planned stop at human review reads as such, never as cancelled', () => {
  const run = { status: 'cancelled', follow_up: boundary };
  assert.equal(runStatusKey(run), 'runs.follow_up.stopped_at_review_boundary');
  assert.equal(runStatusLabel(run, fr), 'Arrêté à la revue humaine');
  assert.equal(runStatusLabel(run, en), 'Stopped at human review');
  assert.equal(stoppedAtReviewBoundary(run), true);
});

test('projections without follow_up fall back to the native status', () => {
  assert.equal(runStatusKey({ status: 'cancelled' }), 'runs.status.cancelled');
  assert.equal(runStatusLabel({ status: 'cancelled' }, fr), 'Annulé');
  assert.equal(stoppedAtReviewBoundary({ status: 'cancelled' }), false);
  assert.equal(runStatusLabel(null, fr), '');
});

test('an unknown business state stays visible as its raw value', () => {
  const run = { status: 'running', follow_up: { native_status: 'running', business_state: 'brand_new', cause: null } };
  assert.equal(runStatusLabel(run, fr), 'brand_new');
});

test('every business state has a French and English label', () => {
  for (const state of ['in_progress', 'awaiting_human_decision', 'paused_for_debug', 'stopped_at_review_boundary', 'completed', 'failed', 'cancelled', 'unknown']) {
    const key = `runs.follow_up.${state}`;
    assert.notEqual(fr(key), key, key);
    assert.notEqual(en(key), key, key);
  }
});

test('an expired approval reads as expired, never as a failure', () => {
  const run = { status: 'failed', follow_up: { native_status: 'failed', business_state: 'decision_expired', cause: { code: 'human_decision_expired' } } };
  assert.equal(runStatusLabel(run, fr), 'Validation expirée');
  assert.equal(runStatusLabel(run, en), 'Approval expired');
});
