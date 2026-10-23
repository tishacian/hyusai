import assert from 'node:assert/strict';
import { test } from 'node:test';
import { EXPERIENCE_EN, EXPERIENCE_FR } from '@app/core/i18n/experience.dict';
import { readyIssueDetail } from './studio-publish';

const fill = (text: string, params: Record<string, string | number>) =>
  Object.entries(params).reduce((out, [name, value]) => out.replace(`{${name}}`, String(value)), text);

test('an unfed step input names the step, its skill and the field, in FR and EN', () => {
  const issue = { code: 'STEP_INPUT_UNFED', binding_key: 'home.app.objective', step: 1, skill: 'LLM', field: 'prompt' };
  const { params, context } = readyIssueDetail(issue);
  assert.equal(context, 'home.app.objective');
  const key = 'experience.publish.issue.step_input_unfed';
  assert.match(fill((EXPERIENCE_FR as Record<string, string>)[key], params), /^L’étape 1 \(LLM\) exige le champ « prompt »/);
  assert.match(fill((EXPERIENCE_EN as Record<string, string>)[key], params), /^Step 1 \(LLM\) requires the field “prompt”/);
});

test('other issues keep their component, binding or path as context', () => {
  assert.deepEqual(readyIssueDetail({ code: 'BINDING_UNUSED', binding_key: 'k' }), { params: {}, context: 'k' });
  assert.deepEqual(readyIssueDetail({ code: 'X', component_id: 'c', binding_key: 'k' }), { params: {}, context: 'c' });
});
