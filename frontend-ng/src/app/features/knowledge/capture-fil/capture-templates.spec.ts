import assert from 'node:assert/strict';
import test from 'node:test';
import {
  FSE_INTERVENTION_V1,
  captureTemplateSystemReady,
} from './capture-templates';

test('FSE template plan remains blocked until its System is resolved', () => {
  assert.equal(captureTemplateSystemReady(FSE_INTERVENTION_V1, null), false);
  assert.equal(captureTemplateSystemReady(FSE_INTERVENTION_V1, ''), false);
  assert.equal(captureTemplateSystemReady(FSE_INTERVENTION_V1, 'system-fse'), true);
  assert.equal(captureTemplateSystemReady(null, null), true);
});
