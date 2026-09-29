import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  chosenSource,
  clientStepStates,
  compactCardVisible,
  currentClientStep,
  ingestionSettled,
  ingestionSummary,
  isClientJourney,
  journeyAvailable,
  type AdoptionSource,
} from './adoption-journey';

const ready: AdoptionSource = {
  id: 'c-ready',
  slug: 'contrats',
  name: 'Contrats fournisseurs',
  status: 'ready',
  document_count: 14,
  chunk_count: 3480,
};
const empty: AdoptionSource = { ...ready, id: 'c-empty', name: 'Brouillons', status: 'created', document_count: 0, chunk_count: 0 };

test('the server picks the journey: Showcase keeps NorthForge, a client workspace walks its sources', () => {
  assert.equal(isClientJourney({ journey: 'northforge_sources' }), false);
  assert.equal(isClientJourney({ journey: 'client_sources' }), true);
  assert.equal(journeyAvailable({ journey: 'northforge_sources', example_available: true }), true, 'older server');
  assert.equal(journeyAvailable({ journey: 'northforge_sources', example_available: false }), false);
  assert.equal(
    journeyAvailable({ journey: 'client_sources', example_available: true }),
    false,
    'the NorthForge corpus never makes a client journey available',
  );
  assert.equal(journeyAvailable({ journey: 'client_sources', available: true }), true);
  assert.equal(journeyAvailable({ journey: 'northforge_sources', available: false, example_available: true }), false);
  assert.equal(journeyAvailable(null), false);
});

test('no readable source, a dismissal or the flag off hides the compact card', () => {
  const record = { journey: 'client_sources', available: true, dismissed: false };
  assert.equal(compactCardVisible(true, record), true);
  assert.equal(compactCardVisible(true, { ...record, available: false }), false, 'unavailable: nothing, no Showcase redirect');
  assert.equal(compactCardVisible(true, { ...record, dismissed: true }), false);
  assert.equal(compactCardVisible(false, record), false);
  assert.equal(compactCardVisible(true, null), false, 'unknown record: no card flashes in');
});

test('the step machine skips adding documents when the source already has some', () => {
  assert.equal(currentClientStep([], true), 'source');
  assert.equal(currentClientStep(['source'], false), 'documents');
  assert.equal(currentClientStep(['source'], true), 'question', 'documents are optional');
  assert.equal(currentClientStep(['source', 'documents'], false), 'question');
  assert.equal(currentClientStep(['source', 'question'], false), 'decision', 'a later step makes documents moot');
  assert.equal(currentClientStep(['source', 'documents', 'question'], true), 'decision');
  assert.equal(currentClientStep(['source', 'question', 'decision'], true), null, 'the decision ends the journey');
  assert.equal(currentClientStep(['decision'], false), null);

  assert.deepEqual(clientStepStates(['source'], true), {
    source: 'done',
    documents: 'optional',
    question: 'current',
    decision: 'todo',
  });
  assert.deepEqual(clientStepStates([], false), {
    source: 'current',
    documents: 'todo',
    question: 'todo',
    decision: 'todo',
  });
});

test('the member resumes on the source they chose, else on the first ready one', () => {
  const sources = [ready, empty];
  assert.equal(chosenSource({ sources, candidate_collection_id: 'c-ready' })?.id, 'c-ready');
  assert.equal(chosenSource({ sources, candidate_collection_id: 'c-ready', collection_id: 'c-empty' })?.id, 'c-empty');
  assert.equal(chosenSource({ sources, collection_id: 'gone' })?.id, 'c-ready', 'a removed choice falls back');
  assert.equal(chosenSource({ sources: [] }), null);
});

test('every figure comes from the inventory: indexed over total, passages, errors', () => {
  const inventory = {
    status: 'ingesting',
    source_count: 14,
    chunk_count: 3480,
    error_sources: 0,
    by_status: { ready: 11, deduplicated: 1, ingesting: 1, queued: 1 },
    sources: [{ id: 's1', filename: 'contrat-atex-2026.pdf', status: 'ready' }],
  };
  assert.deepEqual(ingestionSummary(inventory), { total: 14, indexed: 12, pending: 2, errors: 0, passages: 3480 });
  assert.equal(ingestionSettled(inventory), false);
  const done = { ...inventory, status: 'ready', by_status: { ready: 13, error: 1 }, error_sources: 1 };
  assert.deepEqual(ingestionSummary(done), { total: 14, indexed: 13, pending: 0, errors: 1, passages: 3480 });
  assert.equal(ingestionSettled(done), true);
  assert.deepEqual(ingestionSummary(null), { total: 0, indexed: 0, pending: 0, errors: 0, passages: 0 });
  assert.equal(ingestionSettled(null), false, 'unknown: keep asking');
  // Without per-status counts the listed files still tell the truth.
  assert.deepEqual(
    ingestionSummary({ sources: [{ id: 'a', filename: 'a.pdf', status: 'error' }, { id: 'b', filename: 'b.pdf', status: 'queued' }] }),
    { total: 2, indexed: 0, pending: 1, errors: 1, passages: 0 },
  );
});
