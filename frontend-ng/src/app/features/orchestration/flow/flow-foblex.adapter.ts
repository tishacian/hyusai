/**
 * CanonicalFlow <-> Foblex adapter — the ENGINE BOUNDARY.
 *
 * This is the only place that knows how the canonical (id-less, port-name)
 * edge model maps onto Foblex's connector-to-connector model. If we ever
 * swap Foblex for another engine, this file is the seam that changes; the
 * FlowStore and the CanonicalFlow pivot stay untouched.
 *
 * Connector id scheme (STABLE — Foblex needs deterministic ids):
 *   output connector:  `${nodeId}::out::${portName}`
 *   input  connector:  `${nodeId}::in::${portName}`
 * A node with no declared typed ports renders a single default connector
 * with portName `'_'`. Named ports render one connector each.
 */
import type {
  CanonicalFlowEdge,
  CanonicalFlowNode,
  NodePort,
} from '@app/core/flow-serializer.service';

const OUT_SEP = '::out::';
const IN_SEP = '::in::';
const DEFAULT_PORT = '_';

export interface FlowConnectorView {
  /** Foblex connector id (fOutputId / fInputId). */
  id: string;
  /** Canonical port name ('' for the implicit default port). */
  name: string;
  schema?: string;
}

export interface FlowNodeView {
  id: string;
  node: CanonicalFlowNode;
  position: { x: number; y: number };
  inputs: FlowConnectorView[];
  outputs: FlowConnectorView[];
}

export interface FlowConnectionView {
  /** Deterministic id derived from the edge endpoints. */
  id: string;
  source: string;
  target: string;
  edge: CanonicalFlowEdge;
  kind: 'data' | 'control' | 'branch';
}

export interface ParsedConnector {
  nodeId: string;
  direction: 'in' | 'out';
  /** Canonical port name, or undefined for the implicit default port. */
  port: string | undefined;
}

export function outputConnectorId(nodeId: string, port = DEFAULT_PORT): string {
  return `${nodeId}${OUT_SEP}${port}`;
}

export function inputConnectorId(nodeId: string, port = DEFAULT_PORT): string {
  return `${nodeId}${IN_SEP}${port}`;
}

/** Parse a Foblex connector id back into node + direction + port. */
export function parseConnectorId(id: string | undefined | null): ParsedConnector | null {
  if (!id) return null;
  const outAt = id.indexOf(OUT_SEP);
  if (outAt >= 0) {
    const port = id.slice(outAt + OUT_SEP.length);
    return { nodeId: id.slice(0, outAt), direction: 'out', port: normalizePort(port) };
  }
  const inAt = id.indexOf(IN_SEP);
  if (inAt >= 0) {
    const port = id.slice(inAt + IN_SEP.length);
    return { nodeId: id.slice(0, inAt), direction: 'in', port: normalizePort(port) };
  }
  return null;
}

function normalizePort(port: string): string | undefined {
  return port === DEFAULT_PORT || port.length === 0 ? undefined : port;
}

function connectorViews(
  nodeId: string,
  ports: NodePort[] | undefined,
  direction: 'in' | 'out',
  renderDefault: boolean,
): FlowConnectorView[] {
  const make = direction === 'out' ? outputConnectorId : inputConnectorId;
  if (ports && ports.length > 0) {
    return ports.map((p) => ({ id: make(nodeId, p.name), name: p.name, schema: p.schema }));
  }
  return renderDefault ? [{ id: make(nodeId, DEFAULT_PORT), name: '' }] : [];
}

/** Build the Foblex node view (connectors + position) for a canonical node. */
export function toNodeView(node: CanonicalFlowNode): FlowNodeView {
  const kind = node.kind ?? 'task';
  return {
    id: node.id,
    node,
    position: node.position ?? { x: 120, y: 120 },
    inputs: connectorViews(node.id, node.inputs, 'in', kind !== 'source'),
    outputs: connectorViews(node.id, node.outputs, 'out', kind !== 'sink'),
  };
}

export function toNodeViews(nodes: CanonicalFlowNode[]): FlowNodeView[] {
  return nodes.map(toNodeView);
}

/**
 * Resolve the output connector id that an edge should attach to, given the
 * source node's rendered ports. Guarantees the returned id matches a
 * connector the node actually renders (so connections never dangle).
 */
function resolveOutputConnector(node: CanonicalFlowNode | undefined, edge: CanonicalFlowEdge): string {
  const ports = node?.outputs ?? [];
  if (edge.from_port && ports.some((p) => p.name === edge.from_port)) {
    return outputConnectorId(edge.from, edge.from_port);
  }
  if (ports.length > 0) return outputConnectorId(edge.from, ports[0].name);
  return outputConnectorId(edge.from, DEFAULT_PORT);
}

function resolveInputConnector(node: CanonicalFlowNode | undefined, edge: CanonicalFlowEdge): string {
  const ports = node?.inputs ?? [];
  if (edge.to_port && ports.some((p) => p.name === edge.to_port)) {
    return inputConnectorId(edge.to, edge.to_port);
  }
  if (ports.length > 0) return inputConnectorId(edge.to, ports[0].name);
  return inputConnectorId(edge.to, DEFAULT_PORT);
}

/** Build Foblex connection views for the current edges. */
export function toConnectionViews(
  edges: CanonicalFlowEdge[],
  nodes: CanonicalFlowNode[],
): FlowConnectionView[] {
  const byId = new Map(nodes.map((n) => [n.id, n] as const));
  return edges.map((edge, index) => ({
    id: `edge-${index}-${edge.from}-${edge.to}-${edge.from_port ?? ''}-${edge.to_port ?? ''}`,
    source: resolveOutputConnector(byId.get(edge.from), edge),
    target: resolveInputConnector(byId.get(edge.to), edge),
    edge,
    kind: edge.kind ?? 'data',
  }));
}

/**
 * Build a CanonicalFlowEdge from a pair of Foblex connector ids (the output
 * of a create/reassign interaction). Returns null when the ids cannot be
 * resolved to a valid output→input pair.
 */
export function connectorsToEdge(
  sourceId: string,
  targetId: string | undefined,
): CanonicalFlowEdge | null {
  const source = parseConnectorId(sourceId);
  const target = parseConnectorId(targetId);
  if (!source || !target) return null;
  // Foblex hands us (output, input) but be defensive about ordering.
  const out = source.direction === 'out' ? source : target;
  const inp = source.direction === 'in' ? source : target;
  if (out.direction !== 'out' || inp.direction !== 'in') return null;
  return {
    from: out.nodeId,
    to: inp.nodeId,
    kind: 'data',
    ...(out.port ? { from_port: out.port } : {}),
    ...(inp.port ? { to_port: inp.port } : {}),
  };
}
