import assert from 'node:assert/strict';
import { test } from 'node:test';
import { runSection, runSectionLabels } from './run-sections';
test('links preserve Flow, timeline, judgments and legacy detail destinations', () => {
  assert.equal(runSection('flow', 'quality'), 'execution');
  assert.equal(runSection(null, 'trace'), 'execution');
  assert.equal(runSection(null, 'quality'), 'quality');
  assert.equal(runSection(null, 'usage'), 'usage');
  for (const facet of [null, 'overview', 'payloads', 'checkpoints', 'forged']) assert.equal(runSection(null, facet), 'result');
});
test('run sections have explicit French and English labels', () => {
  assert.equal(runSectionLabels('fr-FR').quality, 'Qualité');
  assert.equal(runSectionLabels('en-GB').usage, 'Usage and costs');
});
