import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { AuthStore } from './auth.store';

test('AuthStore advances an opaque epoch and resets principal caches atomically', () => {
  const injector = Injector.create({ providers: [AuthStore] });
  const auth = injector.get(AuthStore);
  const observations: Array<{ callbackEpoch: number; nextEpoch: number }> = [];
  auth.registerContextReset((transition) => {
    observations.push({
      callbackEpoch: auth.authEpoch(),
      nextEpoch: transition.nextEpoch,
    });
  });

  auth.setAuthenticated({ userId: 'user-a', email: 'a@example.invalid', role: 'member' });
  const principalAScope = auth.captureRequestScope();
  auth.clear();
  auth.setAuthenticated({ userId: 'user-b', email: 'b@example.invalid', role: 'member' });

  assert.equal(auth.authEpoch(), 3);
  assert.equal(auth.userId(), 'user-b');
  assert.equal(auth.isRequestScopeCurrent(principalAScope), false);
  assert.deepEqual(principalAScope, { epoch: 1 });
  assert.deepEqual(observations, [
    { callbackEpoch: 0, nextEpoch: 1 },
    { callbackEpoch: 1, nextEpoch: 2 },
    { callbackEpoch: 2, nextEpoch: 3 },
  ]);

  auth.clear();
  assert.equal(auth.authEpoch(), 4);
  assert.equal(auth.isAuthenticated(), false);
  assert.equal(auth.userId(), null);
  assert.deepEqual(observations.at(-1), { callbackEpoch: 3, nextEpoch: 4 });

  injector.destroy();
});
