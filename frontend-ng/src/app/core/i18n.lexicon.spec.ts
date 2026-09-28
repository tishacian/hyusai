/**
 * The lexicon is the contract four parallel work streams write against, and
 * the split dictionary is what they all edit. Both are cheap to break by
 * hand and expensive to notice in the browser, so the invariants the guard
 * relies on are pinned here.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { EN_DICT, FR_DICT, I18N_DOMAINS } from './i18n.dict';
import {
  CONCEPT_HELP_PREFIX,
  UI_LEXICON,
  forbiddenWords,
  lexiconDefinition,
  lexiconEntry,
  lexiconTerm,
  untranslatedInFrench,
  untranslatedTerms,
} from './i18n.lexicon';

test('every lexicon entry is complete in both languages', () => {
  for (const entry of UI_LEXICON) {
    assert.ok(entry.id.length > 0, 'entry needs an id');
    assert.match(entry.id, /^[a-z0-9-]+$/, `${entry.id}: id must be kebab-case`);
    for (const field of ['en', 'fr'] as const) {
      assert.ok(entry[field].length > 0, `${entry.id}: missing ${field} term`);
      assert.ok(
        entry.definition[field].length > 0,
        `${entry.id}: missing ${field} definition`,
      );
    }
  }
});

test('definitions stay one line of plain language', () => {
  for (const entry of UI_LEXICON) {
    for (const definition of [entry.definition.en, entry.definition.fr]) {
      assert.ok(!definition.includes('\n'), `${entry.id}: definition must be one line`);
      assert.ok(
        definition.length <= 140,
        `${entry.id}: definition is ${definition.length} chars, too long for a tooltip`,
      );
    }
  }
});

test('concept ids are unique', () => {
  const ids = UI_LEXICON.map((entry) => entry.id);
  assert.equal(new Set(ids).size, ids.length, 'duplicate concept id');
});

test('a forbidden word belongs to exactly one concept', () => {
  const seen = new Map<string, string>();
  for (const { word, conceptId } of forbiddenWords()) {
    const previous = seen.get(word.toLowerCase());
    assert.equal(
      previous,
      undefined,
      `"${word}" is forbidden by both ${previous} and ${conceptId}; the guard would report it twice`,
    );
    seen.set(word.toLowerCase(), conceptId);
  }
});

test('the canonical term of a concept is never itself forbidden', () => {
  const forbidden = new Set(forbiddenWords().map((entry) => entry.word.toLowerCase()));
  for (const entry of UI_LEXICON) {
    assert.ok(!forbidden.has(entry.en.toLowerCase()), `${entry.id}: EN term is banned`);
    assert.ok(!forbidden.has(entry.fr.toLowerCase()), `${entry.id}: FR term is banned`);
  }
});

test('lookups fall back instead of throwing on an unknown concept', () => {
  assert.equal(lexiconEntry('not-a-concept'), null);
  assert.equal(lexiconTerm('not-a-concept', 'fr'), 'not-a-concept');
  assert.equal(lexiconDefinition('not-a-concept', 'en'), '');
  assert.equal(lexiconTerm('run', 'en'), 'Run');
  assert.equal(lexiconTerm('run', 'fr'), 'Exécution');
  assert.equal(CONCEPT_HELP_PREFIX, 'concept.');
});

test('the dictionary keeps FR/EN parity across every domain', () => {
  assert.deepEqual(Object.keys(FR_DICT).sort(), Object.keys(EN_DICT).sort());
  for (const [domain, spec] of Object.entries(I18N_DOMAINS)) {
    assert.deepEqual(
      Object.keys(spec.fr).sort(),
      Object.keys(spec.en).sort(),
      `${domain}: FR and EN halves disagree`,
    );
  }
});

test('each key lives in the domain module that owns its prefix', () => {
  const owner = new Map<string, string>();
  for (const [domain, spec] of Object.entries(I18N_DOMAINS)) {
    for (const prefix of spec.prefixes) {
      assert.equal(owner.get(prefix), undefined, `prefix '${prefix}' claimed twice`);
      owner.set(prefix, domain);
    }
  }
  for (const [domain, spec] of Object.entries(I18N_DOMAINS)) {
    for (const key of Object.keys(spec.fr)) {
      assert.equal(
        owner.get(key.split('.')[0]),
        domain,
        `'${key}' is filed in ${domain}.dict.ts`,
      );
    }
  }
});

test('no key is defined by two domains, so the merge order never decides', () => {
  const seen = new Set<string>();
  for (const spec of Object.values(I18N_DOMAINS)) {
    for (const key of Object.keys(spec.fr)) {
      assert.ok(!seen.has(key), `'${key}' is defined in two domain modules`);
      seen.add(key);
    }
  }
  assert.equal(seen.size, Object.keys(FR_DICT).length, 'a domain is missing from the merge');
});

test('the interpolation placeholders of a key match across locales', () => {
  const placeholders = (value: string) =>
    [...value.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
  for (const key of Object.keys(FR_DICT) as (keyof typeof FR_DICT)[]) {
    assert.deepEqual(
      placeholders(FR_DICT[key]),
      placeholders(EN_DICT[key]),
      `'${key}': FR and EN interpolate different placeholders`,
    );
  }
});

test('the English PR to PO desk does not keep French dossier or terrain', () => {
  for (const [key, value] of Object.entries(EN_DICT)) {
    if (!key.startsWith('experience.pr_to_po.')) continue;
    assert.doesNotMatch(value, /\bdossier\b/i, `${key}: EN still says dossier`);
    assert.doesNotMatch(value, /\bterrain\b/i, `${key}: EN still says terrain`);
  }
});

const english = (text: string) => untranslatedInFrench(text).map((hit) => hit.word);

test('a French string that keeps System or Run in English is caught', () => {
  assert.deepEqual(english('Nouveau System'), ['System']);
  assert.deepEqual(english('Registre des Systems'), ['Systems']);
  assert.deepEqual(english('Voir dans Runs →'), ['Runs']);
  assert.deepEqual(english('Ouvrir le Run'), ['Run']);
  // Lower case is English too: « le même run ».
  assert.deepEqual(english('puis reprend sur le même run.'), ['Run']);
  assert.deepEqual(english('Nouvelle automation'), ['automation']);
});

test('the French term, placeholders, identifiers and code are not English copy', () => {
  assert.deepEqual(english('Nouveau système'), []);
  assert.deepEqual(english('Systèmes publiés · Exécutions terminées'), []);
  assert.deepEqual(english('Épinglé par : {systems}'), []);
  assert.deepEqual(english('Exécution {run}'), []);
  assert.deepEqual(english('Clé run_id, mode dry-run, champ system.prompt'), []);
  assert.deepEqual(english('Lancez `npm run build` puis réessayez.'), []);
  // The placeholder is skipped, the visible word is not.
  assert.deepEqual(english('{runs} Runs × {facets} familles'), ['Runs']);
});

test('only concepts whose French term differs carry untranslated forms', () => {
  for (const { word, conceptId, fr } of untranslatedTerms()) {
    const entry = lexiconEntry(conceptId);
    assert.ok(entry, `${conceptId}: unknown concept`);
    assert.notEqual(entry.fr, entry.en, `${conceptId}: product noun, nothing to translate`);
    assert.equal(fr, entry.fr);
    assert.ok(!untranslatedInFrench(entry.fr).length, `${conceptId}: FR term "${fr}" matches "${word}"`);
  }
  for (const noun of ['skill', 'capability', 'flow']) {
    assert.equal(lexiconEntry(noun)?.untranslated, undefined, `${noun} stays a product noun`);
  }
});

test('no French definition keeps an English term', () => {
  for (const entry of UI_LEXICON) {
    assert.deepEqual(english(entry.definition.fr), [], `${entry.id}: French definition`);
  }
});
