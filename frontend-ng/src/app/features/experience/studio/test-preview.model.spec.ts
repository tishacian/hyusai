import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Run } from '@app/core/canonical-api.service';
import type { ExperiencePage } from '../runtime/model';
import { boundOutputs, checkOutput, runStanding, runVersionMatches } from './test-preview.model';

const PAGE = {
  id: 'home',
  title: 'Home',
  components: [
    { id: 'ask', type: 'form', props: { bindingKey: 'procedures.ask' } },
    { id: 'answer', type: 'text', props: { dataBinding: { source: 'run-output', componentId: 'ask', selector: 'answer' } } },
    { id: 'sources', type: 'table', props: { dataBinding: { source: 'run-output', componentId: 'ask', selector: 'citations' } } },
    { id: 'kpi', type: 'kpi', props: { queryBinding: { source: 'system-binding', bindingKey: 'procedures.stats', selector: 'count' } } },
    { id: 'title', type: 'header', props: {} },
  ],
} as unknown as ExperiencePage;

test('bound outputs are found through the component that calls the System', () => {
  assert.deepEqual(boundOutputs(PAGE).map((row) => [row.componentId, row.bindingKey, row.selector]), [
    ['answer', 'procedures.ask', 'answer'],
    ['sources', 'procedures.ask', 'citations'],
    ['kpi', 'procedures.stats', 'count'],
  ]);
});

test('a missing output is reported, never filled', () => {
  const run = { id: 'r1', system_id: 's', status: 'completed', output_ref: { answer: 'Use form B.' } } as Run;
  const [answer, sources] = boundOutputs(PAGE);
  assert.deepEqual(checkOutput(answer!, run), { state: 'present', value: 'Use form B.' });
  assert.equal(checkOutput(sources!, run).state, 'missing');
});

test('a result awaiting review is not a finished one, and a draft version is told apart', () => {
  assert.equal(runStanding({ status: 'hitl_pending' }), 'review');
  assert.equal(runStanding({ status: 'completed' }), 'completed');
  assert.equal(runStanding({ status: 'cancelled' }), 'failed');
  assert.equal(runStanding({ status: 'running' }), 'running');
  assert.equal(runVersionMatches({ flow_version_id: 'v1' }, 'v1'), true);
  assert.equal(runVersionMatches({ flow_version_id: 'v0' }, 'v1'), false);
  assert.equal(runVersionMatches({ flow_version_id: null }, 'v1'), null);
});
