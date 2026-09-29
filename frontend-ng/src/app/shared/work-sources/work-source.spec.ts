import assert from 'node:assert/strict';
import test from 'node:test';

import {
  documentKind,
  filePath,
  isUnavailableStatus,
  passageQuery,
  previewPath,
  sourceStep,
  workSourceRef,
  workSourceView,
  type CitedPassageResponse,
} from './work-source';
import { pdfFindSegments } from '@app/shared/document-preview/highlight-text.util';

const STREAMED = {
  document_id: 'doc-atex',
  collection: 'contrats-fournisseurs',
  title: 'contrat-atex-2026.pdf',
  page: 3,
  score: 0.91,
  snippet: '3.1 Tout dépassement du plafond de commande exige la validation écrite de l’acheteur responsable.',
  metadata: { chunk_index: 12 },
};

test('a streamed source maps to its document, page, chunk, collection and full passage', () => {
  const ref = workSourceRef(STREAMED, 1, { cited: true, collectionLabel: 'Contrats fournisseurs' });
  assert.deepEqual(ref, {
    n: 1,
    documentId: 'doc-atex',
    collection: 'contrats-fournisseurs',
    collectionLabel: 'Contrats fournisseurs',
    title: 'contrat-atex-2026.pdf',
    filename: null,
    page: 3,
    chunkIndex: 12,
    passage: STREAMED.snippet,
    cited: true,
  });
  // Metadata is read when the top level is silent; a bad page is no page.
  const bare = workSourceRef(
    { metadata: { document_id: 'd2', filename: 'plan.docx', collection_name: 'c', page: '0', chunk_index: '4' }, content: '  texte  ' },
    2,
    { cited: false },
  );
  assert.equal(bare.documentId, 'd2');
  assert.equal(bare.title, 'plan.docx');
  assert.equal(bare.collection, 'c');
  assert.equal(bare.page, null);
  assert.equal(bare.chunkIndex, 4);
  assert.equal(bare.passage, 'texte');
  assert.equal(documentKind('contrat-atex-2026.pdf'), 'PDF');
  assert.equal(documentKind('Notes'), null);
});

test('the passage read names the document, its chunk, page and the start of the quote', () => {
  const ref = workSourceRef(STREAMED, 1, { cited: true });
  assert.deepEqual(passageQuery(ref), {
    collection_name: 'contrats-fournisseurs',
    chunk_index: '12',
    page: '3',
    hint: STREAMED.snippet,
  });
  // No document or no collection: nothing to ask, the panel shows what the answer received.
  assert.equal(passageQuery(workSourceRef({ title: 'web', snippet: 'un extrait suffisamment long' }, 1, { cited: true })), null);
});

test('the server passage wins, with its neighbours, page, collection name and a previewable page', () => {
  const ref = workSourceRef(STREAMED, 2, { cited: true, collectionLabel: 'contrats-fournisseurs' });
  const response: CitedPassageResponse = {
    document_id: 'doc-atex',
    filename: 'contrat-atex-2026.pdf',
    collection: { id: 'c1', slug: 'contrats-fournisseurs', name: 'Contrats fournisseurs' },
    passage: { text: '3.1 Tout dépassement du plafond… (texte complet)', truncated: false, chunk_index: 12, page: 4 },
    before: '2.9 Les fournisseurs sont référencés',
    after: '3.2 La validation est archivée.',
    preview_available: true,
  };
  const view = workSourceView(ref, 3, response);
  assert.equal(view.n, 2);
  assert.equal(view.total, 3);
  assert.equal(view.kind, 'PDF');
  assert.equal(view.page, 4);
  assert.equal(view.collection, 'Contrats fournisseurs');
  assert.equal(view.passage, '3.1 Tout dépassement du plafond… (texte complet)');
  assert.equal(view.before, '2.9 Les fournisseurs sont référencés');
  assert.equal(view.after, '3.2 La validation est archivée.');
  assert.equal(view.unverified, false);
  assert.deepEqual(view.preview, {
    documentId: 'doc-atex',
    collection: 'contrats-fournisseurs',
    filename: 'contrat-atex-2026.pdf',
    page: 4,
    highlight: '3.1 Tout dépassement du plafond… (texte complet)',
  });
  assert.equal(
    previewPath(view.preview!),
    '/documents/doc-atex/rich-preview?collection_name=contrats-fournisseurs&filename=contrat-atex-2026.pdf',
  );
  assert.equal(
    filePath(view.preview!),
    '/documents/doc-atex/raw?collection_name=contrats-fournisseurs&disposition=inline&filename=contrat-atex-2026.pdf',
  );
});

test('no original, no page promised; no located passage, no invented context', () => {
  const ref = workSourceRef(STREAMED, 1, { cited: true });
  const view = workSourceView(ref, 1, {
    document_id: 'doc-atex',
    filename: 'contrat-atex-2026.pdf',
    passage: null,
    before: 'ne doit pas apparaître',
    after: 'ne doit pas apparaître',
    preview_available: false,
  });
  assert.equal(view.preview, null);
  assert.equal(view.passage, STREAMED.snippet);
  assert.equal(view.before, null);
  assert.equal(view.after, null);
  assert.equal(view.page, 3);
});

test('an unreachable server keeps the answer’s passage, flagged unverified, without a page', () => {
  const view = workSourceView(workSourceRef(STREAMED, 1, { cited: false }), 2, null);
  assert.equal(view.unverified, true);
  assert.equal(view.passage, STREAMED.snippet);
  assert.equal(view.preview, null);
  assert.equal(view.cited, false);
});

test('deleted or withdrawn sources are unavailable; other failures are not', () => {
  assert.equal(isUnavailableStatus(404), true);
  assert.equal(isUnavailableStatus(403), true);
  assert.equal(isUnavailableStatus(410), true);
  assert.equal(isUnavailableStatus(500), false);
  assert.equal(isUnavailableStatus(0), false);
  assert.equal(isUnavailableStatus(undefined), false);
});

test('moving between sources stops at both ends', () => {
  assert.deepEqual(sourceStep(1, 3), { n: 1, total: 3, previous: null, next: 2 });
  assert.deepEqual(sourceStep(2, 3), { n: 2, total: 3, previous: 1, next: 3 });
  assert.deepEqual(sourceStep(3, 3), { n: 3, total: 3, previous: 2, next: null });
  assert.deepEqual(sourceStep(9, 3), { n: 3, total: 3, previous: 2, next: null });
  assert.deepEqual(sourceStep(1, 1), { n: 1, total: 1, previous: null, next: null });
});

test('the page marks the whole passage in find segments, never a common fragment', () => {
  const passage = "3.1 Tout dépassement du plafond de commande exige la validation écrite de l'acheteur responsable.";
  const segments = pdfFindSegments(passage);
  assert.deepEqual(segments, ['3.1 Tout dépassement du plafond de commande exige la', "validation écrite de l'acheteur responsable."]);
  // End to end: the segments rebuild the passage, the last words included.
  assert.equal(segments.join(' '), passage);
  // A short tail joins the previous piece instead of standing alone.
  const tail = pdfFindSegments('aaaa bbbb cccc dddd eeee ffff gggg hhhh iiii jjjj kkkk llll mm nn', 60, 16);
  assert.ok(tail.every((segment) => segment.length >= 16));
  assert.deepEqual(pdfFindSegments('court'), ['court']);
  assert.deepEqual(pdfFindSegments('   '), []);
});
