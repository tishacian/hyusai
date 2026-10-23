import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  ReviewTimer,
  deadlineState,
  draftDecision,
  draftProblems,
  lostProtectedSpan,
  matrixOf,
  toggleAnnotation,
  type ReviewSetView,
  type ReviewTaxonomy,
} from './review-model';

const TAXONOMY: ReviewTaxonomy = {
  categories: [{ key: 'WT', label: 'Wrong term', severities: ['minor', 'major'] }],
  comment_required_for: ['major'],
};
const SUBJECT = { source: '<b>Frein</b>', candidate: '<b>Brake</b>', protected_spans: ['<b>', '</b>'] };

test('an unchanged value approves, a changed one corrects, reject wins', () => {
  assert.equal(draftDecision(SUBJECT, { value: '<b>Brake</b>', annotations: [], comment: '', reject: false }), 'approve');
  assert.equal(draftDecision(SUBJECT, { value: '<b>Brakes</b>', annotations: [], comment: '', reject: false }), 'correct');
  assert.equal(draftDecision(SUBJECT, { value: '<b>Brake</b>', annotations: [], comment: '', reject: true }), 'reject');
});

test('protected spans must stay, in order', () => {
  assert.equal(lostProtectedSpan(SUBJECT, '<b>Brakes</b>'), null);
  assert.equal(lostProtectedSpan(SUBJECT, 'Brakes</b>'), '<b>');
  assert.equal(lostProtectedSpan(SUBJECT, '</b>Brakes<b>'), '</b>');
});

test('draft problems mirror the server rules', () => {
  const base = { value: '<b>Brake pad</b>', annotations: [], comment: '', reject: false };
  assert.deepEqual(draftProblems(TAXONOMY, SUBJECT, base), []);
  assert.deepEqual(
    draftProblems(TAXONOMY, SUBJECT, { ...base, annotations: [{ category: 'WT', severity: 'major' }] }),
    ['comment_required'],
  );
  assert.deepEqual(draftProblems(TAXONOMY, SUBJECT, { ...base, value: 'Brake pad' }), ['protected_span_lost']);
  assert.deepEqual(
    draftProblems(TAXONOMY, SUBJECT, { ...base, value: '<b>Brake</b>', annotations: [{ category: 'WT', severity: 'minor' }] }),
    ['annotations_on_approve'],
  );
  assert.deepEqual(draftProblems(TAXONOMY, SUBJECT, { ...base, reject: true }), ['comment_required']);
});

test('one annotation per category', () => {
  const once = toggleAnnotation([], 'WT', 'minor');
  const changed = toggleAnnotation(once, 'WT', 'major');
  assert.deepEqual(changed, [{ category: 'WT', severity: 'major' }]);
  assert.deepEqual(toggleAnnotation(changed, 'WT', null), []);
});

test('the timer excludes pauses and restarts after each take', () => {
  let now = 0;
  const timer = new ReviewTimer(() => now);
  timer.start();
  now = 1000;
  timer.pause();
  now = 5000;
  timer.start();
  now = 5500;
  assert.equal(timer.take(), 1500);
  now = 6000;
  assert.equal(timer.take(), 500);
});

test('matrix groups sets on two labels', () => {
  const set = (id: string, lot: string, language: string) =>
    ({ id, group_key: `${lot}:${language}`, group_labels: { lot, language } }) as unknown as ReviewSetView;
  const matrix = matrixOf([set('a', 'L2', 'de'), set('b', 'L1', 'de'), set('c', 'L1', 'it')], 'lot', 'language');
  assert.deepEqual(matrix.rows, ['L1', 'L2']);
  assert.deepEqual(matrix.columns, ['de', 'it']);
  assert.deepEqual(matrix.cell('L1', 'it').map((s) => s.id), ['c']);
  assert.deepEqual(matrix.cell('L2', 'it'), []);
});

test('deadline badge', () => {
  const now = Date.parse('2026-10-23T12:00:00Z');
  assert.equal(deadlineState('2026-10-23T11:00:00', now), 'overdue');
  assert.equal(deadlineState('2026-10-24T06:00:00', now), 'soon');
  assert.equal(deadlineState('2026-10-30T06:00:00', now), 'none');
  assert.equal(deadlineState(null, now), 'none');
});
