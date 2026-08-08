/**
 * Pure view-model helpers behind the node-contract editors (F1 ingress kind,
 * F2 output schema, F3 decision bindings).
 *
 * Angular-free (only `import type`, erased at build) so the three rules that
 * MUST agree with the backend can be unit-tested in the lightweight
 * `node:test` harness — same pattern as `flow-manifest-strip.vm.ts`.
 *
 * Two of them are deliberate mirrors of Python the editor cannot call:
 *   - `derivedIngressKind`  ↔ `flow_contracts._ingress_kind`
 *   - `schemaFromPorts`     ↔ `flow_contracts._ports_schema`
 * If either drifts the editor shows an entry kind or a fallback schema that
 * publication will not produce, so they are locked by spec.
 */
import type { CanonicalFlowNode, NodePort } from '@app/core/flow-serializer.service';

/** Accepted values of `config.ingress_kind` (backend `_INGRESS_KINDS`). */
export const INGRESS_KINDS = ['manual', 'chat', 'http', 'schedule', 'event'] as const;
export type IngressKind = (typeof INGRESS_KINDS)[number];

export function isIngressKind(value: unknown): value is IngressKind {
  return typeof value === 'string' && (INGRESS_KINDS as readonly string[]).includes(value);
}

/**
 * The ingress kind publication derives while `config.ingress_kind` is
 * undeclared. Mirror of `flow_contracts._ingress_kind`; `null` for any node
 * that is not an executable source.
 */
export function derivedIngressKind(node: CanonicalFlowNode): IngressKind | null {
  if ((node.kind ?? 'task') !== 'source') return null;
  const type = String(node.type ?? '');
  if (type === 'source.webhook') return 'http';
  if (type === 'source.schedule') return 'schedule';
  if (type === 'input' && node.id === 'source.request') return 'chat';
  if (type.startsWith('source.')) return 'event';
  return 'manual';
}

const SCHEMA_PRIMITIVES = new Set([
  'string',
  'number',
  'integer',
  'boolean',
  'object',
  'array',
]);

/**
 * The JSON Schema publication derives from a node's ports when no schema is
 * declared. Mirror of `flow_contracts._ports_schema`.
 */
export function schemaFromPorts(ports: readonly NodePort[]): Record<string, unknown> {
  const properties: Record<string, unknown> = {};
  const required: string[] = [];
  for (const port of ports) {
    if (!port?.name) continue;
    properties[port.name] = SCHEMA_PRIMITIVES.has(port.schema) ? { type: port.schema } : {};
    if (port.required === true) required.push(port.name);
  }
  const schema: Record<string, unknown> = {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    type: 'object',
    properties,
    additionalProperties: true,
  };
  if (required.length > 0) schema['required'] = [...required].sort();
  return schema;
}

/** Words the Decision condition DSL owns; never a binding name. */
const DSL_WORDS = new Set([
  'and',
  'or',
  'not',
  'in',
  'is',
  'None',
  'True',
  'False',
  'null',
  'true',
  'false',
]);

/**
 * Bare names a Decision condition reads, ignoring string literals, attribute
 * tails (`ctx.x`) and call targets.
 *
 * A tokeniser, not a parser: it labels the editor while typing. The backend's
 * `condition.references` re-derives the same set from the real AST and owns the
 * `decision_condition_unbound` verdict.
 */
export function conditionNames(expression: string): string[] {
  const withoutStrings = expression.replace(/'[^']*'|"[^"]*"/g, ' ');
  const names = new Set<string>();
  for (const match of withoutStrings.matchAll(/(?<![.\w])[A-Za-z_]\w*/g)) {
    const name = match[0];
    const after = withoutStrings.slice((match.index ?? 0) + name.length).trimStart();
    if (DSL_WORDS.has(name) || after.startsWith('(')) continue;
    names.add(name);
  }
  return [...names].sort();
}
