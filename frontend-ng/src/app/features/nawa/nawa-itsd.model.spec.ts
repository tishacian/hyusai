import { test } from 'node:test';
import assert from 'node:assert/strict';
import { systemIdFromBindingResolve } from './nawa-itsd.model';

test('systemIdFromBindingResolve prefers an ok binding and ignores misses', () => {
  assert.equal(
    systemIdFromBindingResolve({ status: 'ok', binding: { system_id: 'sys-1' } }),
    'sys-1',
  );
  assert.equal(systemIdFromBindingResolve({ status: 'unavailable', binding: { system_id: 'sys-1' } }), null);
  assert.equal(systemIdFromBindingResolve({ status: 'ok', binding: {} }), null);
  assert.equal(systemIdFromBindingResolve(null), null);
});
