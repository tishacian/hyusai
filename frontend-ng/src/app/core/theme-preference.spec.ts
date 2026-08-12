import { strict as assert } from 'node:assert';
import test from 'node:test';

import { resolveStoredThemeMode } from './theme-preference';

test('a fresh browser follows the operating system', () => {
  assert.equal(resolveStoredThemeMode(null, null), 'system');
});

test('an explicit preference on the unified key is honoured', () => {
  assert.equal(resolveStoredThemeMode('light', null), 'light');
  assert.equal(resolveStoredThemeMode('dark', null), 'dark');
  assert.equal(resolveStoredThemeMode('system', null), 'system');
});

test('the business-shell key is adopted when the unified key is unset', () => {
  assert.equal(resolveStoredThemeMode(null, 'light'), 'light');
  assert.equal(resolveStoredThemeMode(null, 'system'), 'system');
});

test("the pin's constant dark loses to a real business-shell choice", () => {
  // `agentium_theme` was written as 'dark' on every boot, so it carries no
  // intent; `agentium_business_theme` only ever held a click.
  assert.equal(resolveStoredThemeMode('dark', 'light'), 'light');
  assert.equal(resolveStoredThemeMode('dark', 'system'), 'system');
  assert.equal(resolveStoredThemeMode('dark', 'dark'), 'dark');
});

test('a non-dark unified value outranks the legacy key', () => {
  assert.equal(resolveStoredThemeMode('light', 'dark'), 'light');
  assert.equal(resolveStoredThemeMode('system', 'dark'), 'system');
});

test('garbage in either key never escapes the tri-state', () => {
  assert.equal(resolveStoredThemeMode('sepia', null), 'system');
  assert.equal(resolveStoredThemeMode('', 'nope'), 'system');
  assert.equal(resolveStoredThemeMode('nope', 'dark'), 'dark');
});
