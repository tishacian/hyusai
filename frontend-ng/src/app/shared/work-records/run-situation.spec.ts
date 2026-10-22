import assert from 'node:assert/strict';
import { test } from 'node:test';
import { RUNS_EN } from '@app/core/i18n/runs.dict';
import type { RunFollowUpDetail } from '@app/core/run-follow-up';
import { situationLines } from './run-situation.vm';

const t = (key: string, params?: Record<string, string | number>) =>
  Object.entries(params ?? {}).reduce((text, [name, value]) => text.replace(`{${name}}`, String(value)), (RUNS_EN as Record<string, string>)[key] ?? key);
const quality = (value: string) => value;
const base: RunFollowUpDetail = {
  run_id: 'run-1', native_status: 'hitl_pending', business_state: 'awaiting_human_decision', cause: null, attempt: null,
  subject: { field: 'claim_id', value: 'RC-1' }, proposal: 'Open a carrier investigation',
  decision: { state: 'awaiting', decision_id: 'd', title: null, expires_at: '2026-10-25T14:00:00Z', expiry_action: 'reject', expired_at: null, seconds_remaining: 3600 },
  payload_unavailable_reason: null,
};

test('situation reads the object, the proposal and an open decision with its zoned deadline', () => {
  const lines = situationLines(base, { s: 'loaded', value: null }, t, 'en-GB', quality);
  assert.deepEqual(lines.map(line => line.id), ['subject', 'proposal', 'quality', 'decision', 'effect']);
  assert.equal(lines[0].value, 'RC-1');
  assert.equal(lines[1].value, 'Open a carrier investigation');
  assert.equal(lines[2].value, 'No check recorded for this run.');
  assert.equal(lines[3].value, 'Yes, a decision is expected.');
  assert.match(lines[3].detail ?? '', /^Due: .+\d{2}:\d{2} \S+$/);
  assert.equal(lines[4].unknown, true);
});

test('an expired approval is said, never shown as still expected', () => {
  const detail = { ...base, decision: { ...base.decision!, state: 'expired', expired_at: '2026-10-22T14:00:05Z' } };
  const decision = situationLines(detail, { s: 'loading' }, t, 'en-GB', quality)[3];
  assert.equal(decision.value, 'No: the approval deadline has passed.');
  assert.match(decision.detail ?? '', /^Expired on /);
});

test('missing facts are unknown and a failed quality read is not "no check"', () => {
  const detail = { ...base, subject: null, proposal: null, decision: null, business_state: 'unknown' };
  const lines = situationLines(detail, { s: 'error' }, t, 'en-GB', quality);
  assert.equal(lines[0].unknown, true);
  assert.equal(lines[1].value, 'Unknown');
  assert.equal(lines[2].value, 'The check could not be read.');
  assert.equal(lines[3].unknown, true);
});

test('a planned stop at review says no decision and no business effect', () => {
  const detail = { ...base, business_state: 'stopped_at_review_boundary', decision: { ...base.decision!, state: 'closed_by_evaluation' } };
  const lines = situationLines(detail, { s: 'loaded', value: { quality: 'passed', execution: 'completed', count: 1 } }, t, 'en-GB', quality);
  assert.equal(lines[2].value, 'passed');
  assert.equal(lines[3].value, 'No: the trial stopped before the decision, as planned.');
  assert.equal(lines[4].value, 'None: no business action was approved.');
});
