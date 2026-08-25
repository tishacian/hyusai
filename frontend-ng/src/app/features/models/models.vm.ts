/**
 * Model plane view-model — Angular-free, so it is unit-testable.
 *
 * Everything a model card *shows* is computed here rather than in a template,
 * for one reason: a card is an argument about a model, and an argument has to
 * be checkable. "Is 0.71 a good AUC" and "which of these two versions serves"
 * are decisions, and a decision that lives in an interpolation cannot be
 * asserted on.
 *
 * The training run's evidence block arrives already shaped by the harness (see
 * `ml_train_harness.py`): the functions below only project it — curves into SVG
 * paths, a confusion matrix into cells that carry their own intensity, feature
 * importances into bars normalized against the strongest one.
 */

// ---------------------------------------------------------------------------
// Transport shapes
// ---------------------------------------------------------------------------

export type ModelTask = 'classification' | 'regression';
export type ModelStatus = 'pending' | 'training' | 'ready' | 'failed' | 'cancelled';

export interface MetricScore {
  key: string;
  value: number | null;
}

export interface CurvePoint {
  x: number;
  y: number;
}

export interface ConfusionBlock {
  labels: string[];
  matrix: number[][];
}

export interface ClassCount {
  label: string;
  count: number;
}

export interface FeatureImportance {
  feature: string;
  value: number | null;
}

/** A cross-validation result, or the reason it did not produce one. */
export interface CvBlock {
  folds: number;
  metric: string;
  mean?: number | null;
  std?: number | null;
  scores?: (number | null)[];
  error?: string;
}

export interface MetricsBlock {
  task?: ModelTask;
  primary?: MetricScore;
  scores?: MetricScore[];
  confusion?: ConfusionBlock;
  curves?: {
    roc?: CurvePoint[];
    pr?: CurvePoint[];
    baseline?: number | null;
    fit?: CurvePoint[];
    ideal?: CurvePoint[];
  };
  rows?: { total?: number; train?: number; test?: number };
  columns?: { used?: string[]; dropped?: { name: string; reason: string }[] };
  importances?: FeatureImportance[];
  cv?: CvBlock;
  target?: {
    name?: string;
    classes?: string[];
    positive?: string | null;
    balance?: ClassCount[];
    min?: number | null;
    max?: number | null;
    mean?: number | null;
  };
}

/** One feature of the input contract: what a prediction form renders. */
export interface SignatureField {
  name: string;
  type: string;
  kind: 'number' | 'category' | 'datetime';
  required?: boolean;
  min?: number | null;
  max?: number | null;
  default?: unknown;
  choices?: string[];
}

export interface ModelSignature {
  inputs?: SignatureField[];
  output?: { task?: ModelTask; target?: string; classes?: string[] };
}

export interface ModelDto {
  id: string;
  name: string;
  slug: string;
  version: number;
  description?: string | null;
  task: ModelTask;
  algo: string;
  target: string;
  features: string[];
  status: ModelStatus;
  status_detail?: string | null;
  error?: string | null;
  cancel_requested?: boolean;
  is_champion: boolean;
  dataset_id?: string | null;
  dataset_slug?: string | null;
  row_count?: number | null;
  test_size?: number | null;
  cross_validation?: number | null;
  primary_metric?: MetricScore | null;
  artifact_bytes?: number | null;
  predict_count?: number;
  last_predict_at?: string | null;
  published_skill_slug?: string | null;
  run_id?: string | null;
  node_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  trained_at?: string | null;
  train_duration_ms?: number | null;
  /** Detail-only blocks. */
  metrics?: MetricsBlock;
  signature?: ModelSignature;
  input_example?: Record<string, unknown>[];
  classes?: string[];
  params?: {
    knobs?: Record<string, number | null>;
    estimator?: string;
    estimator_params?: Record<string, unknown>;
    scale?: boolean;
    warnings?: { code: string; feature?: string }[];
  };
  model_uri?: string | null;
}

export interface KnobDescriptor {
  key: string;
  kind: 'int' | 'float';
  default: number;
  min: number;
  max: number;
  step: number;
  /** Value at which the estimator decides for itself (sklearn's `None`). */
  auto_at?: number;
}

export interface AlgoDescriptor {
  key: string;
  tasks: ModelTask[];
  estimators: Record<string, string>;
  scale: boolean;
  tags: string[];
  knobs: KnobDescriptor[];
}

export interface ModelCatalog {
  enabled: boolean;
  tasks: ModelTask[];
  algos: AlgoDescriptor[];
  limits: {
    min_rows: number;
    max_rows: number;
    max_features: number;
    max_classes: number;
    timeout_s: number;
  };
  defaults: {
    task: ModelTask;
    algo: string;
    test_size: number;
    cross_validation: number;
  };
}

/** One candidate column, carrying the task it suggests. */
export interface PlanColumn {
  name: string;
  kind: string;
  distinct: number;
  nulls: number;
  suggested_task: ModelTask;
}

export interface TrainingPlan {
  task: ModelTask;
  target: string;
  features: string[];
  algo: string;
  estimator: string;
  knobs: Record<string, number | null>;
  test_size: number;
  cross_validation: number;
  name: string;
  warnings: { code: string; feature?: string }[];
  rows: number;
}

export interface CodedRefusal {
  error?: string;
  code: string;
  message: string;
  [detail: string]: unknown;
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

/** Statuses the worker is still working through; surfaces poll while any holds. */
export const MODEL_ACTIVE_STATUSES: readonly ModelStatus[] = ['pending', 'training'];

export function isActiveStatus(status: ModelStatus | undefined | null): boolean {
  return !!status && MODEL_ACTIVE_STATUSES.includes(status);
}

/** Lucide icon for a task — the list's at-a-glance "what does it predict" cue. */
export function taskIcon(task: ModelTask | undefined): string {
  return task === 'regression' ? 'trending-up' : 'target';
}

/**
 * Lucide icon per algorithm family.
 *
 * A family is recognisable by its shape rather than by its name, which is what
 * lets the picker be read at a glance: trees branch, a linear model is a line,
 * neighbours are points.
 */
export function algoIcon(algo: string | undefined): string {
  switch (algo) {
    case 'gradient_boosting':
      return 'bar-chart-3';
    case 'random_forest':
      return 'git-branch';
    case 'linear':
      return 'line-chart';
    case 'knn':
      return 'circle-dot';
    default:
      return 'brain';
  }
}

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

export type MetricScale = 'ratio' | 'percent' | 'value';
export type MetricTone = 'pos' | 'warn' | 'neg' | 'neutral';

interface MetricSpec {
  scale: MetricScale;
  /** Thresholds for the tone, in the metric's own units. Omitted ⇒ no verdict. */
  good?: number;
  poor?: number;
  higherIsBetter: boolean;
}

/**
 * How each metric reads, and when it is worth a colour.
 *
 * The thresholds are deliberately conservative and only exist for metrics whose
 * scale is absolute: an AUC of 0.5 is a coin toss whatever the dataset, so
 * 0.71 can be called "weak" without knowing anything else. An MAE cannot —
 * it is in the target's units — so it gets no verdict rather than a made-up one.
 */
const METRIC_SPECS: Record<string, MetricSpec> = {
  roc_auc: { scale: 'ratio', good: 0.8, poor: 0.65, higherIsBetter: true },
  accuracy: { scale: 'ratio', good: 0.85, poor: 0.7, higherIsBetter: true },
  balanced_accuracy: { scale: 'ratio', good: 0.8, poor: 0.65, higherIsBetter: true },
  f1: { scale: 'ratio', good: 0.8, poor: 0.6, higherIsBetter: true },
  precision: { scale: 'ratio', good: 0.8, poor: 0.6, higherIsBetter: true },
  recall: { scale: 'ratio', good: 0.8, poor: 0.6, higherIsBetter: true },
  r2: { scale: 'ratio', good: 0.7, poor: 0.4, higherIsBetter: true },
  mape: { scale: 'percent', good: 10, poor: 25, higherIsBetter: false },
  mae: { scale: 'value', higherIsBetter: false },
  rmse: { scale: 'value', higherIsBetter: false },
};

export function metricScale(key: string): MetricScale {
  return METRIC_SPECS[key]?.scale ?? 'value';
}

/** Render one metric in its own units: a ratio as a percentage, MAE as itself. */
export function formatMetric(
  key: string,
  value: number | null | undefined,
  locale = 'en',
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const scale = metricScale(key);
  if (scale === 'ratio') {
    return `${(value * 100).toLocaleString(locale, { maximumFractionDigits: 1 })}%`;
  }
  if (scale === 'percent') {
    return `${value.toLocaleString(locale, { maximumFractionDigits: 1 })}%`;
  }
  const digits = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 1 ? 2 : 4;
  return value.toLocaleString(locale, { maximumFractionDigits: digits });
}

/** The colour a score earns, or `neutral` when its scale is not absolute. */
export function metricTone(key: string, value: number | null | undefined): MetricTone {
  const spec = METRIC_SPECS[key];
  if (
    !spec ||
    spec.good === undefined ||
    spec.poor === undefined ||
    value === null ||
    value === undefined ||
    !Number.isFinite(value)
  ) {
    return 'neutral';
  }
  if (spec.higherIsBetter) {
    if (value >= spec.good) return 'pos';
    return value >= spec.poor ? 'warn' : 'neg';
  }
  if (value <= spec.good) return 'pos';
  return value <= spec.poor ? 'warn' : 'neg';
}

/** Whether a bigger number is a better model, for this metric. */
export function higherIsBetter(key: string): boolean {
  return METRIC_SPECS[key]?.higherIsBetter ?? true;
}

/** The one score a list row and the header KPI show. */
export function primaryScore(model: ModelDto | null | undefined): MetricScore | null {
  const primary = model?.primary_metric ?? model?.metrics?.primary ?? null;
  return primary?.key ? primary : null;
}

/**
 * The best score in a set — compared only against scores on the same metric.
 *
 * A workspace holds churn models scored in AUC next to revenue models scored in
 * R², and "best score: 0.94" would be a lie the moment those two are ranked
 * against each other. So the reference metric is the newest trained model's,
 * every other metric is left out of the comparison, and a metric where lower is
 * better (MAE, MAPE) is minimised rather than maximised.
 */
export function bestScore(
  models: readonly ModelDto[],
): { key: string; value: number } | null {
  const scored = models
    .filter((model) => model.status === 'ready')
    .map((model) => primaryScore(model))
    .filter(
      (score): score is { key: string; value: number } =>
        !!score && typeof score.value === 'number' && Number.isFinite(score.value),
    );
  if (!scored.length) return null;
  const reference = scored[0].key;
  const comparable = scored.filter((score) => score.key === reference);
  const better = higherIsBetter(reference)
    ? (a: number, b: number) => a > b
    : (a: number, b: number) => a < b;
  return comparable.reduce((top, score) => (better(score.value, top.value) ? score : top));
}

// ---------------------------------------------------------------------------
// Curves
// ---------------------------------------------------------------------------

export interface CurveBox {
  width: number;
  height: number;
}

export interface CurveDomain {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

/** ROC and precision/recall both live in the unit square. */
export const UNIT_DOMAIN: CurveDomain = { minX: 0, maxX: 1, minY: 0, maxY: 1 };

/**
 * The box a set of series fits in, padded to never be degenerate.
 *
 * Needed for the regression fit chart, whose axes are in the target's units:
 * a chart of ARPU predictions cannot assume the unit square the way a ROC can.
 */
export function curveDomain(series: readonly (readonly CurvePoint[])[]): CurveDomain {
  const points = series.flat().filter((point) => point && Number.isFinite(point.x) && Number.isFinite(point.y));
  if (!points.length) return UNIT_DOMAIN;
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  return {
    minX,
    maxX: maxX > minX ? maxX : minX + 1,
    minY,
    maxY: maxY > minY ? maxY : minY + 1,
  };
}

/**
 * An SVG path for one curve, y flipped so a better model climbs.
 *
 * Returns `''` for fewer than two points rather than a degenerate path: an
 * empty `d` renders nothing, whereas a one-point path renders a dot that reads
 * as data.
 */
export function curvePath(
  points: readonly CurvePoint[] | undefined,
  box: CurveBox,
  domain: CurveDomain = UNIT_DOMAIN,
): string {
  const usable = (points ?? []).filter(
    (point) => point && Number.isFinite(point.x) && Number.isFinite(point.y),
  );
  if (usable.length < 2) return '';
  const spanX = domain.maxX - domain.minX || 1;
  const spanY = domain.maxY - domain.minY || 1;
  return usable
    .map((point, index) => {
      const x = ((point.x - domain.minX) / spanX) * box.width;
      const y = box.height - ((point.y - domain.minY) / spanY) * box.height;
      return `${index === 0 ? 'M' : 'L'}${round(x)},${round(y)}`;
    })
    .join(' ');
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

// ---------------------------------------------------------------------------
// Confusion matrix
// ---------------------------------------------------------------------------

export interface ConfusionCell {
  actual: string;
  predicted: string;
  count: number;
  /** Share of the actual row, which is what makes an imbalanced matrix readable. */
  share: number;
  correct: boolean;
}

export interface ConfusionView {
  labels: string[];
  rows: { actual: string; total: number; cells: ConfusionCell[] }[];
  total: number;
}

/**
 * Cells carrying their own intensity, as a share of the ACTUAL row.
 *
 * Row-normalized rather than matrix-normalized on purpose: a churn matrix is
 * imbalanced by nature, and shading by the global total would paint the whole
 * grid the colour of the majority class and hide exactly the mistake that
 * matters — the churner the model called loyal.
 */
export function confusionView(
  confusion: ConfusionBlock | undefined | null,
): ConfusionView | null {
  const labels = confusion?.labels ?? [];
  const matrix = confusion?.matrix ?? [];
  if (!labels.length || matrix.length !== labels.length) return null;
  let total = 0;
  const rows = labels.map((actual, rowIndex) => {
    const raw = matrix[rowIndex] ?? [];
    const rowTotal = raw.reduce((sum, cell) => sum + (Number(cell) || 0), 0);
    total += rowTotal;
    return {
      actual,
      total: rowTotal,
      cells: labels.map((predicted, colIndex) => {
        const count = Number(raw[colIndex]) || 0;
        return {
          actual,
          predicted,
          count,
          share: rowTotal ? count / rowTotal : 0,
          correct: rowIndex === colIndex,
        };
      }),
    };
  });
  return { labels, rows, total };
}

// ---------------------------------------------------------------------------
// Feature importances and class balance
// ---------------------------------------------------------------------------

export interface ImportanceBar {
  feature: string;
  value: number;
  /** 0–100, relative to the strongest feature of the run. */
  width: number;
  /** A negative permutation score means the column was actively unhelpful. */
  negative: boolean;
}

export function importanceBars(
  importances: readonly FeatureImportance[] | undefined,
  limit = 12,
): ImportanceBar[] {
  const usable = (importances ?? [])
    .filter((row) => row?.feature && row.value !== null && Number.isFinite(row.value))
    .map((row) => ({ feature: row.feature, value: Number(row.value) }));
  if (!usable.length) return [];
  const strongest = Math.max(...usable.map((row) => Math.abs(row.value)));
  return usable.slice(0, limit).map((row) => ({
    feature: row.feature,
    value: row.value,
    width: strongest ? Math.round((Math.abs(row.value) / strongest) * 100) : 0,
    negative: row.value < 0,
  }));
}

export interface BalanceBar {
  label: string;
  count: number;
  share: number;
  width: number;
}

/** Class balance, so an 82% accuracy on a 4% churn rate cannot pass unnoticed. */
export function balanceBars(
  balance: readonly ClassCount[] | undefined,
): BalanceBar[] {
  const rows = (balance ?? []).filter((row) => row?.label !== undefined);
  const total = rows.reduce((sum, row) => sum + (Number(row.count) || 0), 0);
  if (!total) return [];
  const largest = Math.max(...rows.map((row) => Number(row.count) || 0));
  return rows.map((row) => {
    const count = Number(row.count) || 0;
    return {
      label: row.label,
      count,
      share: count / total,
      width: largest ? Math.round((count / largest) * 100) : 0,
    };
  });
}

// ---------------------------------------------------------------------------
// The training form
// ---------------------------------------------------------------------------

/**
 * Clamp one knob the way the backend will.
 *
 * Mirrored rather than trusted-from-the-server because the slider has to be
 * honest while it is being dragged: a form that lets a value out of bounds and
 * finds out after the fit has taught the author nothing.
 */
export function clampKnob(knob: KnobDescriptor, value: unknown): number {
  const raw = Number(value);
  const number = Number.isFinite(raw) ? raw : knob.default;
  const bounded = Math.max(knob.min, Math.min(knob.max, number));
  if (knob.kind === 'int') return Math.round(bounded);
  return Math.round(bounded * 1e6) / 1e6;
}

/** Whether a knob value means "let the estimator decide". */
export function knobIsAuto(knob: KnobDescriptor, value: unknown): boolean {
  return knob.auto_at !== undefined && clampKnob(knob, value) === knob.auto_at;
}

export function defaultKnobs(algo: AlgoDescriptor | undefined): Record<string, number> {
  const knobs: Record<string, number> = {};
  for (const knob of algo?.knobs ?? []) knobs[knob.key] = knob.default;
  return knobs;
}

export function algoFor(
  catalog: ModelCatalog | null | undefined,
  key: string | undefined,
): AlgoDescriptor | undefined {
  return (catalog?.algos ?? []).find((algo) => algo.key === key);
}

/** The algorithms offered for a task, in catalog (ranked) order. */
export function algosForTask(
  catalog: ModelCatalog | null | undefined,
  task: ModelTask,
): AlgoDescriptor[] {
  return (catalog?.algos ?? []).filter((algo) => algo.tasks.includes(task));
}

/**
 * The columns worth offering as a target, best first.
 *
 * A column with one distinct value cannot be predicted and a free-text column
 * with as many values as rows cannot be classified, so neither is offered —
 * the picker states what is trainable rather than listing the schema.
 */
export function targetCandidates(
  columns: readonly PlanColumn[],
  maxClasses: number,
): PlanColumn[] {
  return columns.filter((column) => {
    if (column.distinct <= 1) return false;
    if (column.suggested_task === 'regression') return true;
    return column.distinct <= maxClasses;
  });
}

/** Every column but the target: the default feature set, as the backend's. */
export function defaultFeatures(
  columns: readonly PlanColumn[],
  target: string,
): string[] {
  return columns.map((column) => column.name).filter((name) => name !== target);
}

// ---------------------------------------------------------------------------
// Refusals and warnings
// ---------------------------------------------------------------------------

/**
 * Coded refusals the training form renders against the field that caused them.
 *
 * Listed rather than pattern-matched so an unknown code degrades to the
 * backend's own sentence instead of to a blank: a refusal the UI cannot name is
 * still a refusal the author has to read.
 */
export const REFUSAL_CODES = [
  'ML_TRAIN_DISABLED',
  'DATASET_NOT_READY',
  'ML_DATASET_UNPROFILED',
  'ML_TARGET_REQUIRED',
  'ML_TARGET_UNKNOWN',
  'ML_TASK_UNKNOWN',
  'ML_TARGET_NOT_NUMERIC',
  'ML_TARGET_TOO_MANY_CLASSES',
  'ML_TARGET_SINGLE_CLASS',
  'ML_FEATURE_UNKNOWN',
  'ML_FEATURES_REQUIRED',
  'ML_TOO_MANY_FEATURES',
  'ML_ROWS_INSUFFICIENT',
  'ML_ROWS_TOO_MANY',
  'ML_ALGO_UNKNOWN',
  'ML_ALGO_TASK_MISMATCH',
  'ML_MODEL_NOT_READY',
  'ML_MODEL_NOT_FOUND',
] as const;

export type RefusalCode = (typeof REFUSAL_CODES)[number];

const REFUSAL_SET: ReadonlySet<string> = new Set(REFUSAL_CODES);

/** The dictionary key for a refusal, or `null` when only the server can phrase it. */
export function refusalKey(code: string | undefined | null): string | null {
  if (!code || !REFUSAL_SET.has(code)) return null;
  return `models.refusal.${code.toLowerCase()}`;
}

/** Which form field a refusal belongs against, so it renders next to its cause. */
export function refusalField(
  code: string | undefined | null,
): 'target' | 'features' | 'algo' | 'dataset' | null {
  switch (code) {
    case 'ML_TARGET_REQUIRED':
    case 'ML_TARGET_UNKNOWN':
    case 'ML_TARGET_NOT_NUMERIC':
    case 'ML_TARGET_TOO_MANY_CLASSES':
    case 'ML_TARGET_SINGLE_CLASS':
      return 'target';
    case 'ML_FEATURE_UNKNOWN':
    case 'ML_FEATURES_REQUIRED':
    case 'ML_TOO_MANY_FEATURES':
      return 'features';
    case 'ML_ALGO_UNKNOWN':
    case 'ML_ALGO_TASK_MISMATCH':
      return 'algo';
    case 'DATASET_NOT_READY':
    case 'ML_DATASET_UNPROFILED':
    case 'ML_ROWS_INSUFFICIENT':
    case 'ML_ROWS_TOO_MANY':
      return 'dataset';
    default:
      return null;
  }
}

export const PLAN_WARNING_CODES = ['ML_FEATURE_IDENTIFIER'] as const;

export function warningKey(code: string | undefined | null): string | null {
  if (!code || !PLAN_WARNING_CODES.includes(code as (typeof PLAN_WARNING_CODES)[number])) {
    return null;
  }
  return `models.warning.${code.toLowerCase()}`;
}

/**
 * Split a worker error into its code and its own last line.
 *
 * The worker writes `CODE: detail`; the code is what the UI can translate and
 * the detail is what the harness actually said. Showing only the first would
 * hide the useful half, showing only the second would ship a Python message as
 * a label.
 */
export function splitError(error: string | undefined | null): {
  code: string | null;
  detail: string;
} {
  const text = (error ?? '').trim();
  if (!text) return { code: null, detail: '' };
  const match = /^([A-Z][A-Z0-9_]{3,}):\s*(.*)$/s.exec(text);
  if (!match) return { code: null, detail: text };
  return { code: match[1], detail: match[2].trim() };
}

export const TRAINING_ERROR_CODES = [
  'ML_TIMEOUT',
  'ML_FIT_FAILED',
  'ML_TARGET_UNUSABLE',
  'ML_ROWS_INSUFFICIENT',
  'ML_ARTIFACT_UNWRITABLE',
  'ML_HARNESS_ERROR',
  'ML_SUMMARY_MISSING',
  'ML_DATASET_UNAVAILABLE',
  'ML_ARTIFACT_EMPTY',
  'ML_TRAIN_DISABLED',
] as const;

const TRAINING_ERROR_SET: ReadonlySet<string> = new Set(TRAINING_ERROR_CODES);

/** The dictionary key for a settled run's failure, or `null` if it is unnamed. */
export function trainingErrorKey(code: string | undefined | null): string | null {
  if (!code || !TRAINING_ERROR_SET.has(code)) return null;
  return `models.error.${code.toLowerCase()}`;
}
