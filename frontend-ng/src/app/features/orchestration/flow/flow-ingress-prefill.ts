/**
 * Prefill the Run input editor from the ingress contract the Flow declares.
 *
 * `config.input_schema` on a source node is what publication freezes as the
 * ingress contract and validates every `input_ref` against, so an empty `{}`
 * asks the operator to retype what the graph already states. The resolution
 * here is the one publication uses: the declared schema when there is one,
 * otherwise the node's output ports.
 *
 * How much is seeded differs by source, and deliberately:
 *   - a **declared** schema only gets its required properties and its
 *     defaults, because inventing a value for an optional constrained
 *     property would make a valid request invalid;
 *   - a **port-derived** schema gets every port, since a port carries nothing
 *     but a name and a primitive type — no constraint to violate.
 */
import type { CanonicalFlow, CanonicalFlowNode } from '@app/core/flow-serializer.service';

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Declared ingress schema, or one derived from the node's output ports.
 *
 * `flow-workbench.service.ts` resolves the same rule privately for the chat
 * input shaping. The two must move together until one of them is exported and
 * the other deleted; a Flow whose preview and whose Run disagree on its own
 * entry contract is worse than either being wrong.
 */
export function ingressInputSchema(
  node: CanonicalFlowNode,
): { schema: Record<string, unknown>; declared: boolean } {
  const config = isRecord(node.config) ? node.config : {};
  if (isRecord(config['input_schema'])) {
    return { schema: config['input_schema'], declared: true };
  }

  const properties: Record<string, unknown> = {};
  const required: string[] = [];
  for (const port of node.outputs ?? []) {
    if (!port.name) continue;
    properties[port.name] = typeof port.schema === 'string' ? { type: port.schema } : {};
    if (port.required === true) required.push(port.name);
  }
  return {
    schema: {
      type: 'object',
      properties,
      ...(required.length > 0 ? { required } : {}),
    },
    declared: false,
  };
}

/** The source node a Run enters through, or null when it is ambiguous. */
export function resolveIngressNode(
  flow: CanonicalFlow,
  ingressId?: string | null,
): CanonicalFlowNode | null {
  const sources = flow.nodes.filter((node) => node.kind === 'source');
  if (ingressId) {
    return sources.find((node) => node.id === ingressId) ?? null;
  }
  return sources.length === 1 ? sources[0] : null;
}

function seedValue(definition: Record<string, unknown>): unknown {
  const allowed = definition['enum'];
  if (Array.isArray(allowed) && allowed.length > 0) return allowed[0];
  switch (String(definition['type'] ?? 'string')) {
    case 'integer':
    case 'number':
      return 0;
    case 'boolean':
      return false;
    case 'array':
      return [];
    case 'object':
      return {};
    case 'null':
      return null;
    default:
      return '';
  }
}

export function ingressPrefill(
  schema: Record<string, unknown>,
  includeOptional: boolean,
): Record<string, unknown> {
  const properties = isRecord(schema['properties']) ? schema['properties'] : {};
  const required = new Set(
    (Array.isArray(schema['required']) ? schema['required'] : []).map((key) => String(key)),
  );
  const seeded: Record<string, unknown> = {};
  for (const [key, raw] of Object.entries(properties)) {
    const definition = isRecord(raw) ? raw : {};
    if ('default' in definition) {
      seeded[key] = definition['default'];
    } else if (includeOptional || required.has(key)) {
      seeded[key] = seedValue(definition);
    }
  }
  return seeded;
}

/**
 * JSON skeleton for the resolved ingress, or null when there is nothing to
 * state — an ambiguous entry point, or a contract that demands no property.
 */
export function ingressPrefillText(
  flow: CanonicalFlow,
  ingressId?: string | null,
): string | null {
  const node = resolveIngressNode(flow, ingressId);
  if (!node) return null;
  const { schema, declared } = ingressInputSchema(node);
  const skeleton = ingressPrefill(schema, !declared);
  if (Object.keys(skeleton).length === 0) return null;
  return JSON.stringify(skeleton, null, 2);
}
