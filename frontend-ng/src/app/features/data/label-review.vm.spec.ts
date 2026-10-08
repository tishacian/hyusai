import assert from 'node:assert/strict';
import { test } from 'node:test';
import { labelReviewSubmission, sameLabelReview, updateLabelCorrection, type LabelReviewPage } from './label-review.vm';

const page: LabelReviewPage = { decision_id: 'decision', dataset_id: 'dataset', dataset_name: 'Tickets', source_version: 2, sha256: 'hash', label_column: 'topic', labels: ['yes', 'no'], text_columns: ['message'], total: 51, offset: 0, rows: [{ row_id: 0, values: { message: 'text' }, label: 'yes' }] };

test('multi-page corrections use stable row IDs and restoring the original removes the change', () => {
  const one = updateLabelCorrection(page, {}, 0, 'no');
  const nextPage = { ...page, offset: 50, rows: [{ row_id: 50, values: { message: 'last' }, label: 'no' }] };
  const both = updateLabelCorrection(nextPage, one, 50, 'yes');
  assert.deepEqual(labelReviewSubmission(nextPage, both, true), {
    dataset_id: 'dataset', sha256: 'hash', acknowledged: true,
    corrections: [{ row_id: 0, label: 'no' }, { row_id: 50, label: 'yes' }],
  });
  assert.deepEqual(updateLabelCorrection(page, both, 0, 'yes'), { 50: 'yes' });
  assert.deepEqual(updateLabelCorrection(page, one, 0, 'injected'), one);
  assert.deepEqual(updateLabelCorrection(page, one, 100, 'yes'), one);
});

test('confirmation is explicit and invalid or out-of-bounds corrections cannot be submitted', () => {
  assert.equal(labelReviewSubmission(page, {}, false), null);
  assert.equal(labelReviewSubmission(null, {}, true), null);
  assert.equal(labelReviewSubmission(page, { 51: 'yes' }, true), null);
  assert.equal(labelReviewSubmission(page, { 0: 'unknown' }, true), null);
  assert.equal(labelReviewSubmission(page, { '-1': 'yes' }, true), null);
  assert.deepEqual(labelReviewSubmission(page, {}, true)?.corrections, []);
});

test('pagination never crosses a changed dataset, version, decision or class contract', () => {
  assert.equal(sameLabelReview(page, { ...page, offset: 50, rows: [] }), true);
  for (const patch of [{ dataset_id: 'other' }, { sha256: 'changed' }, { source_version: 3 }, { decision_id: 'new' }, { total: 52 }, { labels: ['unknown'] }]) {
    assert.equal(sameLabelReview(page, { ...page, ...patch }), false);
  }
});
