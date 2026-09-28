import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  advancedBehindComposer,
  answerProofCounts,
  classifyProofSources,
  deriveWorkTrace,
  markSupportingSentence,
  reduceProofRail,
  type ProofRailState,
} from './chat-proof';

test('the trace shows only phases that received a real step, the latest one current', () => {
  const trace = deriveWorkTrace(
    [
      { type: 'query_analysis', status: 'completed' },
      { type: 'retrieve', status: 'completed' },
      { type: 'thought', status: 'active' },
    ],
    { streaming: true },
  );
  assert.deepEqual(trace.phases, [
    { key: 'search', status: 'done' },
    { key: 'read', status: 'current' },
  ]);
  assert.equal(trace.current, 'read');
});

test('no step, no phase: the trace never invents a pseudo-step', () => {
  assert.deepEqual(deriveWorkTrace([], { streaming: true }), { phases: [], current: null });
  assert.deepEqual(deriveWorkTrace([{ type: 'evaluation' }], { streaming: true }).phases, []);
});

test('streamed tokens count as writing even before a synthesis step arrives', () => {
  const trace = deriveWorkTrace([{ type: 'retrieve', status: 'completed' }], { streaming: true, textStarted: true });
  assert.deepEqual(trace.phases.map((phase) => `${phase.key}:${phase.status}`), ['search:done', 'compose:current']);
});

test('once the answer is done every phase is done, a failed one stays failed', () => {
  const trace = deriveWorkTrace(
    [
      { type: 'retrieve', status: 'error' },
      { type: 'synthesis', status: 'completed' },
    ],
    { streaming: false },
  );
  assert.equal(trace.current, null);
  assert.deepEqual(trace.phases, [
    { key: 'search', status: 'error' },
    { key: 'compose', status: 'done' },
  ]);
});

test('cited and read-not-cited sources are split by the numbers the answer cites', () => {
  const groups = classifyProofSources(['a', 'b', 'c'], new Set([1, 3, 7]));
  assert.deepEqual(groups.cited, [{ n: 1, source: 'a' }, { n: 3, source: 'c' }]);
  assert.deepEqual(groups.readNotCited, [{ n: 2, source: 'b' }]);
});

test('the meta line only counts citations that resolve, and claims nothing without sources', () => {
  assert.deepEqual(answerProofCounts(['a', 'b', 'c'], new Set([1, 2, 9])), { passages: 3, cited: 2 });
  assert.equal(answerProofCounts([], new Set([1])), null);
  assert.equal(answerProofCounts(undefined, new Set()), null);
});

test('« Avancé » hides the controls for every mode but builder, and only in the thread', () => {
  assert.equal(advancedBehindComposer(true, 'executive'), true);
  assert.equal(advancedBehindComposer(true, 'operator'), true);
  assert.equal(advancedBehindComposer(true, 'builder'), false);
  assert.equal(advancedBehindComposer(false, 'executive'), false);
});

test('a citation opens the rail; pointer animates the first opening only; close resets', () => {
  const closed: ProofRailState = { selection: null, animate: false };
  const first = { msgId: 'm1', hostId: 'm1', n: 1 };
  const opened = reduceProofRail(closed, { kind: 'open', selection: first, byPointer: true, valid: true });
  assert.deepEqual(opened, { selection: first, animate: true });

  const second = { msgId: 'm1', hostId: 'm1', n: 2 };
  const switched = reduceProofRail(opened, { kind: 'open', selection: second, byPointer: true, valid: true });
  assert.deepEqual(switched, { selection: second, animate: false });

  const byKeyboard = reduceProofRail(closed, { kind: 'open', selection: first, byPointer: false, valid: true });
  assert.equal(byKeyboard.animate, false);

  assert.equal(reduceProofRail(switched, { kind: 'open', selection: first, byPointer: true, valid: false }), switched);
  assert.deepEqual(reduceProofRail(switched, { kind: 'close' }), closed);
});

test('the proof marks the supporting sentence, or the whole passage when unsure', () => {
  const passage = '3.1 Une exécution terminée est immuable. 3.2 La relance réutilise exactement les entrées de l’exécution d’origine. 3.3 Les journaux restent.';
  const parts = markSupportingSentence(passage, 'La relance crée une nouvelle exécution liée, avec exactement les mêmes entrées');
  assert.equal(parts.mark, '3.2 La relance réutilise exactement les entrées de l’exécution d’origine.');
  assert.equal(parts.before + parts.mark + parts.after, passage);

  assert.deepEqual(markSupportingSentence(passage, 'Sans rapport'), { before: '', mark: passage, after: '' });
  assert.deepEqual(markSupportingSentence('Une seule phrase ici', 'phrase seule'), { before: '', mark: 'Une seule phrase ici', after: '' });
});
