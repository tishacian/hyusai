import type { CanonicalFlowNode, NodePort } from './flow-serializer.service';

/** HITL emits a runtime-owned envelope; authored ports cannot redefine it.
 * Kept aligned with backend/services/chains/hitl_ports.py. */
export function hitlPorts(node: CanonicalFlowNode, direction: 'inputs' | 'outputs'): NodePort[] | null {
  if (node.kind !== 'hitl') return null;
  const review = (node.config as Record<string, unknown> | undefined)?.['prompt_kind'] === 'review_dataset_labels';
  if (direction === 'inputs') {
    return review
      ? [{ name: 'dataset_id', schema: 'string' }, { name: 'in', schema: 'object' }]
      : [{ name: 'in', schema: 'object' }];
  }
  const ports: NodePort[] = [
    { name: 'approved', schema: 'boolean' },
    { name: 'rejected', schema: 'boolean' },
    { name: 'decision_id', schema: 'string' },
    { name: 'decision_status', schema: 'string' },
    { name: 'decided_by', schema: 'string' },
  ];
  if (review) ports.push(
    { name: 'dataset_id', schema: 'string' },
    { name: 'name', schema: 'string' },
    { name: 'slug', schema: 'string' },
    { name: 'version', schema: 'integer' },
    { name: 'rows', schema: 'integer' },
    { name: 'columns', schema: 'integer' },
    { name: 'schema', schema: 'array' },
  );
  return ports;
}

export function normalizeHitlPorts(node: CanonicalFlowNode): CanonicalFlowNode {
  const inputs = hitlPorts(node, 'inputs');
  const outputs = hitlPorts(node, 'outputs');
  return inputs && outputs ? { ...node, inputs, outputs } : node;
}
