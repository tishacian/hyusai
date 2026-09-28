import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  LEXICON_ROWS_MAX,
  composePaletteResults,
  frenchElides,
  lexiconMatches,
  normalizePaletteQuery,
} from './command-palette.intent';

test('queries are compared without case, accents or typographic apostrophes', () => {
  assert.equal(normalizePaletteQuery('  Qu’est-ce   qu’une ÉXÉCUTION ? '), "qu'est-ce qu'une execution ?");
});

test('a lexicon term matches in French or in English, shown in the reader locale', () => {
  const [run] = lexiconMatches('exécution', 'en');
  assert.equal(run.id, 'run');
  assert.equal(run.term, 'Run');
  assert.match(run.definition, /\w/);

  const [draft] = lexiconMatches('draft', 'fr');
  assert.equal(draft.id, 'draft');
  assert.equal(draft.term, 'Brouillon');
  assert.match(draft.definition, /\w/);
});

test('a natural-language question finds the term it names', () => {
  assert.deepEqual(lexiconMatches("qu'est-ce qu'un flow", 'fr').map((m) => m.id), ['flow']);
  assert.deepEqual(lexiconMatches('what are skills?', 'en').map((m) => m.id), ['skill']);
});

test('an exact term beats loose matches, and rows are capped', () => {
  assert.deepEqual(lexiconMatches('skill', 'en').map((m) => m.id), ['skill']);
  assert.ok(lexiconMatches('e', 'en').length === 0, 'one letter is not a question');
  assert.ok(lexiconMatches('re', 'en').length <= LEXICON_ROWS_MAX);
  assert.deepEqual(lexiconMatches('zzzz', 'fr'), []);
});

test('French elides « que » before a vowel only', () => {
  assert.equal(frenchElides('Exécution'), true);
  assert.equal(frenchElides('Application métier'), true);
  assert.equal(frenchElides('Brouillon'), false);
  assert.equal(frenchElides('Skill'), false);
});

test('no match puts the agent row first so Enter asks the agent', () => {
  const ask = 'ask';
  assert.deepEqual(composePaletteResults('quels runs ont échoué hier', [], [], ask), ['ask']);
  assert.deepEqual(composePaletteResults("qu'est-ce qu'un flow", [], ['define.flow'], ask), ['ask', 'define.flow']);
});

test('matching commands stay first; definitions follow and survive the cap', () => {
  const matches = Array.from({ length: 50 }, (_, i) => `cmd-${i}`);
  const rows = composePaletteResults('skill', matches, ['define.skill'], 'ask');
  assert.equal(rows.length, 40);
  assert.equal(rows[0], 'cmd-0');
  assert.equal(rows.at(-1), 'define.skill');
  assert.equal(rows.includes('ask'), false, 'the agent row only answers a query without match');
});

test('an empty query lists commands only', () => {
  const matches = Array.from({ length: 45 }, (_, i) => `cmd-${i}`);
  const rows = composePaletteResults('   ', matches, ['define.skill'], null);
  assert.equal(rows.length, 40);
  assert.equal(rows.includes('define.skill'), false);
});
