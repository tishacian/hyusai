/** Authored semantics for any Work prediction. Display bands do not alter a model. */
export interface PredictionBand { key: string; label: string; min: number; }
export interface PredictionContract {
  schema_version: 1;
  model_id: string; model_version: number;
  task: 'classification' | 'regression' | 'clustering';
  target?: string; positive_label?: string;
  label: string; unit: string;
  value_column: string; score_column?: string;
  lower_column?: string; upper_column?: string;
  max_age_seconds: number;
  order?: 'descending' | 'ascending' | 'none';
  bands?: PredictionBand[];
}
export interface PredictionAdvice {
  task: PredictionContract['task']; label: string; unit: string;
  value: string | number | null; score: number | null;
  interval: { lower: number; upper: number } | null;
  band: PredictionBand | null; captured_at: string;
  model: { id: string; version: number }; provenance: Record<string, unknown>;
}
function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
export function finiteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}
export function probability(value: unknown): value is number {
  return finiteNumber(value) && value >= 0 && value <= 1;
}
export function predictionContract(value: unknown): PredictionContract | null {
  if (!object(value)) return null;
  const text = (key: string) => typeof value[key] === 'string' && !!(value[key] as string).trim();
  const task = value['task'];
  if (value['schema_version'] !== 1 || !['classification', 'regression', 'clustering'].includes(String(task))
      || !text('model_id') || !Number.isInteger(value['model_version']) || Number(value['model_version']) < 1
      || !text('label') || !text('unit') || !text('value_column')
      || !Number.isInteger(value['max_age_seconds']) || Number(value['max_age_seconds']) < 1 || Number(value['max_age_seconds']) > 604800
      || !['ascending', 'descending', 'none'].includes(String(value['order'] ?? 'none'))) return null;
  if (task !== 'clustering' && !text('target')) return null;
  if (task === 'classification' && (!text('positive_label') || !text('score_column') || value['unit'] !== 'probability')) return null;
  if (task !== 'classification' && (value['positive_label'] || value['score_column'])) return null;
  const bands = value['bands'] ?? [];
  if (!Array.isArray(bands) || bands.length > 12 || bands.some(b => !object(b) || !b['key'] || typeof b['key'] !== 'string'
      || !b['label'] || typeof b['label'] !== 'string' || !finiteNumber(b['min']) || (task === 'classification' && !probability(b['min'])))) return null;
  if (new Set(bands.map(b => b['key'])).size !== bands.length || new Set(bands.map(b => b['min'])).size !== bands.length) return null;
  if (task === 'clustering' && (bands.length || (value['order'] ?? 'none') !== 'none' || value['unit'] !== 'segment')) return null;
  if (['lower_column', 'upper_column'].some(key => value[key] != null && typeof value[key] !== 'string')) return null;
  if (!!value['lower_column'] !== !!value['upper_column'] || (value['lower_column'] && task !== 'regression')) return null;
  return value as unknown as PredictionContract;
}
export function predictionBand(value: number, contract: PredictionContract): PredictionBand | null {
  return [...(contract.bands ?? [])].filter(b => value >= b.min).sort((a, b) => b.min - a.min)[0] ?? null;
}
export function predictionTime(value: unknown): number {
  if (typeof value !== 'string' || !value) return NaN;
  return Date.parse(/(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : value + 'Z');
}
export function predictionFresh(value: unknown, contract: PredictionContract, now: number): boolean {
  const age = now - predictionTime(value);
  return Number.isFinite(age) && age >= 0 && age <= contract.max_age_seconds * 1000;
}

/** No inference on page load; reject stale data, another class/target, or another model version. */
export function predictionAdvice(value: unknown, rawContract: unknown, now: number): PredictionAdvice | null {
  const contract = predictionContract(rawContract);
  if (!contract || !object(value)) return null;
  if (object(value['model_advice'])) return predictionAdvice(value['model_advice'], contract, now);
  const canonical = value['schema_version'] === 1;
  const model = canonical ? value['model'] : value['served'];
  if (!object(model) || (canonical ? model['id'] : model['model_id']) !== contract.model_id || model['version'] !== contract.model_version
      || (value['task'] !== undefined && value['task'] !== contract.task)
      || (contract.task !== 'clustering' && value['target'] !== contract.target)
      || (contract.task === 'classification' && value['positive_label'] !== contract.positive_label)
      || (canonical && (value['task'] !== contract.task || value['status'] !== 'ready' || value['unit'] !== contract.unit))
      || !predictionFresh(value['captured_at'], contract, now)) return null;
  const predictions = value['predictions'];
  if (!canonical && Array.isArray(predictions) && predictions.length !== 1) return null;
  const row = !canonical && Array.isArray(predictions) ? predictions[0] : value;
  if (!object(row)) return null;
  const result = canonical ? row['value'] : row[contract.value_column];
  const score = contract.task === 'classification' ? (canonical ? row['score'] : row[contract.score_column!]) : null;
  if (contract.task === 'classification' && !probability(score)) return null;
  if (contract.task === 'regression' && !finiteNumber(result)) return null;
  if (contract.task === 'clustering' && !(typeof result === 'string' || (typeof result === 'number' && Number.isInteger(result)))) return null;
  if (result != null && typeof result !== 'string' && !finiteNumber(result)) return null;
  let interval: PredictionAdvice['interval'] = null;
  if (contract.lower_column) {
    const rawInterval = canonical ? row['interval'] : null;
    const lower = canonical && object(rawInterval) ? rawInterval['lower'] : row[contract.lower_column];
    const upper = canonical && object(rawInterval) ? rawInterval['upper'] : row[contract.upper_column!];
    if (!finiteNumber(lower) || !finiteNumber(upper) || !finiteNumber(result) || lower > result || upper < result) return null;
    interval = { lower, upper };
  }
  return {
    task: contract.task, label: contract.label, unit: contract.unit,
    value: result as string | number | null ?? null, score: score as number | null, interval,
    band: contract.task === 'clustering' ? null : predictionBand((score ?? result) as number, contract),
    captured_at: value['captured_at'] as string,
    model: { id: contract.model_id, version: contract.model_version },
    provenance: object(value['provenance']) ? value['provenance'] : {},
  };
}
