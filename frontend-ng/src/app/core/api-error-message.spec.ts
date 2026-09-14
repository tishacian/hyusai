import assert from 'node:assert/strict';
import test from 'node:test';

import { apiErrorMessage } from './api-error-message';

test('reads FastAPI validation messages instead of coercing detail arrays', () => {
  assert.equal(
    apiErrorMessage(
      { error: { detail: [{ msg: 'Value error, Unknown action pack: generic' }] } },
      'Save failed',
    ),
    'Unknown action pack: generic',
  );
});

test('reads structured API messages and falls back for opaque objects', () => {
  assert.equal(
    apiErrorMessage(
      { error: { detail: { code: 'DENIED', message: 'Admin access required' } } },
      'Save failed',
    ),
    'Admin access required',
  );
  assert.equal(apiErrorMessage({ error: { detail: { code: 'OPAQUE' } } }, 'Save failed'), 'Save failed');
});
