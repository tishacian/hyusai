/**
 * The Play tab's two explanations, as pure functions (M5).
 *
 * **Which method answered.** The card asks `explain_method: "auto"`: a tree
 * ensemble is explained by exact TreeSHAP from the ml-ts worker, anything else —
 * or a TreeSHAP that could not answer in time — by the existing counterfactual,
 * and the answer names the method and the reason. The card must never present
 * the one as the other: Shapley values add up to the model's output, the
 * counterfactual's effects do not.
 *
 * **What would change the answer.** A bounded search over 1–3 fields the person
 * declares they can act on, with candidate values drawn only from the model's
 * input contract. The view model decides, before any request, which fields can
 * be searched at all — the same rule the backend applies — so the picker never
 * offers a field the server would refuse.
 */
import type { ModelTask, SignatureField } from './models.vm';

export type ExplainOutputSpace = 'probability' | 'log_odds' | 'raw_score' | 'value';

export interface TreeShapContribution {
  field: string;
  value?: unknown;
  contribution: number;
}

export interface TreeShapExplanation {
  method: 'tree_shap' | 'tree_shap_approximate';
  output_space: ExplainOutputSpace;
  estimator?: string;
  class?: string | null;
  base: number;
  output: number;
  contributions: TreeShapContribution[];
  other?: { fields: number; contribution: number } | null;
  additivity_gap?: number;
  duration_ms?: number;
}

export interface CounterfactualFallback {
  method: 'counterfactual';
  reason: string;
}

export type ServedExplanation = TreeShapExplanation | CounterfactualFallback;

export function isTreeShap(value: unknown): value is TreeShapExplanation {
  const candidate = value as TreeShapExplanation | null | undefined;
  return (
    !!candidate &&
    (candidate.method === 'tree_shap' || candidate.method === 'tree_shap_approximate') &&
    Number.isFinite(candidate.base) &&
    Number.isFinite(candidate.output) &&
    Array.isArray(candidate.contributions)
  );
}

export function fallbackOf(value: unknown): CounterfactualFallback | null {
  const candidate = value as CounterfactualFallback | null | undefined;
  return candidate?.method === 'counterfactual' && typeof candidate.reason === 'string'
    ? candidate
    : null;
}

/** Reasons the server names; anything else reads as a generic one. */
const REASONS = new Set([
  'shap_unavailable',
  'shap_disabled',
  'not_a_tree_model',
  'calibrated_model',
  'unsupported_tree',
  'timeout',
  'runtime_mismatch',
  'feature_mapping_unavailable',
  'class_unknown',
  'explain_failed',
]);

export function fallbackReasonKey(reason: string | null | undefined): string {
  return `models.play.explain.reason.${reason && REASONS.has(reason) ? reason : 'other'}`;
}

export function outputSpaceKey(space: string | null | undefined): string {
  const known = ['probability', 'log_odds', 'raw_score', 'value'];
  return `models.play.explain.space.${space && known.includes(space) ? space : 'value'}`;
}

export function methodKey(explanation: TreeShapExplanation): string {
  return explanation.method === 'tree_shap_approximate'
    ? 'models.play.explain.method.approximate'
    : 'models.play.explain.method.exact';
}

export interface ShapBar {
  key: string;
  field: string | null;
  value: string;
  contribution: number;
  /** 0–50: half the track, since bars grow left or right from its centre. */
  width: number;
  positive: boolean;
  /** The "other fields" remainder, so the sum still closes on screen. */
  other: boolean;
  fields?: number;
}

export interface ShapView {
  base: number;
  output: number;
  bars: ShapBar[];
  /** base + Σ bars − output, as the server measured it: shown, never hidden. */
  gap: number;
}

/**
 * Signed bars from the base value to the output, strongest first, then the
 * remainder of the fields the server folded into "other". Scaled to the
 * strongest bar of *this* answer, like the counterfactual bars.
 */
export function shapView(explanation: TreeShapExplanation): ShapView {
  const rows = explanation.contributions.filter(
    (item) => item && typeof item.field === 'string' && Number.isFinite(item.contribution),
  );
  const other = explanation.other && Number.isFinite(explanation.other.contribution)
    ? explanation.other
    : null;
  const magnitudes = [
    ...rows.map((item) => Math.abs(item.contribution)),
    ...(other ? [Math.abs(other.contribution)] : []),
  ];
  const strongest = magnitudes.length ? Math.max(...magnitudes) : 0;
  const width = (value: number) =>
    strongest ? Math.round((Math.abs(value) / strongest) * 500) / 10 : 0;
  const bars: ShapBar[] = rows.map((item) => ({
    key: `field:${item.field}`,
    field: item.field,
    value: cellText(item.value),
    contribution: item.contribution,
    width: width(item.contribution),
    positive: item.contribution > 0,
    other: false,
  }));
  if (other && other.fields > 0) {
    bars.push({
      key: 'other',
      field: null,
      value: '',
      contribution: other.contribution,
      width: width(other.contribution),
      positive: other.contribution > 0,
      other: true,
      fields: other.fields,
    });
  }
  return {
    base: explanation.base,
    output: explanation.output,
    bars,
    gap: Number.isFinite(explanation.additivity_gap) ? Number(explanation.additivity_gap) : 0,
  };
}

/** A probability reads as a percentage; a log-odds or a value as a number. */
export function formatExplained(value: number, space: string, locale: string): string {
  if (!Number.isFinite(value)) return '—';
  if (space === 'probability') {
    return value.toLocaleString(locale, { style: 'percent', maximumFractionDigits: 1 });
  }
  return value.toLocaleString(locale, { maximumFractionDigits: 3 });
}

export function signed(value: number, space: string, locale: string): string {
  if (!Number.isFinite(value)) return '—';
  const text = space === 'probability'
    ? Math.abs(value * 100).toLocaleString(locale, { maximumFractionDigits: 1 }) + ' pt'
    : Math.abs(value).toLocaleString(locale, { maximumFractionDigits: 3 });
  return `${value < 0 ? '−' : '+'}${text}`;
}

function cellText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : String(Math.round(value * 1000) / 1000);
  }
  return String(value);
}

// ---------------------------------------------------------------------------
// What would change the answer
// ---------------------------------------------------------------------------

export const MAX_COUNTERFACTUAL_FIELDS = 3;

export interface CounterfactualChange {
  field: string;
  from: unknown;
  to: unknown;
}

export interface CounterfactualResult {
  changes: CounterfactualChange[];
  changed_fields: number;
  distance: number;
  prediction: unknown;
  probability?: number | null;
}

export interface CounterfactualTarget {
  class?: string | null;
  min?: number | null;
  max?: number | null;
}

export interface CounterfactualAnswer {
  status: 'found' | 'not_found' | 'already_reached';
  task?: ModelTask;
  current: { prediction: unknown; probability?: number | null };
  target: CounterfactualTarget;
  results: CounterfactualResult[];
  refused: { field: string; reason: string }[];
  fields: { field: string; candidates: number }[];
  evaluated: number;
  budget: number;
  exhausted: boolean;
  duration_ms?: number;
}

export interface CounterfactualRequest {
  row: Record<string, unknown>;
  fields: string[];
  target?: CounterfactualTarget;
  version?: number;
}

export interface SearchableField {
  name: string;
  usable: boolean;
  /** Why it cannot be searched; the same reasons the server would give. */
  reason?: 'no_range' | 'constant' | 'no_levels' | 'unsupported_kind';
}

const NUMERIC = new Set(['double', 'float', 'long', 'integer']);

/** Which contract fields a counterfactual can move, decided like the server does. */
export function searchableFields(fields: readonly SignatureField[]): SearchableField[] {
  return fields.map((field) => {
    const type = String(field.type ?? 'string');
    const kind = String(field.kind ?? '');
    if (type === 'datetime' || kind === 'datetime') {
      return { name: field.name, usable: false, reason: 'unsupported_kind' };
    }
    if (type === 'boolean') return { name: field.name, usable: true };
    if (NUMERIC.has(type)) {
      const low = Number(field.min), high = Number(field.max);
      if (field.min == null || field.max == null || !Number.isFinite(low) || !Number.isFinite(high)) {
        return { name: field.name, usable: false, reason: 'no_range' };
      }
      return high > low
        ? { name: field.name, usable: true }
        : { name: field.name, usable: false, reason: 'constant' };
    }
    return Array.isArray(field.choices) && field.choices.length
      ? { name: field.name, usable: true }
      : { name: field.name, usable: false, reason: 'no_levels' };
  });
}

/** Toggle a field in the selection, never past the three the search accepts. */
export function toggleField(selected: readonly string[], name: string): string[] {
  if (selected.includes(name)) return selected.filter((item) => item !== name);
  return selected.length >= MAX_COUNTERFACTUAL_FIELDS ? [...selected] : [...selected, name];
}

/**
 * The request body, or the dictionary key of what is missing. A regression
 * needs a range; a classifier may name a class or accept "any other answer".
 */
export function counterfactualRequest(
  row: Record<string, unknown>,
  selected: readonly string[],
  task: ModelTask,
  target: { class?: string; min?: string; max?: string },
  version?: number | null,
): { body: CounterfactualRequest } | { error: string } {
  if (!selected.length) return { error: 'models.play.cf.error.fields' };
  if (selected.length > MAX_COUNTERFACTUAL_FIELDS) return { error: 'models.play.cf.error.fields' };
  const body: CounterfactualRequest = { row, fields: [...selected] };
  if (task === 'regression') {
    const low = parseNumber(target.min), high = parseNumber(target.max);
    if (low === null && high === null) return { error: 'models.play.cf.error.range' };
    if (low !== null && high !== null && high < low) return { error: 'models.play.cf.error.order' };
    body.target = { ...(low !== null ? { min: low } : {}), ...(high !== null ? { max: high } : {}) };
  } else if (target.class) {
    body.target = { class: target.class };
  }
  if (version) body.version = version;
  return { body };
}

function parseNumber(value: string | undefined): number | null {
  if (value === undefined || value.trim() === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export interface CounterfactualRow {
  rank: number;
  changes: { field: string; from: string; to: string }[];
  answer: string;
  probability: string | null;
  distance: string;
}

export function counterfactualRows(
  answer: CounterfactualAnswer | null,
  locale: string,
): CounterfactualRow[] {
  return (answer?.results ?? []).map((result, index) => ({
    rank: index + 1,
    changes: result.changes.map((change) => ({
      field: change.field,
      from: cellText(change.from),
      to: cellText(change.to),
    })),
    answer: typeof result.prediction === 'number'
      ? result.prediction.toLocaleString(locale, { maximumFractionDigits: 3 })
      : cellText(result.prediction),
    probability: typeof result.probability === 'number' && Number.isFinite(result.probability)
      ? result.probability.toLocaleString(locale, { style: 'percent', maximumFractionDigits: 1 })
      : null,
    distance: Number.isFinite(result.distance)
      ? result.distance.toLocaleString(locale, { maximumFractionDigits: 2 })
      : '—',
  }));
}

export function counterfactualStatusKey(answer: CounterfactualAnswer): string {
  return `models.play.cf.status.${answer.status}`;
}

export function refusalReasonKey(reason: string): string {
  const known = ['no_range', 'constant', 'no_levels', 'unsupported_kind', 'no_alternative'];
  return `models.play.cf.refused.${known.includes(reason) ? reason : 'no_alternative'}`;
}
