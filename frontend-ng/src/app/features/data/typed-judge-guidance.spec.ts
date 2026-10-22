import test from 'node:test';
import assert from 'node:assert/strict';
import { guidedJudgeIdentity, judgeOutputPaths, nextRubricVersion, selectJudgeModel } from './typed-judge-guidance';
import { newJudgeDraft } from './dataops.models';
import { selectableEvaluationModel, selectableTextModel, type ModelCatalogEntry } from '@app/core/model-catalog';

test('new rubric is derived without changing an existing identifier', () => {
  assert.equal(guidedJudgeIdentity(newJudgeDraft(), 'system', 'judge').rubric_id, 'system:judge');
  assert.equal(guidedJudgeIdentity({ ...newJudgeDraft(), rubric_id: 'historic' }, 'system', 'judge').rubric_id, 'historic');
  assert.equal(nextRubricVersion('3'), '4');
});
test('paths are selected from the exact contract and escape JSON pointer keys', () => {
  assert.deepEqual(judgeOutputPaths({ type: 'object', properties: { result: { properties: { 'a/b~c': { type: 'string' } } } } }), ['/result', '/result/a~1b~0c']);
  assert.deepEqual(judgeOutputPaths({}), []);
});

const jev: ModelCatalogEntry = {provider: 'typesafe', model: 'jev-1.13.0', configured: true, discovered: true, status: 'active', runtime_available: false, typed_decisions_available: true, capabilities: ['typed_decisions'], compatibility: 'typed_decisions'};
test('typed-only models can evaluate but never become text generation or chat fallbacks', () => {
  assert.equal(selectableEvaluationModel(jev), true);
  assert.equal(selectableTextModel(jev), false);
  assert.equal(selectableEvaluationModel({...jev, configured: false}), false);
  assert.equal(selectableEvaluationModel({...jev, typed_decisions_available: false}), false);
  assert.equal(selectableEvaluationModel({...jev, compatibility: 'unknown'}), false);
});
test('changing evaluator preserves rubric requirements and sources while invalidating the old tariff', () => {
  const original = newJudgeDraft();
  original.tariff = {provider: 'openai', model: 'gpt-5', reference: 'openai-prices', input_per_million: 1.25, output_per_million: 10, currency: 'USD'};
  original.run_evidence = {sources: [{id: 'proposal', skill_slug: 'proposal', paths: ['/summary'], required: true}], native_refs: []};
  const next = selectJudgeModel(original, jev);
  assert.deepEqual(next.questions, original.questions);
  assert.equal(next.questions[0].requires_evidence, true);
  assert.deepEqual(next.run_evidence, original.run_evidence);
  assert.deepEqual(next.tariff, {provider: 'typesafe', model: 'jev-1.13.0', reference: '', input_per_million: 0, output_per_million: 0, currency: 'USD'});
  assert.equal(original.tariff.reference, 'openai-prices');
  next.tariff.reference = 'typesafe-prices';
  assert.equal(selectJudgeModel(next, jev), next, 'reselecting the same engine keeps its reviewed price');
  assert.equal(selectJudgeModel(original, {...jev, configured: false}), original);
});
