import test from 'node:test';
import assert from 'node:assert/strict';
import { guidedJudgeIdentity, judgeOutputPaths, nextRubricVersion } from './typed-judge-guidance';
import { newJudgeDraft } from './dataops.models';

test('new rubric is derived without changing an existing identifier', () => {
  assert.equal(guidedJudgeIdentity(newJudgeDraft(), 'system', 'judge').rubric_id, 'system:judge');
  assert.equal(guidedJudgeIdentity({ ...newJudgeDraft(), rubric_id: 'historic' }, 'system', 'judge').rubric_id, 'historic');
  assert.equal(nextRubricVersion('3'), '4');
});
test('paths are selected from the exact contract and escape JSON pointer keys', () => {
  assert.deepEqual(judgeOutputPaths({ type: 'object', properties: { result: { properties: { 'a/b~c': { type: 'string' } } } } }), ['/result', '/result/a~1b~0c']);
  assert.deepEqual(judgeOutputPaths({}), []);
});
