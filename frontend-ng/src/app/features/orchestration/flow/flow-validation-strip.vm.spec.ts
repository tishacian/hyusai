/**
 * Unit tests for `toValidationStripVm` — the checklist projection.
 *
 * Covers the issues → rows mapping the strip renders: client + server folding,
 * cross-origin dedup, error/warn grouping and counts, and the empty/clean
 * state. Pure logic (no Angular/DI) under the `node:test` harness.
 *
 * Run with `npm run test:unit`.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  toValidationStripVm,
  type ValidationIssueLike,
} from './flow-validation-strip.vm';

test('no issues → clean, empty rows, zero counts', () => {
  const vm = toValidationStripVm([], []);
  assert.equal(vm.clean, true);
  assert.equal(vm.rows.length, 0);
  assert.equal(vm.errorCount, 0);
  assert.equal(vm.warnCount, 0);

  // Tolerates null/undefined inputs.
  assert.equal(toValidationStripVm(null, undefined).clean, true);
});

test('client issues map to rows; errors group before warnings with counts', () => {
  const client: ValidationIssueLike[] = [
    { level: 'warn', code: 'task_no_skill', message: 'Task X has no Skill bound.', node_id: 'x' },
    { level: 'error', code: 'cycle_detected', message: 'Flow contains a cycle.' },
    { level: 'warn', code: 'variable_unresolved', message: 'Input reads unknown node.', node_id: 'y' },
  ];
  const vm = toValidationStripVm(client);

  assert.equal(vm.errorCount, 1);
  assert.equal(vm.warnCount, 2);
  // Errors first.
  assert.equal(vm.rows[0].level, 'error');
  assert.equal(vm.rows[0].code, 'cycle_detected');
  assert.equal(vm.rows[0].nodeId, null, 'graph-level issue has no node id');
  // Node-scoped rows carry the node id (used for click → setSelection).
  const taskRow = vm.rows.find((r) => r.code === 'task_no_skill');
  assert.equal(taskRow?.nodeId, 'x');
  assert.equal(taskRow?.origin, 'client');
});

test('server issues are folded in and tagged; identical client+server is deduped', () => {
  const shared: ValidationIssueLike = {
    level: 'error',
    code: 'task_no_skill',
    message: 'Task X has no Skill bound.',
    node_id: 'x',
  };
  const serverOnly: ValidationIssueLike = {
    level: 'error',
    code: 'node_orphan',
    message: 'Node z is orphaned.',
    node_id: 'z',
  };

  const vm = toValidationStripVm([shared], [shared, serverOnly]);
  // The shared issue appears once (client wins), the server-only one is added.
  assert.equal(vm.rows.length, 2);
  const sharedRows = vm.rows.filter((r) => r.code === 'task_no_skill');
  assert.equal(sharedRows.length, 1, 'identical client+server issue deduped');
  assert.equal(sharedRows[0].origin, 'client');

  const serverRow = vm.rows.find((r) => r.code === 'node_orphan');
  assert.equal(serverRow?.origin, 'server', 'server-only issue keeps its origin tag');
  assert.equal(serverRow?.nodeId, 'z');
});

test('node_id null/undefined normalize to null', () => {
  const vm = toValidationStripVm([
    { level: 'warn', code: 'join_without_fork', message: 'Join with no fork.' },
    { level: 'warn', code: 'fork_without_join', message: 'Fork with no join.', node_id: null },
  ]);
  assert.equal(vm.warnRows.length, 2);
  assert.ok(vm.warnRows.every((r) => r.nodeId === null));
});
