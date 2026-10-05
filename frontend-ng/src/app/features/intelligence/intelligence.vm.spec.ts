import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { GOVERNANCE_EN, GOVERNANCE_FR } from '../../core/i18n/governance.dict';
import {
  batchErrorMessage,
  knowledgeCollection,
  needsSetup,
  progressLabel,
  schedulerInterval,
  setupSteps,
  watchRows,
  type Translate,
} from './intelligence.vm';

const translator = (dictionary: Record<string, string>): Translate => (key, params) => {
  let value = dictionary[key] ?? key;
  for (const [name, replacement] of Object.entries(params ?? {})) {
    value = value.replaceAll(`{${name}}`, String(replacement));
  }
  return value;
};

test('the watch list is exactly what the server marked, with no fallback', () => {
  assert.deepEqual(watchRows({ systems: [], can_create: true }, 'No measure'), []);
  assert.deepEqual(watchRows(null, 'No measure'), []);
  const rows = watchRows(
    {
      can_create: false,
      systems: [
        { id: 'sys-1', name: 'News Lab', status: 'ACTIVE', objective: '  ', created_at: '2026-10-01' },
        { id: 'sys-2', name: '', status: null, objective: 'Watch retail', updated_at: '2026-10-02' },
      ],
    },
    'No measure',
  );
  assert.deepEqual(rows, [
    { id: 'sys-1', systemId: 'sys-1', name: 'News Lab', status: 'active', measure: 'No measure', updatedAt: '2026-10-01' },
    { id: 'sys-2', systemId: 'sys-2', name: 'sys-2', status: 'draft', measure: 'Watch retail', updatedAt: '2026-10-02' },
  ]);
});

test('the setup guide asks for a feed and a target until both exist', () => {
  assert.deepEqual(setupSteps(0, 0), [
    { key: 'feed', done: false },
    { key: 'target', done: false },
  ]);
  assert.equal(needsSetup(1, 0), true);
  assert.equal(needsSetup(0, 2), true);
  assert.equal(needsSetup(1, 1), false);
});

test('the knowledge collection comes from the dashboard, never a hard-coded slug', () => {
  assert.equal(knowledgeCollection(null), null);
  assert.equal(knowledgeCollection({}), null);
  assert.deepEqual(
    knowledgeCollection({ knowledge_collection: { slug: 'workspace-intelligence', name: 'Workspace intelligence' } }),
    { slug: 'workspace-intelligence', name: 'Workspace intelligence' },
  );
  assert.deepEqual(
    knowledgeCollection({ synthesis: { knowledge_reference: { recommended_collection: 'own-collection' } } }),
    { slug: 'own-collection', name: 'own-collection' },
  );
});

test('server refusals and progress read in both languages', () => {
  for (const dictionary of [GOVERNANCE_FR, GOVERNANCE_EN] as Record<string, string>[]) {
    const t = translator(dictionary);
    for (const code of ['no_feed', 'no_target', 'workspace_required']) {
      const message = batchErrorMessage({ type: 'batch_error', code, message: 'raw server text' }, t);
      assert.equal(message, dictionary[`intelligence.newsLab.error.${code}`]);
    }
    assert.equal(batchErrorMessage({ type: 'batch_error', message: 'Boom' }, t), 'Boom');
    assert.equal(batchErrorMessage({ type: 'batch_error' }, t), dictionary['intelligence.newsLab.error.unknown']);
    for (const evt of [
      { type: 'batch_start', batch_id: 'abc' },
      { type: 'batch_fetch', source: 'Feed' },
      { type: 'batch_analyze' },
      { type: 'run_started', run_id: '0123456789' },
      { type: 'batch_complete', total_articles: 3, analyzed: 2 },
      { type: 'knowledge_sync_started', collection_slug: 'workspace-intelligence' },
      { type: 'run_completed', run_id: '0123456789', status: 'completed' },
      { type: 'batch_error', code: 'no_feed' },
    ]) {
      const label = progressLabel(evt, t);
      assert.ok(label && !label.startsWith('intelligence.'), `${evt.type} → ${label}`);
    }
  }
  assert.notEqual(
    progressLabel({ type: 'batch_analyze' }, translator(GOVERNANCE_FR)),
    progressLabel({ type: 'batch_analyze' }, translator(GOVERNANCE_EN)),
  );
});

test('scheduler intervals are compact', () => {
  assert.equal(schedulerInterval(43200), '12h');
  assert.equal(schedulerInterval(900), '15m');
  assert.equal(schedulerInterval(45), '45s');
  assert.equal(schedulerInterval(undefined), '—');
});

test('News Lab copy goes through the dictionary and names no customer collection', () => {
  const source = readFileSync(
    join(process.cwd(), 'src/app/features/intelligence/news-lab.component.ts'),
    'utf8',
  );
  assert.doesNotMatch(source, /sentinel|open-intelligence/i);
  for (const literal of ['Run analysis', 'Knowledge target', 'Live feed', 'No articles yet', 'Backend defaults will apply']) {
    assert.ok(!source.includes(literal), literal);
  }
  // Literal keys only; a key completed at runtime ends with a dot here.
  const keys = [...source.matchAll(/'(intelligence\.newsLab\.[a-zA-Z_.]*[a-zA-Z_])'/g)].map((m) => m[1]);
  assert.ok(keys.length > 40);
  for (const key of keys) {
    assert.ok(key in GOVERNANCE_FR && key in GOVERNANCE_EN, key);
  }
});
