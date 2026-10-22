import assert from 'node:assert/strict';
import { test } from 'node:test';
import { newVersionAvailable } from './new-version';

const a = { revision: 'a'.repeat(40), revision_verified: true };
const b = { revision: 'b'.repeat(40), revision_verified: true };

test('a different served revision is a new version', () => {
  assert.equal(newVersionAvailable(a, b), true);
  assert.equal(newVersionAvailable(a, { revision: 'A'.repeat(40) }), false);
});

test('development builds, missing files and failed reads never raise a notice', () => {
  assert.equal(newVersionAvailable({ revision: 'development' }, b), false);
  assert.equal(newVersionAvailable(a, { revision: 'development' }), false);
  assert.equal(newVersionAvailable(null, b), false);
  assert.equal(newVersionAvailable(a, null), false);
  assert.equal(newVersionAvailable(a, { revision: 42 }), false);
});
