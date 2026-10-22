import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Run } from '@app/core/canonical-api.service';
import type { ExperiencePage } from '../runtime/model';
import { boundOutputs, checkOutput, runStanding, runVersionMatches, outputLabel, previewShape } from './test-preview.model';

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

test('preview headings use business titles with localized fallback, never internal ids', () => {
  assert.equal(outputLabel({ id: 'opaque-123', type: 'table', props: { title: 'Dossiers prioritaires' } }), 'Dossiers prioritaires');
  assert.equal(outputLabel({ id: 'opaque-123', type: 'table', props: { title: { $i18n: 'queue', fallback: 'File SAV' } } }), 'File SAV');
  assert.equal(outputLabel({ id: 'opaque-123', type: 'table', props: {} }), '');
});

test('preview distinguishes structured results, zero values and empty lists', () => {
  assert.equal(previewShape([]), 'list');
  assert.equal(previewShape({ count: 0 }), 'record');
  assert.equal(previewShape(0), 'scalar');
  assert.equal(previewShape(false), 'scalar');
});

test('a saved legacy form-result page previews the same unambiguous action as the runtime', () => {
  const page = { id: 'home', title: 'Team', components: [
    { id: 'form', type: 'form', props: { bindingKey: 'team.refresh' } },
    { id: 'status', type: 'runtime_status', props: {} },
    { id: 'result', type: 'result', props: {} },
    { id: 'evidence', type: 'evidence', props: {} },
  ] };
  const before = JSON.stringify(page);
  assert.deepEqual(boundOutputs(page).map(row => [row.componentId, row.bindingKey]), [
    ['status', 'team.refresh'], ['result', 'team.refresh'], ['evidence', 'team.refresh'],
  ]);
  assert.equal(JSON.stringify(page), before);
  const result = boundOutputs(page).find(row => row.componentId === 'result')!;
  assert.deepEqual(checkOutput(result, { id: 'r1', system_id: 's', status: 'completed', output_ref: { updated: 23 } } as Run), { state: 'present', value: { updated: 23 } });
});

test('legacy multi-action output requires an explicit source rather than inventing one', () => {
  const page = { id: 'home', title: 'Team', components: [
    { id: 'refresh', type: 'form', props: { bindingKey: 'team.refresh' } },
    { id: 'close', type: 'action_button', props: { bindingKey: 'team.close' } },
    { id: 'result', type: 'result', props: {} },
    { id: 'evidence', type: 'evidence', props: { sourceComponentId: 'refresh' } },
  ] };
  assert.deepEqual(boundOutputs(page).map(row => [row.componentId, row.bindingKey]), [['evidence', 'team.refresh']]);
});
