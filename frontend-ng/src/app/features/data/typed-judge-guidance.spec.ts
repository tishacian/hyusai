import test from 'node:test';
import assert from 'node:assert/strict';
import { guidedJudgeIdentity, judgeOutputPaths, nextRubricVersion, selectExplicitJudgeModel, selectJudgeModel } from './typed-judge-guidance';
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

test('an explicit version outside the catalogue preserves evidence and resets prices without claiming discovery', () => {
  const original = selectJudgeModel(newJudgeDraft(), {...jev, model: 'jev-latest'});
  original.tariff.reference = 'reviewed-alias-price';
  original.tariff.input_per_million = 0.042;
  const catalogue = [{...jev, model: 'jev-latest'}];
  const next = selectExplicitJudgeModel(original, catalogue, 'jev-1.13.0');
  assert.equal(next.tariff.model, 'jev-1.13.0');
  assert.equal(next.tariff.reference, '');
  assert.equal(next.tariff.input_per_million, 0);
  assert.deepEqual(next.questions, original.questions);
  assert.equal(next.questions[0].requires_evidence, true);
  assert.equal(catalogue[0].model, 'jev-latest');
  assert.equal(catalogue.length, 1, 'manual entry never invents a discovered catalogue item');
  next.tariff.reference = 'pinned-version-price';
  assert.equal(selectExplicitJudgeModel(next, catalogue, 'jev-1.13.0'), next);
});

test('explicit model entry requires a configured evaluation provider and a valid identifier', () => {
  const original = selectJudgeModel(newJudgeDraft(), jev);
  for (const name of ['', ' jev-1.13.0', 'jev latest', 'jev\n', 'x'.repeat(201)]) {
    assert.equal(selectExplicitJudgeModel(original, [jev], name), original);
  }
  assert.equal(selectExplicitJudgeModel(original, [{...jev, configured: false}], 'jev-1.14.0'), original);
  assert.equal(selectExplicitJudgeModel(original, [{...jev, provider: 'openai'}], 'jev-1.14.0'), original);
});
