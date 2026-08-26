/**
 * A workspace may declare the language its pages open in. The Nawa data/ML
 * demo is the reason: every string it seeds is English, so the chrome around
 * them has to open English on whatever browser the room happens to have — and
 * "remember to flip the switcher" is not a deployment property.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { workspaceLocale } from './workspace-locale';

test('a workspace declares the language its pages open in', () => {
  assert.equal(workspaceLocale({ presentation: { locale: 'en' } }), 'en');
  assert.equal(workspaceLocale({ presentation: { locale: 'fr' } }), 'fr');
});

test('a workspace that declares nothing gets no opinion', () => {
  assert.equal(workspaceLocale(undefined), null);
  assert.equal(workspaceLocale(null), null);
  assert.equal(workspaceLocale({}), null);
  assert.equal(workspaceLocale({ presentation: {} }), null);
});

test('a locale the product does not have is not a locale', () => {
  // Returning it would put the key names on screen: the dictionaries are the
  // list of languages, and a third one silently falls through to the key.
  assert.equal(workspaceLocale({ presentation: { locale: 'de' } }), null);
  assert.equal(workspaceLocale({ presentation: { locale: 'EN' } }), null);
  assert.equal(workspaceLocale({ presentation: { locale: '' } }), null);
  assert.equal(workspaceLocale({ presentation: { locale: 42 } }), null);
});

test('a presentation block that is not a block is ignored, not trusted', () => {
  // Settings are tenant-writable JSON, so every shape has to be survivable.
  assert.equal(workspaceLocale({ presentation: 'en' }), null);
  assert.equal(workspaceLocale({ presentation: ['en'] }), null);
  assert.equal(workspaceLocale({ presentation: null }), null);
});
