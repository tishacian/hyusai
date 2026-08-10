import '@angular/compiler';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import {
  isRunnableWorkbenchSkillNode,
  parseWorkbenchGoldenSet,
  parseWorkbenchObject,
} from './flow-workbench-panel.component';

const PANEL_SOURCE = readFileSync(
  join(
    process.cwd(),
    'src/app/features/orchestration/flow/flow-workbench-panel.component.ts',
  ),
  'utf8',
);

test('workbench JSON object parser accepts only a top-level object', () => {
  assert.deepEqual(parseWorkbenchObject('{"prompt":"hello","context":{"case":42}}'), {
    ok: true,
    value: { prompt: 'hello', context: { case: 42 } },
  });

  for (const invalid of ['not-json', 'null', '[]', '"text"', '42']) {
    const result = parseWorkbenchObject(invalid);
    assert.equal(result.ok, false, invalid);
  }
});

test('golden-set parser preserves expected values and enforces the bounded wire contract', () => {
  assert.deepEqual(
    parseWorkbenchGoldenSet(JSON.stringify([
      { id: 'case-a', input_ref: { query: 'A' }, expected: false },
      { id: 'case-b', input_ref: { query: 'B', context: {} } },
    ])),
    {
      ok: true,
      value: [
        { id: 'case-a', input_ref: { query: 'A' }, expected: false },
        { id: 'case-b', input_ref: { query: 'B', context: {} } },
      ],
    },
  );

  const twenty = Array.from({ length: 20 }, (_, index) => ({
    id: `case-${index}`,
    input_ref: { query: String(index) },
  }));
  assert.equal(parseWorkbenchGoldenSet(JSON.stringify(twenty)).ok, true);
  assert.equal(
    parseWorkbenchGoldenSet(JSON.stringify([...twenty, { id: 'case-20', input_ref: {} }])).ok,
    false,
  );
});

test('golden-set parser rejects ambiguous ids and malformed input_ref values', () => {
  const invalidSets: unknown[] = [
    [],
    {},
    [{ id: '', input_ref: {} }],
    [{ id: ' padded ', input_ref: {} }],
    [{ id: 'same', input_ref: {} }, { id: 'same', input_ref: {} }],
    [{ id: 'case', input_ref: [] }],
    [{ id: 'case', input_ref: null }],
    [{ id: 'case' }],
    ['case'],
  ];
  for (const value of invalidSets) {
    const result = parseWorkbenchGoldenSet(JSON.stringify(value));
    assert.equal(result.ok, false, JSON.stringify(value));
  }
  assert.equal(parseWorkbenchGoldenSet('not-json').ok, false);
});

test('isolated-node affordance accepts only task nodes with one coherent Skill slug', () => {
  assert.equal(isRunnableWorkbenchSkillNode({
    id: 'bound',
    type: 'skill',
    kind: 'task',
    config: { skill_slug: 'answer' },
  }), true);
  assert.equal(isRunnableWorkbenchSkillNode({
    id: 'historical-bound',
    type: 'skill',
    kind: 'task',
    config: { skill: { slug: 'answer' } },
    data: { bound_skill_slug: 'answer' },
  }), true);
  assert.equal(isRunnableWorkbenchSkillNode({
    id: 'unbound',
    type: 'task',
    kind: 'task',
    config: {},
  }), false);
  assert.equal(isRunnableWorkbenchSkillNode({
    id: 'conflict',
    type: 'skill',
    kind: 'task',
    config: { skill_slug: 'answer' },
    data: { skill_slug: 'retrieval' },
  }), false);
  assert.equal(isRunnableWorkbenchSkillNode({
    id: 'source',
    type: 'source',
    kind: 'source',
    config: { skill_slug: 'answer' },
  }), false);
});

test('workbench panel exposes the three preview modes and the unsaved boundary', () => {
  const requiredContracts = [
    'aria-label="Local Flow workbench"',
    'role="tablist"',
    "tab() === 'chat'",
    "tab() === 'node'",
    "tab() === 'golden'",
    // The badge wall became one status line plus an on-demand detail list.
    // Every warning the badges shouted is still stated, in full sentences.
    'your unsaved canvas',
    'Nothing is saved or published',
    'so are their side effects',
    'What this run touches',
    'Autosave stays paused for as long as this panel is open.',
    'Never published. The published version and the ingress serving it do',
    'Real Skills run. Whatever they write, send or call outside Agentium',
    'I understand this preview invokes real Skills and may cause external side effects.',
    'Confirmation is valid only for the current Flow revision.',
    'Additional input_ref (JSON)',
    'Send preview',
    'Run selected node',
    'Run golden set',
    'Expected',
    'Actual output_ref',
    'event.preventDefault()',
  ];

  for (const contract of requiredContracts) {
    assert.match(PANEL_SOURCE, new RegExp(contract.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(
    PANEL_SOURCE,
    /saveNow\(|publishNow\(|openPublicationReview\(/,
    'preview UI has no persistence or publication action',
  );
  assert.match(
    PANEL_SOURCE,
    /this\.store\.revision\(\);[\s\S]*this\.realSideEffectsAcknowledged\.set\(false\)/,
    'side-effect consent is revision-scoped and fails closed after every edit',
  );
  assert.match(
    PANEL_SOURCE,
    /runChat\([\s\S]*additionalInputRef\.value,[\s\S]*true/,
    'the UI only dispatches chat after explicit acknowledgement',
  );
  const styles = readFileSync(
    join(process.cwd(), 'src/app/features/orchestration/flow/flow-workbench-panel.component.scss'),
    'utf8',
  );
  assert.match(
    styles.match(/\.ck-workbench__detail \{([\s\S]*?)\n\}/)?.[1] ?? '',
    /&\[hidden\] \{\s*display: none;/,
    'a grid display would otherwise beat the hidden attribute',
  );
});
