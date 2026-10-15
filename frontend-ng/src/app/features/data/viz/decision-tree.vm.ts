/**
 * A decision tree laid out for an SVG: where each node sits, which edges join
 * them, and how strongly each node is tinted.
 *
 * Pure on purpose, like the rest of this kit: the component only draws what
 * this computes, so the geometry is tested without a browser. The layout is
 * the classic top-down tidy tree — leaves spread left to right in reading
 * order, each split centred over its children — which is all a tree of a few
 * levels needs and reads the way a decision is read: from the whole population
 * down to the group it ends in.
 */

/** The condition that leads from a split to one of its children. */
export interface TreeCondition {
  feature: string;
  op: string;
  value: number | null;
  /** True when rows with the value missing also follow this branch. */
  missing?: boolean;
}

/** One node as the caller hands it over, already worded for display. */
export interface TreeChartNode {
  id: number;
  parent: number | null;
  children: number[];
  depth: number;
  condition: TreeCondition | null;
  /** The feature this node splits on; null for a leaf. */
  split: string | null;
  rows: number;
  /** Share of the root's rows, 0–1. */
  share: number;
  /** First line: the split feature, or what the leaf stands for. */
  title: string;
  /** Second line: the section's measure (error, prediction…). */
  value: string;
  /** Third line: how many rows reach the node. */
  detail: string;
  /** Background, as a CSS colour (see `errorShade` / `decisionShade`). */
  fill: string;
}

export interface TreeLayoutNode extends TreeChartNode {
  x: number;
  y: number;
}

export interface TreeLayoutEdge {
  from: number;
  to: number;
  path: string;
  /** Stroke width in px, from the share of rows that take this branch. */
  width: number;
  label: string;
  labelX: number;
  labelY: number;
}

export interface TreeLayout {
  nodes: TreeLayoutNode[];
  edges: TreeLayoutEdge[];
  width: number;
  height: number;
  nodeWidth: number;
  nodeHeight: number;
}

export interface TreeLayoutOptions {
  nodeWidth?: number;
  nodeHeight?: number;
  gapX?: number;
  gapY?: number;
  /** Words the edge labels: `≤ 42,5`, `> 42,5`, `manquant`… */
  label?: (condition: TreeCondition) => string;
}

const DEFAULTS = { nodeWidth: 148, nodeHeight: 62, gapX: 14, gapY: 58 };

/** Where every node goes. Empty or malformed input gives an empty layout. */
export function layoutTree(nodes: readonly TreeChartNode[], options: TreeLayoutOptions = {}): TreeLayout {
  const { nodeWidth, nodeHeight, gapX, gapY } = { ...DEFAULTS, ...options };
  const label = options.label ?? conditionLabel;
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const root = nodes.find((node) => node.parent === null);
  const empty: TreeLayout = { nodes: [], edges: [], width: 0, height: 0, nodeWidth, nodeHeight };
  if (!root) return empty;

  // Leaves take consecutive slots in left-to-right order; a split sits at the
  // middle of its children. Cycles or dangling ids are ignored, not followed.
  const slot = new Map<number, number>();
  let nextLeaf = 0;
  const seen = new Set<number>();
  const place = (id: number): number | null => {
    const node = byId.get(id);
    if (!node || seen.has(id)) return null;
    seen.add(id);
    const placed = node.children.map(place).filter((value): value is number => value !== null);
    const position = placed.length ? (placed[0] + placed[placed.length - 1]) / 2 : nextLeaf++;
    slot.set(id, position);
    return position;
  };
  place(root.id);

  const laid: TreeLayoutNode[] = [];
  for (const node of nodes) {
    const position = slot.get(node.id);
    if (position === undefined) continue;
    laid.push({ ...node, x: position * (nodeWidth + gapX), y: node.depth * (nodeHeight + gapY) });
  }
  const at = new Map(laid.map((node) => [node.id, node]));

  const edges: TreeLayoutEdge[] = [];
  for (const node of laid) {
    const parent = node.parent === null ? undefined : at.get(node.parent);
    if (!parent || !node.condition) continue;
    const x1 = parent.x + nodeWidth / 2, y1 = parent.y + nodeHeight;
    const x2 = node.x + nodeWidth / 2, y2 = node.y;
    const middle = (y1 + y2) / 2;
    edges.push({
      from: parent.id,
      to: node.id,
      path: `M ${round(x1)} ${round(y1)} C ${round(x1)} ${round(middle)}, ${round(x2)} ${round(middle)}, ${round(x2)} ${round(y2)}`,
      width: edgeWidth(node.share),
      label: label(node.condition),
      labelX: round((x1 + x2) / 2),
      labelY: round(middle),
    });
  }

  const depth = laid.reduce((deepest, node) => Math.max(deepest, node.depth), 0);
  return {
    nodes: laid,
    edges,
    width: Math.max(nodeWidth, nextLeaf * (nodeWidth + gapX) - gapX),
    height: (depth + 1) * nodeHeight + depth * gapY,
    nodeWidth,
    nodeHeight,
  };
}

/**
 * Stroke width for a branch: thin for a sliver of the rows, thick for most of
 * them. Square-root scaled so a 4 % branch stays visible next to a 96 % one.
 */
export function edgeWidth(share: number): number {
  const bounded = Math.max(0, Math.min(1, Number(share) || 0));
  return round(1.25 + 6.75 * Math.sqrt(bounded));
}

/** The node and every ancestor up to the root, for highlighting a path. */
export function pathTo(nodes: readonly Pick<TreeChartNode, 'id' | 'parent'>[], id: number | null): Set<number> {
  const parents = new Map(nodes.map((node) => [node.id, node.parent]));
  const path = new Set<number>();
  let current: number | null | undefined = id;
  while (current !== null && current !== undefined && parents.has(current) && !path.has(current)) {
    path.add(current);
    current = parents.get(current);
  }
  return path;
}

/** The conditions from the root down to a node, in order. */
export function conditionsTo(nodes: readonly TreeChartNode[], id: number | null): TreeCondition[] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const chain: TreeCondition[] = [];
  const visited = new Set<number>();
  let current = id === null ? undefined : byId.get(id);
  while (current && !visited.has(current.id)) {
    visited.add(current.id);
    if (current.condition) chain.unshift(current.condition);
    current = current.parent === null ? undefined : byId.get(current.parent);
  }
  return chain;
}

/** Short edge label; the split's feature is already written in the parent. */
export function conditionLabel(condition: TreeCondition, locale = 'en', missing = 'missing', present = 'present'): string {
  if (condition.op === 'missing') return missing;
  if (condition.op === 'not_missing') return present;
  const value = typeof condition.value === 'number'
    ? condition.value.toLocaleString(locale, { maximumFractionDigits: 3 })
    : '—';
  return `${condition.op === '<=' ? '≤' : condition.op} ${value}`;
}

/**
 * Background for an error node: neutral at or below the overall error, then
 * increasingly red the worse the group is relative to the worst one.
 *
 * Relative to the overall error, not to zero, on purpose: the question the
 * tree answers is "where does it fail MORE than usual", and a node painted
 * pink for merely matching the average would send the reader to the wrong
 * branch. Alpha carries the intensity, as for the confusion matrix, so the
 * tree reads as one quantity at different strengths in both themes.
 */
export function errorShade(error: number | null | undefined, overall: number | null | undefined, worst: number | null | undefined): string {
  const value = Number(error), base = Number(overall), top = Number(worst);
  if (![value, base, top].every(Number.isFinite) || value <= base || top <= base) return 'transparent';
  const intensity = Math.min(1, (value - base) / (top - base));
  return `color-mix(in srgb, var(--ck-signal-neg, #ef5a6f) ${Math.round((0.1 + 0.42 * intensity) * 100)}%, transparent)`;
}

/**
 * Background for a surrogate node: how clear-cut the model's decision is for
 * that population (the share of its majority answer, or a regression value's
 * position in the range). Accent rather than red: nothing here is a fault.
 */
export function decisionShade(strength: number | null | undefined): string {
  const value = Number(strength);
  if (!Number.isFinite(value) || value <= 0) return 'transparent';
  return `color-mix(in srgb, var(--ck-accent, #6aa9ff) ${Math.round((0.06 + 0.3 * Math.min(1, value)) * 100)}%, transparent)`;
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}
