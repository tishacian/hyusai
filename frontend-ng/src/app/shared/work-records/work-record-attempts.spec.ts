import assert from 'node:assert/strict';
import { test } from 'node:test';
import { attemptsView } from './work-record-attempts.vm';

const row = (run_id: string) => ({ run_id });

test('an empty ledger with no Run shown is an honest "no attempt"', () => {
  assert.deepEqual(attemptsView([], false, null), { lines: [], historyIncomplete: false, empty: true });
});

test('a Run shown on the page but missing from the ledger is listed and the history is incomplete', () => {
  const view = attemptsView([], false, 'run-0399');
  assert.equal(view.empty, false);
  assert.equal(view.historyIncomplete, true);
  assert.deepEqual(view.lines, [{ runId: 'run-0399', attempt: null }]);

  const older = attemptsView([row('run-new')], false, 'run-0399');
  assert.deepEqual(older.lines.map((line) => line.runId), ['run-0399', 'run-new']);
  assert.equal(older.historyIncomplete, true);
});

test('a Run already in the ledger, or possibly on a later page, is not duplicated nor flagged', () => {
  const listed = attemptsView([row('run-a'), row('run-b')], false, 'run-b');
  assert.deepEqual(listed.lines.map((line) => line.runId), ['run-a', 'run-b']);
  assert.equal(listed.historyIncomplete, false);

  const paged = attemptsView([row('run-a')], true, 'run-z');
  assert.deepEqual(paged.lines.map((line) => line.runId), ['run-a']);
  assert.equal(paged.historyIncomplete, false);
});
