import assert from 'node:assert/strict';
import { test } from 'node:test';
import { depositReceipt, failedDepositReceipt } from './deposit-receipt';

test('receipt preserves per-file server verdict and rejection reason', () => {
  assert.deepEqual(depositReceipt('unsafe.exe', { file: { status: 'rejected', rejection_reason: 'Extension refused' } }), { filename: 'unsafe.exe', state: 'rejected', reason: 'Extension refused' });
  assert.equal(depositReceipt('notes.pdf', { file: { status: 'received' } }).state, 'received');
  assert.equal(depositReceipt('notes.pdf', {}).state, 'unknown');
});

test('lost upload answers are unknown and cannot be treated as rejected or retried automatically', () => {
  for (const status of [0, 408, 502, 504]) assert.equal(failedDepositReceipt('notes.pdf', { status }).state, 'unknown');
  assert.equal(failedDepositReceipt('large.pdf', { status: 413 }).state, 'rejected');
  assert.equal(failedDepositReceipt('notes.pdf', { status: 403 }).state, 'failed');
});
