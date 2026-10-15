import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  conditionLabel,
  conditionsTo,
  decisionShade,
  edgeWidth,
  errorShade,
  layoutTree,
  pathTo,
  type TreeChartNode,
} from './decision-tree.vm';

/** A depth-2 tree: root → (left leaf, right split → two leaves). */
function sample(): TreeChartNode[] {
  const node = (id: number, parent: number | null, depth: number, children: number[], share: number, op?: string): TreeChartNode => ({
    id, parent, depth, children, share, rows: Math.round(share * 1000),
    condition: op ? { feature: parent === 0 ? 'age' : 'tenure', op, value: parent === 0 ? 42.5 : 3 } : null,
    split: children.length ? (id === 0 ? 'age' : 'tenure') : null,
    title: String(id), value: '', detail: '', fill: 'transparent',
  });
  return [
    node(0, null, 0, [1, 2], 1),
    node(1, 0, 1, [], 0.6, '<='),
    node(2, 0, 1, [3, 4], 0.4, '>'),
    node(3, 2, 2, [], 0.1, '<='),
    node(4, 2, 2, [], 0.3, '>'),
  ];
}

test('leaves spread left to right and each split sits over the middle of its children', () => {
  const tree = layoutTree(sample(), { nodeWidth: 100, nodeHeight: 50, gapX: 10, gapY: 40 });
  const at = new Map(tree.nodes.map((node) => [node.id, node]));
  // Three leaves in reading order: 1, 3, 4.
  assert.equal(at.get(1)!.x, 0);
  assert.equal(at.get(3)!.x, 110);
  assert.equal(at.get(4)!.x, 220);
  assert.equal(at.get(2)!.x, (at.get(3)!.x + at.get(4)!.x) / 2);
  assert.equal(at.get(0)!.x, (at.get(1)!.x + at.get(2)!.x) / 2);
  assert.deepEqual([at.get(0)!.y, at.get(2)!.y, at.get(4)!.y], [0, 90, 180]);
  assert.equal(tree.width, 320);
  assert.equal(tree.height, 230);
});

test('no two boxes of the same level overlap', () => {
  const tree = layoutTree(sample());
  const byDepth = new Map<number, number[]>();
  for (const node of tree.nodes) byDepth.set(node.depth, [...(byDepth.get(node.depth) ?? []), node.x]);
  for (const xs of byDepth.values()) {
    const sorted = [...xs].sort((a, b) => a - b);
    for (let index = 1; index < sorted.length; index++) assert.ok(sorted[index] - sorted[index - 1] >= tree.nodeWidth);
  }
});

test('one edge per child, labelled with its condition and as thick as its share', () => {
  const tree = layoutTree(sample(), { label: (condition) => conditionLabel(condition, 'fr') });
  assert.equal(tree.edges.length, 4);
  const toThree = tree.edges.find((edge) => edge.to === 3)!;
  assert.equal(toThree.from, 2);
  assert.equal(toThree.label, '≤ 3');
  assert.equal(tree.edges.find((edge) => edge.to === 2)!.label, '> 42,5');
  assert.ok(tree.edges.find((edge) => edge.to === 1)!.width > toThree.width);
  assert.match(toThree.path, /^M [\d.]+ [\d.]+ C /);
});

test('malformed trees give an empty or partial layout rather than a loop', () => {
  assert.equal(layoutTree([]).nodes.length, 0);
  const cyclic = sample().map((node) => (node.id === 4 ? { ...node, children: [0] } : node));
  assert.equal(layoutTree(cyclic).nodes.length, 5);
  const orphan = [...sample(), { ...sample()[1], id: 9, parent: 77 }];
  assert.equal(layoutTree(orphan).nodes.length, 5);
});

test('the path to a node runs up to the root, and its conditions read top down', () => {
  assert.deepEqual([...pathTo(sample(), 3)].sort(), [0, 2, 3]);
  assert.equal(pathTo(sample(), null).size, 0);
  assert.deepEqual(conditionsTo(sample(), 3).map((condition) => `${condition.feature} ${condition.op}`), ['age >', 'tenure <=']);
  assert.deepEqual(conditionsTo(sample(), 0), []);
});

test('missing-value branches are worded, numbers are localised', () => {
  assert.equal(conditionLabel({ feature: 'x', op: 'missing', value: null }, 'fr', 'manquant', 'présent'), 'manquant');
  assert.equal(conditionLabel({ feature: 'x', op: 'not_missing', value: null }, 'fr', 'manquant', 'présent'), 'présent');
  assert.equal(conditionLabel({ feature: 'x', op: '<=', value: 34.5678 }, 'fr'), '≤ 34,568');
});

test('error tint starts above the overall error and peaks at the worst group', () => {
  assert.equal(errorShade(0.1, 0.2, 0.6), 'transparent');
  assert.equal(errorShade(0.2, 0.2, 0.6), 'transparent');
  assert.match(errorShade(0.6, 0.2, 0.6), /--ck-signal-neg.* 52%/);
  assert.match(errorShade(0.4, 0.2, 0.6), / 31%/);
  assert.equal(errorShade(null, 0.2, 0.6), 'transparent');
  assert.equal(decisionShade(0), 'transparent');
  assert.match(decisionShade(1), /--ck-accent.* 36%/);
});

test('branch width grows with the share but never vanishes', () => {
  assert.equal(edgeWidth(0), 1.25);
  assert.equal(edgeWidth(1), 8);
  assert.ok(edgeWidth(0.04) > 2 && edgeWidth(0.04) < edgeWidth(0.5));
});
