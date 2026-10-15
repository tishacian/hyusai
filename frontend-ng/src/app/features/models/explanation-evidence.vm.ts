import { decisionShade, errorShade, type TreeChartNode } from '../data/viz/decision-tree.vm';

/** Small explanations of held-out rows; failures are local to each section. */
export interface ExplainRule { feature: string; op: string; value: number | null; missing?: boolean; }
export interface ExplainLeaf { rule: ExplainRule[]; rows: number; error?: number | null; global_error?: number | null; lift?: number | null; prediction?: unknown; }
/** One node of the full tree, as the training harness writes it. */
export interface ExplainTreeNode {
  id: number; parent: number | null; depth: number; children: number[];
  condition: ExplainRule | null; split: string | null; rows: number; share: number | null;
  error?: number | null; lift?: number | null;
  prediction?: unknown; purity?: number | null; distribution?: { label: unknown; share: number | null }[]; spread?: number | null;
}
export interface ExplainTreeShape { nodes: ExplainTreeNode[]; depth?: number; leaves?: number; }
export interface ExplainTree { error?: string; rules?: ExplainLeaf[]; global_error?: number | null; rows?: number; tree?: ExplainTreeShape; }
export interface SurrogateEvidence extends ExplainTree { fidelity?: number | null; metric?: string; train_rows?: number; validation_rows?: number; }
export interface PartialEffect { feature: string; error?: string; kind?: string; grid?: (number | string | null)[]; average?: (number | null)[]; ice?: (number | null)[][]; class?: string | number; }
export interface FairnessGroup { group: unknown; n: number; low_support: boolean; [key: string]: unknown; }
export interface FairnessEvidence { column: string; error?: string; groups?: FairnessGroup[]; selection_ratio?: number | null; equalized_odds_diff?: number | null; mae_gap_ratio?: number | null; signal?: boolean; }
export interface ExplanationEvidence {
  error?: string;
  rows?: number;
  elapsed_s?: number;
  budget_s?: number;
  error_tree?: ExplainTree;
  surrogate?: SurrogateEvidence;
  pdp?: PartialEffect[];
  fairness?: FairnessEvidence[] | { error: string };
}
export function readableRule(rule: readonly ExplainRule[], locale: string, all: string, and: string, missing = 'is missing', present = 'is present', or = 'or'): string {
  if (!rule.length) return all;
  return rule.map((term) => {
    if (term.op === 'missing' || term.op === 'not_missing') return `${term.feature} ${term.op === 'missing' ? missing : present}`;
    const comparison = `${term.feature} ${term.op === '<=' ? '≤' : term.op} ${term.value?.toLocaleString(locale, { maximumFractionDigits: 3 }) ?? '—'}`;
    return term.missing ? `(${comparison} ${or} ${term.feature} ${missing})` : comparison;
  }).join(` ${and} `);
}
export function surrogateRules(evidence: SurrogateEvidence | null | undefined): ExplainLeaf[] {
  return evidence && !evidence.error && typeof evidence.fidelity === 'number' && evidence.fidelity >= 0.7 ? evidence.rules ?? [] : [];
}
export function fairnessMetrics(evidence: FairnessEvidence): string[] {
  const available = evidence.groups ?? [];
  return ['selection_rate', 'tpr', 'fpr', 'accuracy', 'mae', 'bias'].filter((key) => available.some((group) => key in group));
}
export function partialSeries(effect: PartialEffect): { grid: (number | string | null)[]; average: (number | null)[]; ice: (number | null)[][] } {
  const grid = effect.grid ?? [], average = effect.average ?? [];
  if (!grid.length || grid.length !== average.length || effect.error) return { grid: [], average: [], ice: [] };
  return { grid, average, ice: (effect.ice ?? []).filter((row) => row.length === grid.length).slice(0, 30) };
}

type PartialPlotValue = number | { x: number; y: number } | null;
export function partialPlot(effect: PartialEffect, locale: string): {
  scale: 'linear' | 'category'; labels: string[]; average: PartialPlotValue[]; ice: PartialPlotValue[][];
} {
  const series = partialSeries(effect);
  if (effect.kind !== 'numeric') {
    return { scale: 'category', labels: series.grid.map((value) => typeof value === 'number'
      ? value.toLocaleString(locale, { maximumFractionDigits: 3 }) : String(value ?? '—')),
      average: series.average, ice: series.ice };
  }
  // Numeric grids may contain only a few unevenly spaced values. Preserve
  // their coordinates; categorical labels would assign them equal spacing.
  const points = (values: (number | null)[]): PartialPlotValue[] => values.map((y, index) => {
    const x = series.grid[index];
    return typeof x === 'number' && Number.isFinite(x) && y !== null && Number.isFinite(y) ? { x, y } : null;
  });
  return { scale: 'linear', labels: [], average: points(series.average), ice: series.ice.map(points) };
}

/**
 * The full tree when the model was trained with it, else nothing. Models
 * trained before the tree was recorded only carry ranked leaf rules, and the
 * card falls back to those.
 */
export function treeNodes(tree: ExplainTree | null | undefined): ExplainTreeNode[] {
  const nodes = tree && !tree.error ? tree.tree?.nodes ?? [] : [];
  return nodes.some((node) => node.parent === null) ? nodes : [];
}

/** How a tree's nodes are worded; the card supplies it from the dictionary. */
export interface TreeWords {
  /** Title of a node that does not split further. */
  group: string;
  rows: (rows: number, share: number | null) => string;
  error: (error: number | null | undefined) => string;
  prediction: (node: ExplainTreeNode) => string;
}

/** The error tree as chart nodes, tinted by how much worse than overall each group is. */
export function errorTreeChart(tree: ExplainTree, words: TreeWords): TreeChartNode[] {
  const nodes = treeNodes(tree);
  const worst = nodes.reduce((top, node) => Math.max(top, typeof node.error === 'number' ? node.error : -Infinity), -Infinity);
  return nodes.map((node) => ({
    ...chartBase(node, words),
    value: words.error(node.error),
    fill: errorShade(node.error, tree.global_error, Number.isFinite(worst) ? worst : null),
  }));
}

/**
 * The surrogate as chart nodes, tinted by how clear-cut the model's answer is:
 * the majority share for a classifier, the position of the mean prediction in
 * the tree's range for a regressor.
 */
export function surrogateChart(tree: ExplainTree, words: TreeWords): TreeChartNode[] {
  const nodes = treeNodes(tree);
  const values = nodes.map((node) => node.prediction).filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  const low = Math.min(...values), high = Math.max(...values);
  return nodes.map((node) => {
    const strength = typeof node.purity === 'number'
      ? node.purity
      : typeof node.prediction === 'number' && high > low ? (node.prediction - low) / (high - low) : null;
    return { ...chartBase(node, words), value: words.prediction(node), fill: decisionShade(strength) };
  });
}

/** Where the card opens: the group that adds the most error beyond the overall rate. */
export function worstErrorNode(tree: ExplainTree): number | null {
  const nodes = treeNodes(tree);
  const overall = typeof tree.global_error === 'number' ? tree.global_error : 0;
  let best: ExplainTreeNode | null = null, score = -Infinity;
  for (const node of nodes) {
    if (node.children.length || typeof node.error !== 'number') continue;
    const excess = (node.error - overall) * node.rows;
    if (excess > score) { score = excess; best = node; }
  }
  return best?.id ?? nodes.find((node) => node.parent === null)?.id ?? null;
}

/** Where the surrogate opens: the group that holds the most rows. */
export function largestLeaf(tree: ExplainTree): number | null {
  const leaves = treeNodes(tree).filter((node) => !node.children.length);
  return leaves.reduce<ExplainTreeNode | null>((best, node) => (!best || node.rows > best.rows ? node : best), null)?.id
    ?? treeNodes(tree).find((node) => node.parent === null)?.id ?? null;
}

function chartBase(node: ExplainTreeNode, words: TreeWords): Omit<TreeChartNode, 'value' | 'fill'> {
  return {
    id: node.id,
    parent: node.parent,
    children: node.children ?? [],
    depth: node.depth,
    condition: node.condition,
    split: node.split,
    rows: node.rows,
    share: typeof node.share === 'number' ? node.share : 0,
    title: node.split ?? words.group,
    detail: words.rows(node.rows, node.share),
  };
}
