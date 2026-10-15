import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  errorTreeChart, fairnessMetrics, largestLeaf, partialPlot, partialSeries, readableRule, surrogateChart, surrogateRules, treeNodes, worstErrorNode,
  type ExplainTree, type ExplainTreeNode, type TreeWords,
} from './explanation-evidence.vm';

test('rules preserve learned conditions and localize numeric boundaries', () => {
  assert.equal(readableRule([], 'fr', 'Toutes', 'et'), 'Toutes');
  assert.equal(readableRule([{ feature: 'age', op: '<=', value: 2.5 }, { feature: 'region_North', op: '>', value: 0.5 }], 'fr', 'Toutes', 'et'), 'age ≤ 2,5 et region_North > 0,5');
});
test('a weak or failed surrogate never advertises rules', () => {
  const rules = [{ rule: [], rows: 30, prediction: 'yes' }];
  assert.deepEqual(surrogateRules({ fidelity: 0.69, rules }), []);
  assert.deepEqual(surrogateRules({ fidelity: 0.7, rules }), rules);
  assert.deepEqual(surrogateRules({ fidelity: 0.9, rules, error: 'budget' }), []);
  assert.deepEqual(surrogateRules(undefined), []);
});
test('PDP rejects malformed dimensions and caps the individual curves', () => {
  assert.deepEqual(partialSeries({ feature: 'x', grid: [1], average: [] }).grid, []);
  const curve = partialSeries({ feature: 'region', grid: ['A', 'B'], average: [0.2, 0.5], ice: [[1], ...Array.from({ length: 40 }, () => [0.1, 0.4])] });
  assert.deepEqual(curve.grid, ['A', 'B']);
  assert.equal(curve.ice.length, 30);
});
test('fairness tables show only the metrics measured for their task', () => {
  assert.deepEqual(fairnessMetrics({ column: 'region', groups: [{ group: 'A', n: 50, low_support: false, mae: 1.5, bias: -0.2 }] }), ['mae', 'bias']);
  assert.deepEqual(fairnessMetrics({ column: 'region', groups: [{ group: 'A', n: 50, low_support: false, accuracy: 0.8 }] }), ['accuracy']);
});

test('numeric PDP and ICE preserve irregular spacing and missing predictions', () => {
  const plot = partialPlot({ feature: 'visits', kind: 'numeric', grid: [0, 1, 100],
    average: [0.1, 0.2, 0.8], ice: [[0.2, null, 0.9]] }, 'fr');
  assert.equal(plot.scale, 'linear');
  assert.deepEqual(plot.labels, []);
  assert.deepEqual(plot.average, [{ x: 0, y: 0.1 }, { x: 1, y: 0.2 }, { x: 100, y: 0.8 }]);
  assert.deepEqual(plot.ice, [[{ x: 0, y: 0.2 }, null, { x: 100, y: 0.9 }]]);
});

test('categorical PDP retains labeled categories and curve values', () => {
  const plot = partialPlot({ feature: 'region', kind: 'categorical', grid: ['North', 'South'],
    average: [0.2, 0.8], ice: [[0.1, 0.9]] }, 'en');
  assert.equal(plot.scale, 'category');
  assert.deepEqual(plot.labels, ['North', 'South']);
  assert.deepEqual(plot.average, [0.2, 0.8]);
  assert.deepEqual(plot.ice, [[0.1, 0.9]]);
});

test('rules expose missing-value branches instead of an infinite threshold', () => {
  assert.equal(readableRule([{ feature: 'age', op: 'missing', value: null }], 'en', 'All', 'and'), 'age is missing');
  assert.equal(readableRule([{ feature: 'age', op: '<=', value: 3, missing: true }], 'en', 'All', 'and'), '(age ≤ 3 or age is missing)');
});

const words: TreeWords = {
  group: 'Group',
  rows: (rows, share) => `${rows} rows · ${share}`,
  error: (error) => `error ${error}`,
  prediction: (node) => `→ ${String(node.prediction)}`,
};

function errorTree(): ExplainTree {
  const node = (id: number, parent: number | null, children: number[], rows: number, error: number, op?: string): ExplainTreeNode => ({
    id, parent, depth: parent === null ? 0 : parent === 0 ? 1 : 2, children, rows, share: rows / 1000, error,
    condition: op ? { feature: 'tenure', op, value: 3 } : null, split: children.length ? 'tenure' : null,
  });
  return {
    global_error: 0.2,
    rules: [{ rule: [], rows: 100, error: 0.6 }],
    tree: { nodes: [node(0, null, [1, 2], 1000, 0.2), node(1, 0, [], 900, 0.15, '<='), node(2, 0, [], 100, 0.6, '>')], depth: 1, leaves: 2 },
  };
}

test('a model trained before the tree was recorded falls back to its rules', () => {
  assert.deepEqual(treeNodes({ rules: [{ rule: [], rows: 10 }] }), []);
  assert.deepEqual(treeNodes({ error: 'budget', tree: errorTree().tree }), []);
  assert.deepEqual(treeNodes({ tree: { nodes: [{ ...errorTree().tree!.nodes[1] }] } }), []);
  assert.equal(treeNodes(errorTree()).length, 3);
});

test('error nodes are tinted only above the overall error, the worst one the most', () => {
  const nodes = errorTreeChart(errorTree(), words);
  assert.deepEqual(nodes.map((node) => node.title), ['tenure', 'Group', 'Group']);
  assert.equal(nodes[0].fill, 'transparent');
  assert.equal(nodes[1].fill, 'transparent');
  assert.match(nodes[2].fill, /--ck-signal-neg/);
  assert.equal(nodes[2].value, 'error 0.6');
  assert.equal(nodes[2].detail, '100 rows · 0.1');
});

test('the card opens on the group that adds the most error, else on the root', () => {
  assert.equal(worstErrorNode(errorTree()), 2);
  const flat = errorTree();
  flat.tree!.nodes = flat.tree!.nodes.map((node) => ({ ...node, error: null }));
  assert.equal(worstErrorNode(flat), 0);
});

test('surrogate nodes show the model answer, tinted by how clear it is', () => {
  const tree = errorTree();
  tree.tree!.nodes = tree.tree!.nodes.map((node, index) => ({ ...node, prediction: index === 2 ? 'churn' : 'stay', purity: [0.7, 0.9, 0.55][index] }));
  const nodes = surrogateChart(tree, words);
  assert.equal(nodes[2].value, '→ churn');
  assert.ok(nodes.every((node) => node.fill.includes('--ck-accent')));
  assert.equal(largestLeaf(tree), 1);
  // A regression surrogate is tinted by where its value sits in the range.
  tree.tree!.nodes = tree.tree!.nodes.map((node, index) => ({ ...node, purity: undefined, prediction: [10, 5, 20][index] }));
  const numeric = surrogateChart(tree, words);
  assert.equal(numeric[1].fill, 'transparent');
  assert.match(numeric[2].fill, / 36%/);
});
