import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { CHROME_EN, CHROME_FR } from '../../core/i18n/chrome.dict';
import {
  passwordErrors,
  resendState,
  signupErrorKey,
  signupResult,
  verificationView,
} from './signup.vm';

const confirmed = (value: unknown) => ({ s: 'confirmed', value, at: 1 }) as const;

test('only an explicit true counts as a sent verification email', () => {
  assert.equal(verificationView(true), 'sent');
  assert.equal(verificationView(false), 'not_sent');
  assert.equal(verificationView(undefined), 'unconfirmed');
  assert.equal(verificationView(null), 'unconfirmed');
  assert.deepEqual(signupResult(confirmed({ status: 'ok', message: 'User created.' })), { view: 'unconfirmed', error: null });
  assert.deepEqual(signupResult(confirmed({ verification_email_sent: false })), { view: 'not_sent', error: null });
  assert.deepEqual(signupResult(confirmed({ verification_email_sent: true })), { view: 'sent', error: null });
});

test('a lost answer is unknown, never a failure that invites a second account', () => {
  assert.deepEqual(signupResult({ s: 'unknown', status: null, code: 'timeout' }), { view: 'unknown', error: null });
});

test('a refused signup stays on the form with a cause in the reader\'s words', () => {
  const failed = (status: number) => signupResult({ s: 'failed', status, code: null, detail: 'User already exists' });
  assert.deepEqual(failed(409), { view: 'form', error: 'auth.signup.error.exists' });
  assert.equal(failed(503).error, 'auth.signup.error.unavailable');
  assert.equal(failed(422).error, 'auth.signup.error.invalid');
  assert.equal(failed(500).error, 'auth.signup.error.server');
  assert.equal(signupErrorKey(null), 'auth.signup.error.server');
});

test('password errors name the field that is wrong', () => {
  assert.deepEqual(passwordErrors('Str0ng!Pass', 'Str0ng!Pass'), { password: null, confirm: null });
  assert.deepEqual(passwordErrors('weak', 'weak'), { password: 'auth.signup.error.password_weak', confirm: null });
  assert.deepEqual(passwordErrors('Str0ng!Pass', 'Str0ng!Pas'), { password: null, confirm: 'auth.signup.error.password_mismatch' });
});

test('resending says sent only when the server says so', () => {
  assert.equal(resendState(null), 'idle');
  assert.equal(resendState({ s: 'sent' }), 'sending');
  assert.equal(resendState(confirmed({ verification_email_sent: true })), 'sent');
  assert.equal(resendState(confirmed({ verification_email_sent: false })), 'not_sent');
  assert.equal(resendState(confirmed({})), 'not_sent');
  assert.equal(resendState({ s: 'failed', status: 503, code: null, detail: null }), 'failed');
  assert.equal(resendState({ s: 'unknown', status: null, code: 'network' }), 'unknown');
});

test('every signup text exists in FR and EN', () => {
  const views = ['sent', 'not_sent', 'unconfirmed', 'unknown'];
  const keys = [
    ...views.flatMap((view) => ['eyebrow', 'title', 'body'].map((part) => `auth.signup.result.${view}.${part}`)),
    ...['sent', 'not_sent', 'failed', 'unknown'].map((state) => `auth.signup.resend.${state}`),
  ];
  for (const key of keys) {
    assert.ok(CHROME_FR[key], `FR ${key}`);
    assert.ok(CHROME_EN[key], `EN ${key}`);
  }
});

test('the signup page has no hard-coded English left', () => {
  const source = readFileSync(join(process.cwd(), 'src/app/features/auth/signup.component.ts'), 'utf8');
  const template = source.slice(source.indexOf('template: `'), source.indexOf('styles: ['));
  for (const legacy of ['Create your cockpit', 'CREATE ACCOUNT', 'Registration failed', 'Passwords do not match', 'Back to sign in', 'First name']) {
    assert.ok(!source.includes(legacy), legacy);
  }
  // Text nodes between tags are interpolations only.
  const textNodes = template.match(/>\s*([^<{@}\s][^<{]*?)\s*</g) ?? [];
  const words = textNodes.map((node) => node.slice(1, -1).trim()).filter((text) => /[A-Za-z]{3,}/.test(text));
  assert.deepEqual(words, []);
});
