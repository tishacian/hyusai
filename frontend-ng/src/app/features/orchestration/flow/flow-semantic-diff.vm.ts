import {
  canonicalEdgeIdentity,
  type CanonicalFlow,
  type CanonicalFlowEdge,
  type CanonicalFlowNode,
} from '@app/core/flow-serializer.service';

export type FlowExecutionContractDiff =
  | 'not_checked'
  | 'same'
  | 'changed'
  | 'pinned_uncompared'
  | 'unavailable_uncompared';

export interface FlowSemanticDiffOptions {
  /** Contracts can only be compared when the live canvas is the exact
   * published Flow. A mutable draft has no pinned execution contract yet. */
  executionContracts?: {
    comparable: boolean;
    baseline: Record<string, unknown> | null;
    candidate: Record<string, unknown> | null;
  };
}

export interface FlowSemanticDiff {
  nodesAdded: number;
  nodesRemoved: number;
  nodesChanged: number;
  nodeOrderChanged: boolean;
  edgesAdded: number;
  edgesRemoved: number;
  edgeOrderChanged: boolean;
  metadataChanged: boolean;
  executionContract: FlowExecutionContractDiff;
}

function normalized(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => normalized(item));
  if (!value || typeof value !== 'object') return value;
  const record = value as Record<string, unknown>;
  const result: Record<string, unknown> = {};
  for (const key of Object.keys(record).sort()) {
    if (record[key] !== undefined) result[key] = normalized(record[key]);
  }
  return result;
}

function signature(value: unknown): string {
  return JSON.stringify(normalized(value));
}

/** Node layout is deliberately excluded: version semantics cover executable
 * graph meaning (kind, ports, config, data and extension fields), not where a
 * card happened to be dragged on the canvas. */
function nodeSignature(node: CanonicalFlowNode): string {
  const { position: _position, ...semanticNode } = node;
  return signature(semanticNode);
}

/** Full-edge signatures make kind, ports, branches/labels and future edge
 * fields part of the comparison. A semantic edge mutation is represented as
 * one removal plus one addition, including duplicate parallel routes. */
function edgeCounts(edges: readonly CanonicalFlowEdge[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const edge of edges) {
    const key = signature(edge);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}

function metadataSignature(flow: CanonicalFlow): string {
  const { nodes: _nodes, edges: _edges, ...metadata } = flow;
  return signature(metadata);
}

function sameMembers(before: readonly string[], after: readonly string[]): boolean {
  if (before.length !== after.length) return false;
  const sortedBefore = [...before].sort();
  const sortedAfter = [...after].sort();
  return sortedBefore.every((value, index) => value === sortedAfter[index]);
}

function executableOrderChanged(
  before: readonly string[],
  after: readonly string[],
): boolean {
  return signature(before) !== signature(after) && sameMembers(before, after);
}

function executionContractDiff(
  options: FlowSemanticDiffOptions | undefined,
): FlowExecutionContractDiff {
  const contracts = options?.executionContracts;
  if (!contracts) return 'not_checked';
  if (!contracts.comparable) {
    return contracts.candidate === null
      ? 'unavailable_uncompared'
      : 'pinned_uncompared';
  }
  return signature(contracts.baseline) === signature(contracts.candidate)
    ? 'same'
    : 'changed';
}

export function diffCanonicalFlows(
  baseline: CanonicalFlow,
  candidate: CanonicalFlow,
  options?: FlowSemanticDiffOptions,
): FlowSemanticDiff {
  const beforeNodeOrder = (baseline.nodes ?? []).map((node) => String(node.id));
  const afterNodeOrder = (candidate.nodes ?? []).map((node) => String(node.id));
  const beforeEdgeOrder = (baseline.edges ?? []).map((edge) => canonicalEdgeIdentity(edge));
  const afterEdgeOrder = (candidate.edges ?? []).map((edge) => canonicalEdgeIdentity(edge));
  const beforeNodes = new Map(
    (baseline.nodes ?? []).map((node) => [String(node.id), nodeSignature(node)]),
  );
  const afterNodes = new Map(
    (candidate.nodes ?? []).map((node) => [String(node.id), nodeSignature(node)]),
  );
  let nodesAdded = 0;
  let nodesRemoved = 0;
  let nodesChanged = 0;
  for (const [id, after] of afterNodes) {
    const before = beforeNodes.get(id);
    if (before === undefined) nodesAdded += 1;
    else if (before !== after) nodesChanged += 1;
  }
  for (const id of beforeNodes.keys()) {
    if (!afterNodes.has(id)) nodesRemoved += 1;
  }

  const beforeEdges = edgeCounts(baseline.edges ?? []);
  const afterEdges = edgeCounts(candidate.edges ?? []);
  let edgesAdded = 0;
  let edgesRemoved = 0;
  for (const [key, count] of afterEdges) {
    edgesAdded += Math.max(0, count - (beforeEdges.get(key) ?? 0));
  }
  for (const [key, count] of beforeEdges) {
    edgesRemoved += Math.max(0, count - (afterEdges.get(key) ?? 0));
  }

  return {
    nodesAdded,
    nodesRemoved,
    nodesChanged,
    nodeOrderChanged: executableOrderChanged(beforeNodeOrder, afterNodeOrder),
    edgesAdded,
    edgesRemoved,
    edgeOrderChanged: executableOrderChanged(beforeEdgeOrder, afterEdgeOrder),
    metadataChanged: metadataSignature(baseline) !== metadataSignature(candidate),
    executionContract: executionContractDiff(options),
  };
}

export function formatFlowSemanticDiff(diff: FlowSemanticDiff, t: (key: string) => string): string {
  const parts: string[] = [];
  const nodeParts = [
    diff.nodesAdded ? `+${diff.nodesAdded}` : '',
    diff.nodesRemoved ? `-${diff.nodesRemoved}` : '',
    diff.nodesChanged ? `~${diff.nodesChanged}` : '',
  ].filter(Boolean);
  if (nodeParts.length > 0) parts.push(`${nodeParts.join(' ')}n`);
  if (diff.nodeOrderChanged) parts.push(t('flow.versions.diff.node_order'));
  const edgeParts = [
    diff.edgesAdded ? `+${diff.edgesAdded}` : '',
    diff.edgesRemoved ? `-${diff.edgesRemoved}` : '',
  ].filter(Boolean);
  if (edgeParts.length > 0) parts.push(`${edgeParts.join(' ')}e`);
  if (diff.edgeOrderChanged) parts.push(t('flow.versions.diff.edge_order'));
  if (diff.metadataChanged) parts.push(t('flow.versions.diff.flow'));
  if (diff.executionContract === 'changed') parts.push(t('flow.versions.diff.contract'));
  if (diff.executionContract === 'pinned_uncompared') {
    parts.push(t('flow.versions.diff.pinned_contract'));
  }
  if (diff.executionContract === 'unavailable_uncompared') {
    parts.push(t('flow.versions.diff.unavailable_contract'));
  }
  return parts.length > 0 ? parts.join(' · ') : t('flow.versions.diff.canvas_equal');
}
