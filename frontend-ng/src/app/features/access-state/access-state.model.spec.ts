import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Router } from '@angular/router';
import {
  accessReasonFromError,
  accessStateUrl,
  parseAccessFeature,
  parseAccessReason,
  safeReturnPath,
} from './access-state.model';

test('unknown reasons read as not found, unknown features as none', () => {
  assert.equal(parseAccessReason('disabled'), 'disabled');
  assert.equal(parseAccessReason('<script>'), 'not_found');
  assert.equal(parseAccessReason(null), 'not_found');
  assert.equal(parseAccessFeature('studio'), 'studio');
  assert.equal(parseAccessFeature('admin'), null);
});

test('the return path stays inside the app and never loops on itself', () => {
  assert.equal(safeReturnPath('/create/apps?x=1'), '/create/apps?x=1');
  assert.equal(safeReturnPath('https://evil.example'), null);
  assert.equal(safeReturnPath('//evil.example/x'), null);
  assert.equal(safeReturnPath('/\\evil.example'), null);
  assert.equal(safeReturnPath('/unavailable?reason=disabled'), null);
  assert.equal(safeReturnPath('/unavailable'), null);
  assert.equal(safeReturnPath('/' + 'a'.repeat(3000)), null);
});

test('the access-state URL carries the reason, the feature and a safe origin only', () => {
  const calls: unknown[] = [];
  const router = { createUrlTree: (commands: unknown, extras: unknown) => { calls.push({ commands, extras }); return 'tree'; } } as unknown as Router;
  accessStateUrl(router, 'disabled', { from: '/work', feature: 'work' });
  accessStateUrl(router, 'not_found', { from: 'https://evil.example' });
  assert.deepEqual(calls, [
    { commands: ['/unavailable'], extras: { queryParams: { reason: 'disabled', from: '/work', feature: 'work' } } },
    { commands: ['/unavailable'], extras: { queryParams: { reason: 'not_found' } } },
  ]);
});

test('server errors map to a case; a hidden object reads as not found', () => {
  assert.deepEqual(accessReasonFromError({ status: 404, error: { code: 'EXPERIENCE_V1_DISABLED' } }), { reason: 'disabled', feature: 'work' });
  assert.deepEqual(accessReasonFromError({ status: 404, error: { detail: { code: 'EXPERIENCE_STUDIO_V1_DISABLED' } } }), { reason: 'disabled', feature: 'studio' });
  assert.deepEqual(accessReasonFromError({ status: 403, error: {} }), { reason: 'not_found', feature: null });
  assert.deepEqual(accessReasonFromError({ status: 404, error: null }), { reason: 'not_found', feature: null });
  assert.deepEqual(accessReasonFromError({ status: 0 }), { reason: 'unverifiable', feature: null });
  assert.deepEqual(accessReasonFromError({ status: 503 }), { reason: 'unverifiable', feature: null });
  assert.deepEqual(accessReasonFromError(new Error('x')), { reason: 'unverifiable', feature: null });
});
