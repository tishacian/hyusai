/**
 * Pure helpers for the Flow Builder's "drop from handle" insertion.
 *
 * Connector availability must follow the exact same structural rules as the
 * canvas adapter: sources/assets do not render an input connector, sinks do
 * not render an output connector, and other port-less nodes render one
 * implicit passthrough connector. Keeping the selection here makes menu
 * filtering and edge creation use one decision.
 */
import {
  primitivesIncompatible,
  type CanonicalFlowEdge,
  type CanonicalFlowNode,
} from '@app/core/flow-serializer.service';
import {
  connectorsToEdge,
  inputConnectorId,
  outputConnectorId,
  toNodeView,
  type FlowConnectorView,
  type ParsedConnector,
} from './flow-foblex.adapter';
import type { PaletteItem } from './flow.types';

export type PreconnectSide = 'in' | 'out';

function candidateNode(item: PaletteItem, nodeId: string): CanonicalFlowNode {
  return {
    id: nodeId,
    type: item.type,
    kind: item.kind,
    label: item.label,
    inputs: item.inputs ?? [],
    outputs: item.outputs ?? [],
  };
}

/**
 * Return the first connector that both exists on the rendered node and is
 * compatible with the originating handle. An implicit connector has no
 * schema and therefore accepts any schema, matching the existing validator.
 */
export function firstCompatibleRenderedConnector(
  item: PaletteItem,
  side: PreconnectSide,
  originSchema: string | undefined,
  nodeId = '__preconnect_candidate__',
): FlowConnectorView | null {
  const view = toNodeView(candidateNode(item, nodeId));
  const connectors = side === 'in' ? view.inputs : view.outputs;
  return connectors.find((connector) => (
    !originSchema ||
    !connector.schema ||
    !primitivesIncompatible(connector.schema, originSchema)
  )) ?? null;
}

export function isPaletteItemConnectable(
  item: PaletteItem,
  side: PreconnectSide,
  originSchema: string | undefined,
): boolean {
  return firstCompatibleRenderedConnector(item, side, originSchema) !== null;
}

/** Build the preconnection using the exact compatible connector selected. */
export function buildPreconnectEdge(
  origin: ParsedConnector,
  item: PaletteItem,
  newNodeId: string,
  originSchema: string | undefined,
): CanonicalFlowEdge | null {
  const candidateSide: PreconnectSide = origin.direction === 'out' ? 'in' : 'out';
  const candidate = firstCompatibleRenderedConnector(
    item,
    candidateSide,
    originSchema,
    newNodeId,
  );
  if (!candidate) return null;

  if (origin.direction === 'out') {
    return connectorsToEdge(
      outputConnectorId(origin.nodeId, origin.port),
      candidate.id,
    );
  }
  return connectorsToEdge(
    candidate.id,
    inputConnectorId(origin.nodeId, origin.port),
  );
}
