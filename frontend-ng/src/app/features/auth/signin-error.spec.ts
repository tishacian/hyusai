import assert from 'node:assert/strict';
import test from 'node:test';

import { signinErrorKey } from './signin-error';

test('credential rejection gets the credential-specific message', () => {
  assert.equal(signinErrorKey({ status: 401 }), 'auth.signin.error.credentials');
  assert.equal(signinErrorKey({ status: 403 }), 'auth.signin.error.credentials');
});

test('network and server failures do not blame the password', () => {
  assert.equal(signinErrorKey({ status: 0 }), 'auth.signin.error.unavailable');
  assert.equal(signinErrorKey({ status: 500 }), 'auth.signin.error.unavailable');
  assert.equal(signinErrorKey({ status: 503 }), 'auth.signin.error.unavailable');
});

test('unexpected client failures stay neutral', () => {
  assert.equal(signinErrorKey({ status: 422 }), 'auth.signin.error.unexpected');
  assert.equal(signinErrorKey(null), 'auth.signin.error.unexpected');
});
