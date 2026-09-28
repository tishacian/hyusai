import assert from 'node:assert/strict';
import { test } from 'node:test';

import { layoutSankey, truncateLabel } from './sankey-layout';

const OPTIONS = {
  width: 336,
  height: 336,
  nodeWidth: 6,
  middleLabel: '1 284 h ●',
  rightLabel: '≈ 55,9 k€ ◐',
  leftCaption: 'RUNS ●',
  middleCaption: 'RÉSULTATS',
  rightCaption: 'VALEUR ◐',
};

const DENSE = [
  { label: 'Capture Invoices', detail: '612 runs', value: 612 },
  { label: 'Service Helpdesk', detail: '1 236 runs', value: 1236 },
  { label: 'PR-to-PO', detail: '96 runs', value: 96 },
  { label: 'Contract Risk', value: 212, stubLabel: '212 contrats ○' },
  { label: 'Diagnostic', value: 148, stubLabel: '9 incidents ○' },
  { label: 'Veille', value: 38, stubLabel: '38 briefs ○' },
];

test('dense layout reproduces the approved scale and stacks stubs under the hours node', () => {
  const layout = layoutSankey(DENSE, OPTIONS);
  const sources = layout.nodes.slice(0, 6);
  assert.ok(Math.abs(sources[1]!.h / 1236 - 0.09) < 0.005, 'about 0.09 px per run');
  assert.equal(sources[0]!.y, 14);
  const hours = layout.nodes[6]!;
  assert.equal(hours.x, 184);
  assert.equal(hours.y, 44);
  assert.ok(Math.abs(hours.h - (sources[0]!.h + sources[1]!.h + sources[2]!.h)) < 1e-9);
  const value = layout.nodes[7]!;
  assert.equal(value.x, 322);
  assert.equal(value.fill, 'var(--ck-data-declared)');
  assert.equal(value.declared, true, 'the value node carries an estimate');
  assert.ok(sources.every((node) => !node.declared) && !hours.declared, 'runs and hours are measured');
  const lastNode = layout.nodes.reduce((max, node) => Math.max(max, node.y + node.h), 0);
  assert.ok(lastNode <= 336 - 20 + 1, `nodes stay above the caption row (${lastNode})`);
  assert.equal(layout.stubs.length, 3);
  assert.ok(layout.stubs.every((stub) => stub.y1 > hours.y + hours.h), 'stubs sit below the hours node');
  assert.equal(layout.ribbons.filter((ribbon) => ribbon.kind === 'value').length, 1);
  assert.deepEqual(
    layout.ribbons.filter((ribbon) => ribbon.declared).map((ribbon) => ribbon.kind),
    ['value'],
    'only the value ribbon is declared (and hatched)',
  );
  assert.ok(layout.labels.some((label) => label.text === '612 runs'), 'run count under tall nodes');
  assert.ok(!layout.labels.some((label) => label.text === '96 runs'), 'no run count under short nodes');
  assert.deepEqual(
    layout.labels.filter((label) => label.caption).map((label) => label.text),
    ['RUNS ●', 'RÉSULTATS', 'VALEUR ◐'],
  );
});

test('a single converging source still curves into a lower hours node and is capped', () => {
  const layout = layoutSankey([{ label: 'SAP HANA Maintenance Copilot', detail: '3 runs', value: 3 }], OPTIONS);
  const source = layout.nodes[0]!;
  const hours = layout.nodes[1]!;
  assert.equal(source.y, 14);
  assert.equal(hours.y, 44, 'hours node starts lower so the ribbon bends');
  assert.ok(source.h <= 0.55 * (336 - 14 - 20) + 1e-9, 'single node capped at 55 % of the column');
  assert.ok(source.h >= 4);
  const names = layout.labels.filter((label) => label.title === 'SAP HANA Maintenance Copilot');
  assert.ok(names.length >= 1);
  assert.ok(names.every((label) => label.title === 'SAP HANA Maintenance Copilot'));
  assert.ok(names.some((label) => label.text.includes('SAP') || label.text.includes('HANA')));
  assert.ok(names.every((label) => !label.text.endsWith('…') || label.text.length <= 20));
});

test('stub-only sources render without hours or value nodes', () => {
  const layout = layoutSankey([{ label: 'Veille', value: 38, stubLabel: '38 briefs ○' }], OPTIONS);
  assert.equal(layout.nodes.length, 2, 'source node + result node');
  assert.equal(layout.stubs.length, 1);
  assert.equal(layout.ribbons.filter((ribbon) => ribbon.kind === 'value').length, 0);
  assert.ok(!layout.labels.some((label) => label.text === OPTIONS.middleLabel));
});

test('truncateLabel keeps short names and ellipsises long ones', () => {
  assert.equal(truncateLabel('Capture Invoices'), 'Capture Invoices');
  assert.equal(truncateLabel('Service Helpdesk Copilot'), 'Service Helpdes…');
  assert.equal(layoutSankey([], OPTIONS).nodes.length, 0);
});
