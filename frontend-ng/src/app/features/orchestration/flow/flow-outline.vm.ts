/** Pure connector projection shared by the accessible Flow outline. */
import {
  primitivesIncompatible,
  type CanonicalFlowNode,
} from '@app/core/flow-serializer.service';
import {
  parseConnectorId,
  toNodeView,
  type FlowConnectorView,
} from './flow-foblex.adapter';

export interface OutlineConnectorOption extends FlowConnectorView {
  nodeId: string;
  nodeLabel: string;
}

function optionsFor(
  nodes: readonly CanonicalFlowNode[],
  direction: 'in' | 'out',
): OutlineConnectorOption[] {
  return nodes.flatMap((node) => {
    const view = toNodeView(node);
    const connectors = direction === 'out' ? view.outputs : view.inputs;
    return connectors.map((connector) => ({
      ...connector,
      nodeId: node.id,
      nodeLabel: node.label?.trim() || String(node.type),
    }));
  });
}

/** Every output the canvas renders, in the exact canonical node order. */
export function outlineSourceOptions(
  nodes: readonly CanonicalFlowNode[],
): OutlineConnectorOption[] {
  return optionsFor(nodes, 'out');
}

/** Inputs a chosen output can connect to without creating a self-loop or a
 * known primitive schema mismatch. The server validator remains authoritative
 * for richer JSON-schema compatibility. */
export function outlineTargetOptions(
  nodes: readonly CanonicalFlowNode[],
  sourceId: string,
): OutlineConnectorOption[] {
  const source = outlineSourceOptions(nodes).find((option) => option.id === sourceId);
  const parsed = parseConnectorId(sourceId);
  if (!source || !parsed || parsed.direction !== 'out') return [];
  return optionsFor(nodes, 'in').filter((target) => (
    target.nodeId !== parsed.nodeId &&
    (!source.schema ||
      !target.schema ||
      !primitivesIncompatible(source.schema, target.schema))
  ));
}
