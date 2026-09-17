import type { MandateSpec } from './mandate.models';

export const MANDATE_LIST_FIELDS = [
  {key: 'collections', path: 'inbound.collection_allowlist'},
  {key: 'skills', path: 'capabilities.allowed_skills'},
  {key: 'models', path: 'capabilities.allowed_models'},
] as const;
export const MANDATE_NUMBER_FIELDS = [
  {path: 'outbound.gate_if_confidence_below', key: 'review_threshold', scale: 100, min: 0, max: 100, step: 'any'},
  {path: 'valves.mandatory_hitl_if_confidence_below', key: 'mandatory_threshold', scale: 100, min: 0, max: 100, step: 'any'},
  {path: 'valves.max_cost_per_decision', key: 'cost', scale: 1, min: 0, max: null, step: 'any'},
  {path: 'valves.max_latency_ms', key: 'latency', scale: .001, min: 0, max: null, step: 'any'},
  {path: 'valves.token_budget', key: 'tokens', scale: 1, min: 1, max: null, step: '1'},
] as const;
export const MANDATE_BOOLEAN_FIELDS = [
  {path: 'inbound.reject_cross_project_sources', key: 'cross_project'},
  {path: 'outbound.expert_review_required', key: 'review_required'},
  {path: 'provenance.require_citations', key: 'citations'},
  {path: 'valves.hard_abort', key: 'hard_abort'},
] as const;
export const MANDATE_EDIT_FIELDS = [
  {path: 'version', key: 'contract_version'}, {path: 'enforcement_mode', key: 'mode'},
  ...MANDATE_LIST_FIELDS.map(field => ({path: field.path, key: field.key})),
  {path: 'capabilities.allowed_delegations', key: 'delegations'},
  ...MANDATE_BOOLEAN_FIELDS, ...MANDATE_NUMBER_FIELDS,
] as const;

export function mandateField(spec: MandateSpec | null, path: string): unknown {
  return path.split('.').reduce<unknown>((value, key) => value && typeof value === 'object'
    ? (value as Record<string, unknown>)[key] : undefined, spec);
}

/** Only a field named by the form is replaced; unexposed legacy controls survive. */
export function withMandateField(spec: MandateSpec, path: string, value: unknown): MandateSpec {
  const clone = structuredClone(spec) as Record<string, unknown>;
  const keys = path.split('.');
  let target = clone;
  for (const key of keys.slice(0, -1)) {
    target[key] = {...(target[key] as Record<string, unknown> | undefined)};
    target = target[key] as Record<string, unknown>;
  }
  target[keys[keys.length - 1]] = value;
  return clone as MandateSpec;
}

/** ACL entries may carry nested contracts; property order is not a change. */
export function mandateJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(mandateJson).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${mandateJson((value as Record<string, unknown>)[key])}`).join(',')}}`;
  return JSON.stringify(value) ?? 'null';
}

export function mandateEditorDiff(before: MandateSpec | null, after: MandateSpec | null) {
  return MANDATE_EDIT_FIELDS.flatMap(field => {
    const previous = mandateField(before, field.path); const next = mandateField(after, field.path);
    return mandateJson(previous) === mandateJson(next) ? [] : [{...field, before: previous, after: next}];
  });
}
