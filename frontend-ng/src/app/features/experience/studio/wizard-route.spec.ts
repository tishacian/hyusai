import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  resumeStep,
  slugProblem,
  slugProblemFromCode,
  wizardQueryParams,
  wizardReturnTo,
  wizardStepFromParam,
  wizardUrl,
} from './wizard-route';

test('the step travels in the address by name', () => {
  assert.equal(wizardStepFromParam('bind'), 2);
  assert.equal(wizardStepFromParam('3'), null);
  assert.deepEqual(wizardQueryParams('exp-1', 3), { draft: 'exp-1', step: 'access' });
  assert.deepEqual(wizardQueryParams(null, 1), { step: 'identity' });
  assert.equal(wizardUrl('exp 1', 2), '/create/apps/new?draft=exp+1&step=bind');
});

test('resuming never jumps past the step the author reached', () => {
  assert.equal(resumeStep(2, null), 2);
  assert.equal(resumeStep(2, 1), 1);
  assert.equal(resumeStep(2, 3), 2);
  assert.equal(resumeStep(null, 3), 1);
  assert.equal(resumeStep(9, null), 1);
});

test('only a wizard address is a way back', () => {
  assert.equal(wizardReturnTo('/create/apps/new?draft=a&step=bind'), '/create/apps/new?draft=a&step=bind');
  assert.equal(wizardReturnTo('/create/apps/new'), null);
  assert.equal(wizardReturnTo('https://evil.example/create/apps/new?x'), null);
  assert.equal(wizardReturnTo('/systems'), null);
});

test('the address follows the server rule and its refusals are explained', () => {
  assert.equal(slugProblem('procedures'), null);
  assert.equal(slugProblem('Procédures'), 'invalid');
  assert.equal(slugProblem('1-app'), 'invalid');
  assert.equal(slugProblem('procedures', ['procedures']), 'taken');
  assert.equal(slugProblemFromCode('EXPERIENCE_SLUG_INVALID'), 'invalid');
  assert.equal(slugProblemFromCode('EXPERIENCE_SLUG_EXISTS'), 'taken');
  assert.equal(slugProblemFromCode('EXPERIENCE_DEPLOYED_SLUG_IMMUTABLE'), 'immutable');
  assert.equal(slugProblemFromCode('OTHER'), null);
});
