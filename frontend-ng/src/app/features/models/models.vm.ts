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
import type {
  ConfusionBlock,
  CurvePoint,
  VizBar,
} from '@app/features/data/viz/viz.vm';
import type { NavLinkInput } from '@app/core/navigation.catalog';
import type { TabularColumn, TabularColumnStats } from '@app/shared/ui/data-table.vm';

// ---------------------------------------------------------------------------
// Transport shapes
// ---------------------------------------------------------------------------

// The tasks the catalog offers are open-ended (one per model family); the two
// tabular ones are named for autocompletion and exhaustive copy.
export type ModelTask = 'classification' | 'regression' | (string & {});
export type ModelStatus = 'pending' | 'training' | 'ready' | 'failed' | 'cancelled';
export type MonitorStatus = 'ok' | 'watch' | 'alert';

export interface DriftFeature {
  name: string;
  kind: string;
  value: number | null;
  status: string;
}

export interface MonitoringReport {
  badge: MonitorStatus | null;
  window: { predictions: number; labeled: number; limit: number };
  data_drift: { status: string; features: DriftFeature[] };
  score_drift: {
    status: string;
    value: number | null;
    served_mean: number | null;
    reference_mean: number | null;
    n: number;
  };
  concept_drift: {
    status: string;
    rolling_auc: number | null;
    train_auc: number | null;
    delta: number | null;
    labeled: number;
  };
}

export interface MetricScore {
  key: string;
  value: number | null;
}

// The geometry these read into lives in the shared viz kit, so a curve on a
// model card and a curve anywhere else are one drawing with different numbers.
export type { ConfusionBlock, CurvePoint };

export interface ClassCount {
  label: string;
  count: number;
}

export interface FeatureImportance {
  feature: string;
  value: number | null;
}

/** A cross-validation result, or the reason it did not produce one. */
/** One metric's spread across folds, as skore's cross-validation report reports it. */
export interface CvMetric {
  key: string;
  mean?: number | null;
  std?: number | null;
}

/**
 * Two versions re-scored over one test split, as skore's `ComparisonReport`
 * returns them.
 *
 * The card's delta tiles subtract two *recorded* results, each measured on its
 * own split — fine as history, misleading as a ranking. This is the ranking:
 * same rows, same labels, one value per version per metric. `warnings` names
 * the caveats the table cannot show, chiefly a version that was fitted on a
 * different dataset and may therefore have seen some of these rows.
 */
export interface ComparisonMetricRow {
  key: string;
  /** Keyed by model id: one value per side. */
  [modelId: string]: string | number | null;
}

export interface ComparisonDto {
  task: ModelTask;
  target: string;
  dataset: { id: string; name: string; slug: string; version: number };
  split: { rows: number; test_size: number; random_state: number };
  models: {
    model_id: string;
    column: string;
    version: number;
    algo: string;
    is_champion: boolean;
  }[];
  metrics: ComparisonMetricRow[];
  warnings: { code: string; model_id: string }[];
}

export interface CvBlock {
  folds: number;
  metric: string;
  mean?: number | null;
  std?: number | null;
  /** Every metric, not just the headline one: a fold spread per row. */
  metrics?: CvMetric[];
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
  /**
   * Where skore's serialized evaluation was kept, when it was small enough to
   * keep. Not a metric — the pointer that lets someone reopen the report these
   * numbers were read from, on the rows they were read from.
   */
  report?: { key?: string; bytes?: number; skore?: string };
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
  /** A forecast's covariate: what is known about it (`future`: planned ahead). */
  role?: string;
}

export interface ModelSignature {
  inputs?: SignatureField[];
  /** `levels` and `horizon`: a forecast's series and the horizon it was built for. */
  output?: { task?: ModelTask; target?: string; classes?: string[]; levels?: string[]; horizon?: number };
}

export interface ModelDto {
  id: string;
  name: string;
  slug: string;
  version: number;
  description?: string | null;
  task: ModelTask;
  /** The model family (absent on rows from before families: tabular). */
  family?: string;
  /** The family's problem definition, as validated at training time. */
  spec?: Record<string, unknown>;
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
  published_skill_id?: string | null;
  run_id?: string | null;
  node_id?: string | null;
  /** The System whose run trained the row; null when trained from the card. */
  system_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  trained_at?: string | null;
  train_duration_ms?: number | null;
  /** Worst of data / score / concept drift. Absent until something has been served. */
  monitor_status?: MonitorStatus | null;
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

// ---------------------------------------------------------------------------
// The serving plane
// ---------------------------------------------------------------------------

/** One credential, as the card is allowed to know it: never the secret. */
export interface ApiKeyRow {
  id: string;
  name: string;
  prefix: string;
  revoked: boolean;
  revoked_at?: string | null;
  last_used_at?: string | null;
  use_count: number;
  created_at?: string | null;
  /** Present exactly once, in the response that minted it. */
  secret?: string;
}

export interface PublishedSkillDto {
  slug: string;
  name: string;
  description: string;
  category?: string;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
}

/** Everything the Playground and the key panel render, in one read. */
export interface ServingBlock {
  enabled: boolean;
  callable: boolean;
  serving_version: number | null;
  serving_model_id: string | null;
  is_serving: boolean;
  max_rows: number;
  fields: SignatureField[];
  classes: string[];
  positive_label: string | null;
  predict_count: number;
  last_predict_at: string | null;
  published_skill: PublishedSkillDto | null;
  keys: ApiKeyRow[];
  endpoint: string;
  key_header: string;
  /** `forecast`: the model is asked for a horizon on /forecast, not for rows. */
  mode?: 'rows' | 'forecast';
}

export interface ClassProbability {
  label: string;
  value: number;
}

/** One field's measured effect on this row's answer. */
export interface Contribution {
  field: string;
  value: unknown;
  typical: unknown;
  effect: number;
}

export interface PredictionRow {
  prediction: string | number | null;
  confidence?: number;
  score?: number | null;
  probabilities?: ClassProbability[];
  contributions?: Contribution[];
}

export interface PredictAnswer {
  served: {
    model_id: string;
    name?: string;
    slug?: string;
    version: number;
    is_champion?: boolean;
    task?: ModelTask;
  };
  task: ModelTask;
  target: string;
  classes: string[];
  positive_label: string | null;
  predictions: PredictionRow[];
  rows: number;
  duration_ms: number;
  /** The journal row this call wrote. Feedback attaches here. */
  prediction_id?: string;
  /** What this call paid to get the pipeline in memory. Zero when `cached`. */
  load_ms?: number;
  cached?: boolean;
}

/**
 * The values a prediction form opens on.
 *
 * Pre-filled from the training set's own typical row — the median of a numeric
 * column, the most frequent level of a categorical one, both computed at fit
 * time — and overridden by the model's `input_example` where it has one. Nobody
 * demos a model by typing forty fields, and a form that opens empty makes the
 * first click "fill in the blanks" instead of "change one thing and watch".
 */
export function playgroundSeed(
  fields: readonly SignatureField[],
  example: readonly Record<string, unknown>[] | undefined,
): Record<string, string> {
  const sample = example?.[0] ?? {};
  const seed: Record<string, string> = {};
  for (const field of fields) {
    const raw = sample[field.name] ?? field.default;
    seed[field.name] =
      raw === null || raw === undefined ? '' : String(raw);
  }
  return seed;
}

/**
 * Turn form strings into the JSON the endpoint's contract accepts.
 *
 * An empty box is sent as `null` rather than as `""`: a hole is a legitimate
 * production value and the pipeline was fitted to take one, whereas an empty
 * string in a numeric column is a type error the endpoint would (correctly)
 * refuse.
 */
export function predictPayload(
  fields: readonly SignatureField[],
  values: Record<string, string>,
): Record<string, unknown> {
  const row: Record<string, unknown> = {};
  for (const field of fields) {
    const raw = (values[field.name] ?? '').trim();
    if (!raw) {
      row[field.name] = null;
    } else if (field.kind === 'number') {
      const number = Number(raw);
      row[field.name] = Number.isFinite(number) ? number : raw;
    } else {
      row[field.name] = raw;
    }
  }
  return row;
}

export interface GaugeView {
  /** 0–1: the probability of the class the gauge is about. */
  value: number;
  percent: string;
  /** The class this number is about — a bare number would mean nothing. */
  label: string;
  predicted: string;
  /** The prediction landed in the class the model was asked to find. */
  flagged: boolean;
  /** Arc length for the SVG dash, so the fill can be animated by CSS. */
  dash: number;
  /**
   * Dash offset that parks the handle's single round dash on the fill's tip.
   *
   * The handle used to be a circle in a rotated group, which is the obvious way
   * to put a dot on an arc and the wrong one here: the fill animates
   * `stroke-dashoffset` and the group animated `transform`, and a browser does
   * not interpolate the two alike. Both ran 620ms on the same easing and the dot
   * still trailed the stroke it terminates by a third of the dial. Riding the
   * same property as the fill is what makes them one movement.
   */
  handle: number;
}

/**
 * The gauge's radius, in the SVG's own user units.
 *
 * The track is written `A56,56`, and 56 is a figure SVG quietly corrects: the
 * arc's endpoints are 116 apart, no circle of radius 56 reaches both, and the
 * renderer scales the radii up until one does — to 58. Anything that has to
 * agree with the drawn path (its length, a marker riding its tip) needs the
 * radius the browser used and not the one the `d` attribute asked for.
 */
export const GAUGE_RADIUS = 58;

/** Length of the gauge's semicircular track, in user units. */
export const GAUGE_ARC = Math.PI * GAUGE_RADIUS;

/**
 * Length of the handle's dash: a dot rather than a segment.
 *
 * Short enough that a round cap renders it as a circle of the stroke's width,
 * and not zero, because a zero-length dash is a length no renderer has to draw.
 */
export const GAUGE_HANDLE = 0.01;

/**
 * A classification answer as one number with its class named.
 *
 * The number is the positive class's probability when the model has one, and the
 * winning class's confidence otherwise: on a three-class model there is no
 * "positive", and the honest single number is how sure it is of what it said.
 */
export function gaugeView(
  row: PredictionRow | null | undefined,
  positive: string | null | undefined,
  locale = 'en',
): GaugeView | null {
  if (!row) return null;
  const predicted = row.prediction === null || row.prediction === undefined
    ? ''
    : String(row.prediction);
  const vector = row.probabilities ?? [];
  const named = positive
    ? vector.find((entry) => entry.label === positive)
    : undefined;
  const raw = named?.value ?? row.score ?? row.confidence;
  if (raw === null || raw === undefined || !Number.isFinite(raw)) return null;
  const value = Math.min(1, Math.max(0, Number(raw)));
  const dash = Math.round(value * GAUGE_ARC * 100) / 100;
  return {
    value,
    percent: `${(value * 100).toLocaleString(locale, { maximumFractionDigits: 1 })}%`,
    label: named ? String(named.label) : predicted,
    predicted,
    flagged: !!positive && predicted === positive,
    dash,
    // One period of `GAUGE_HANDLE` then a gap of `GAUGE_ARC`: offsetting by a
    // whole period less the arc length lands the dash on the tip, and stays
    // positive, which negative offsets only became legal in SVG 2.
    handle: Math.round((GAUGE_ARC + GAUGE_HANDLE - dash) * 100) / 100,
  };
}

export interface ContributionBar {
  field: string;
  value: string;
  typical: string;
  effect: number;
  /** 0–100 relative to the strongest effect on this row. */
  width: number;
  /** This value pushed the answer up rather than down. */
  raises: boolean;
}

/**
 * Per-row contributions as signed bars, strongest first.
 *
 * Each one is a measured counterfactual: what the answer would have been had
 * this field held its training-typical value. Bars are normalized against the
 * strongest effect on *this* row, because the question a viewer has is "which of
 * these values is doing the work", not "how does this row compare to others".
 */
export function contributionBars(
  contributions: readonly Contribution[] | undefined,
  limit = 6,
): ContributionBar[] {
  const usable = (contributions ?? []).filter(
    (row) => row?.field && Number.isFinite(row.effect),
  );
  if (!usable.length) return [];
  const strongest = Math.max(...usable.map((row) => Math.abs(row.effect)));
  return usable.slice(0, limit).map((row) => ({
    field: row.field,
    value: cellText(row.value),
    typical: cellText(row.typical),
    effect: row.effect,
    width: strongest ? Math.round((Math.abs(row.effect) / strongest) * 100) : 0,
    raises: row.effect > 0,
  }));
}

function cellText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : String(Math.round(value * 1000) / 1000);
  }
  return String(value);
}

/**
 * The version this card's own calls must name, or `null` to let the alias pick.
 *
 * A card is about one version and builds its form from that version's
 * signature. The endpoint, asked for nothing in particular, answers from the
 * champion — right for an integration, and wrong here the moment two versions
 * do not share a column list: the form would offer v3's twenty-nine fields and
 * the plane would judge them against v1's twenty. So a version that is not the
 * one serving names itself, and the serving version's card stays unpinned,
 * which is where "the alias may answer from another version" is the point being
 * made rather than a contradiction.
 */
export function pinnedVersion(
  block: Pick<ServingBlock, 'is_serving'>,
  version: unknown,
): number | null {
  if (block.is_serving) return null;
  const wanted = Math.trunc(Number(version));
  return Number.isFinite(wanted) && wanted >= 1 ? wanted : null;
}

/**
 * The request, as a shell command that runs.
 *
 * Written against the real endpoint with the real payload, because a snippet
 * that has to be edited before it works is a snippet the audience does not
 * believe. The secret is only substituted in the one response that carried it;
 * afterwards the prefix stands in, since this platform cannot show a key twice.
 */
export function curlSnippet(options: {
  origin: string;
  endpoint: string;
  header: string;
  row: Record<string, unknown>;
  secret?: string | null;
  prefix?: string | null;
  version?: number | null;
}): string {
  const key = options.secret
    ? options.secret
    : options.prefix
      ? `${options.prefix}…`
      : 'YOUR_API_KEY';
  const body = JSON.stringify({
    inputs: [options.row],
    ...(options.version ? { version: options.version } : {}),
  });
  return [
    `curl -X POST ${options.origin}${options.endpoint} \\`,
    `  -H '${options.header}: ${key}' \\`,
    `  -H 'Content-Type: application/json' \\`,
    `  -d '${body}'`,
  ].join('\n');
}

// ---------------------------------------------------------------------------
// Comparison across versions
// ---------------------------------------------------------------------------

export interface MetricDelta {
  key: string;
  /** Signed difference in the metric's own units. */
  value: number;
  display: string;
  /** The change is an improvement for this metric, whichever direction that is. */
  better: boolean;
  /** Too small to be worth a verdict, so it is rendered as flat. */
  flat: boolean;
}

/** Below this, in ratio units, a difference is noise on a demo-sized test set. */
const DELTA_EPSILON = 0.001;

/**
 * How this version's score moved against the one before it.
 *
 * The reason the model card has deltas at all: "AUC 0.87" is a number, "AUC 0.87
 * · +0.03" is a story about a retrain. Sign is reported raw and the verdict comes
 * from the metric, so a smaller MAE reads as an improvement rather than a drop.
 */
export function metricDelta(
  key: string,
  current: number | null | undefined,
  previous: number | null | undefined,
  locale = 'en',
): MetricDelta | null {
  if (
    current === null ||
    current === undefined ||
    previous === null ||
    previous === undefined ||
    !Number.isFinite(current) ||
    !Number.isFinite(previous)
  ) {
    return null;
  }
  const higher = higherIsBetter(key);
  // No direction, no verdict: a delta arrow would claim one.
  if (higher === null) return null;
  const value = current - previous;
  const scale = metricScale(key);
  const digits = scale === 'ratio' ? 3 : scale === 'percent' ? 1 : 3;
  const magnitude = Math.abs(value);
  const flat = scale === 'ratio' ? magnitude < DELTA_EPSILON : magnitude === 0;
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return {
    key,
    value,
    display: flat
      ? '='
      : `${sign}${magnitude.toLocaleString(locale, { maximumFractionDigits: digits })}`,
    better: higher ? value > 0 : value < 0,
    flat,
  };
}

/**
 * The version a delta is measured against: the newest trained one below this.
 *
 * Not "the champion" and not "version n-1": a lineage can hold a failed retrain,
 * and comparing against a run that never produced a score would silence the
 * delta on the version after it.
 */
export function previousVersion(
  current: ModelDto | null | undefined,
  versions: readonly ModelDto[],
): ModelDto | null {
  if (!current) return null;
  const earlier = versions
    .filter(
      (row) =>
        row.id !== current.id &&
        row.status === 'ready' &&
        row.version < current.version,
    )
    .sort((a, b) => b.version - a.version);
  return earlier[0] ?? null;
}

/**
 * The two versions the comparison table puts side by side, earlier one first.
 *
 * `previousVersion` answers "what did this retrain change?", which is the right
 * question for the delta beside a score and the wrong one for the table: the v1
 * of a lineage has nothing below it, so on the only card a demo opens — the one
 * that serves — the tab came up empty under a sentence telling the reader to
 * retrain, while the tab beside it listed three versions. Any other trained
 * version is worth the table. The one below is preferred, because a comparison
 * reads forwards, and the pair is returned in version order so "before" is
 * always the earlier column whichever side the reader arrived from.
 */
export function comparisonPair(
  current: ModelDto | null | undefined,
  versions: readonly ModelDto[],
): { before: ModelDto; after: ModelDto } | null {
  if (!current) return null;
  const others = versions.filter((row) => row.id !== current.id && row.status === 'ready');
  const earlier = others
    .filter((row) => row.version < current.version)
    .sort((a, b) => b.version - a.version)[0];
  if (earlier) return { before: earlier, after: current };
  const later = others
    .filter((row) => row.version > current.version)
    .sort((a, b) => a.version - b.version)[0];
  return later ? { before: current, after: later } : null;
}

export interface ComparisonRow {
  key: string;
  left: string;
  right: string;
  delta: MetricDelta | null;
  /** Which side this metric favours, for the winner marker. */
  winner: 'left' | 'right' | 'tie';
}

/**
 * Two versions' scores, aligned on the metrics they share.
 *
 * Only shared metrics are shown: a classification version next to a regression
 * one has nothing to compare, and inventing a row for a metric one side lacks
 * would read as a regression to zero.
 */
export function comparisonRows(
  left: ModelDto | null | undefined,
  right: ModelDto | null | undefined,
  locale = 'en',
): ComparisonRow[] {
  const leftScores = new Map(
    (left?.metrics?.scores ?? []).map((score) => [score.key, score.value]),
  );
  const rightScores = new Map(
    (right?.metrics?.scores ?? []).map((score) => [score.key, score.value]),
  );
  const rows: ComparisonRow[] = [];
  for (const [key, leftValue] of leftScores) {
    if (!rightScores.has(key)) continue;
    const rightValue = rightScores.get(key) ?? null;
    const delta = metricDelta(key, rightValue, leftValue, locale);
    rows.push({
      key,
      left: formatMetric(key, leftValue, locale),
      right: formatMetric(key, rightValue, locale),
      delta,
      winner: !delta || delta.flat ? 'tie' : delta.better ? 'right' : 'left',
    });
  }
  return rows;
}

/** A slider between bounds — the only kind the forms render today. */
export interface NumericKnobDescriptor {
  key: string;
  kind: 'int' | 'float';
  default: number;
  min: number;
  max: number;
  step: number;
  /** Value at which the estimator decides for itself (sklearn's `None`). */
  auto_at?: number;
}

export interface EnumKnobDescriptor {
  key: string;
  kind: 'enum';
  default: string;
  choices: string[];
}

export interface BoolKnobDescriptor {
  key: string;
  kind: 'bool';
  default: boolean;
}

export interface IntListKnobDescriptor {
  key: string;
  kind: 'int_list';
  default: number[];
  min: number;
  max: number;
  step: number;
  max_items: number;
}

/**
 * One tunable as the catalog serves it. A kind the form does not render yet
 * keeps the server's default: the request simply omits it.
 */
export type KnobDescriptor =
  | NumericKnobDescriptor
  | EnumKnobDescriptor
  | BoolKnobDescriptor
  | IntListKnobDescriptor;

export function isNumericKnob(knob: KnobDescriptor): knob is NumericKnobDescriptor {
  return knob.kind === 'int' || knob.kind === 'float';
}

/** The knobs of an algorithm that render as sliders. */
export function numericKnobs(algo: AlgoDescriptor | undefined): NumericKnobDescriptor[] {
  return (algo?.knobs ?? []).filter(isNumericKnob);
}

/** A field of a model family's problem definition (time column, horizon, …). */
export interface SpecFieldDescriptor {
  key: string;
  kind: 'column' | 'columns' | 'int' | 'float' | 'enum' | 'bool' | 'int_list' | 'column_roles';
  required: boolean;
  default?: unknown;
  min?: number;
  max?: number;
  max_items?: number;
  choices?: string[];
  column_kinds?: string[];
  /** Shown only while another field holds one of these values. */
  when?: Record<string, string[]>;
}

export interface FamilyDescriptor {
  key: string;
  tasks: ModelTask[];
  runtime: string;
  serving: 'in_process' | 'remote';
  /** Whether a worker that can train this family is listening. */
  available: boolean;
  /** For a family served by its own worker: whether that worker answers now. */
  serve_available?: boolean;
  reason?: 'no_worker' | 'runtime_missing' | 'disabled' | (string & {});
  spec_fields: SpecFieldDescriptor[];
}

/** How a metric ranks and reads, served by the catalog (app.services.ml.metrics). */
export interface MetricDescriptor {
  key: string;
  direction: 'max' | 'min' | 'none';
  scale: MetricScale;
  good?: number;
  poor?: number;
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
  /** Absent from catalogs served before model families. */
  families?: FamilyDescriptor[];
  metrics?: MetricDescriptor[];
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

/** One candidate column, carrying the task it suggests and its profile. */
export interface PlanColumn {
  role?: 'text';
  name: string;
  kind: string;
  distinct: number;
  nulls: number;
  suggested_task: ModelTask;
  /**
   * The ingest-time profile, in the shape `<ck-data-table>` already reads, so
   * the picker draws the same distribution glyph as the dataset page.
   */
  profile?: TabularColumnStats;
}

export interface TrainingPlan {
  task: ModelTask;
  target: string;
  features: string[];
  algo: string;
  estimator: string;
  knobs: Record<string, number | null>;
  /** The model family, and its problem definition as the server resolved it. */
  family?: string;
  spec?: Record<string, unknown>;
  test_size: number;
  cross_validation: number;
  name: string;
  warnings: { code: string; feature?: string; field?: string; task?: ModelTask }[];
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
  if (task === 'forecasting') return 'history';
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
    case 'ets':
      return 'waves';
    case 'arima':
      return 'activity';
    case 'seasonal_naive':
      return 'repeat';
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
  /** `null`: the metric has no "better" direction (an interval's coverage). */
  higherIsBetter: boolean | null;
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
  // Calibration, from skore. No good/poor thresholds on purpose: what counts as
  // a good log loss depends on how imbalanced the target is, so an absolute
  // colour would lie. The delta against the previous version still reads.
  log_loss: { scale: 'value', higherIsBetter: false },
  brier_score: { scale: 'value', higherIsBetter: false },
};

/**
 * The registry the catalog serves, which wins over the offline copy above.
 *
 * The copy only covers the tabular metrics and keeps the card readable before
 * the catalog arrives; a forecast's MASE or coverage is known from the server.
 */
const METRIC_REGISTRY = new Map<string, MetricSpec>();

export function setMetricRegistry(metrics: readonly MetricDescriptor[] | null | undefined): void {
  if (!metrics?.length) return;
  METRIC_REGISTRY.clear();
  for (const metric of metrics) {
    METRIC_REGISTRY.set(metric.key, {
      scale: metric.scale,
      good: metric.good,
      poor: metric.poor,
      higherIsBetter: metric.direction === 'max' ? true : metric.direction === 'min' ? false : null,
    });
  }
}

function metricSpec(key: string): MetricSpec | undefined {
  return METRIC_REGISTRY.get(key) ?? METRIC_SPECS[key];
}

export function metricScale(key: string): MetricScale {
  return metricSpec(key)?.scale ?? 'value';
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
  const spec = metricSpec(key);
  if (
    !spec ||
    spec.higherIsBetter === null ||
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
/**
 * Which way a metric improves, or `null` when it does not rank (coverage) or is
 * unknown. Unknown used to mean "higher", which ranks every error backwards.
 */
export function higherIsBetter(key: string): boolean | null {
  return metricSpec(key)?.higherIsBetter ?? null;
}

/**
 * One hop on the model card's pipeline banner.
 *
 * Distinct from `ProvenanceSource` (the published Skill's "who answers"
 * sentence). This is the data path: upload → transform → this version → the
 * tables it later scored.
 */
export type PipelineHopKind = 'dataset' | 'transform' | 'model' | 'scored';

export interface PipelineChip {
  id: string;
  name: string;
  slug?: string;
  version: number;
  kind: PipelineHopKind;
  engine?: string | null;
  added_columns?: string[];
}

export interface PipelineProvenance {
  dataset: PipelineChip | null;
  transform: PipelineChip | null;
  model: PipelineChip;
  scored: PipelineChip[];
}

export interface PipelineHop {
  id: string;
  kind: PipelineHopKind;
  label: string;
  link: NavLinkInput;
  current?: boolean;
}

/**
 * Flatten the pipeline into the hops the banner draws, dropping empty slots.
 *
 * A card with only this version (no training dataset, no scored children) is
 * not a pipeline — drawing a one-chip chain would be ceremony around nothing.
 */
export function pipelineHops(
  provenance: PipelineProvenance | null | undefined,
  label: (chip: PipelineChip) => string,
): PipelineHop[] {
  if (!provenance) return [];
  const hops: PipelineHop[] = [];
  if (provenance.dataset) {
    hops.push({
      id: provenance.dataset.id,
      kind: 'dataset',
      label: label(provenance.dataset),
      link: { leaf: 'data-doc', ref: provenance.dataset.id },
    });
  }
  if (provenance.transform) {
    hops.push({
      id: provenance.transform.id,
      kind: 'transform',
      label: label(provenance.transform),
      link: { leaf: 'data-doc', ref: provenance.transform.id },
    });
  }
  hops.push({
    id: provenance.model.id,
    kind: 'model',
    label: label(provenance.model),
    link: { leaf: 'model-doc', ref: provenance.model.id },
    current: true,
  });
  for (const scored of provenance.scored ?? []) {
    hops.push({
      id: scored.id,
      kind: 'scored',
      label: label(scored),
      link: { leaf: 'data-doc', ref: scored.id },
    });
  }
  if (hops.length < 2) return [];
  return hops;
}

/**
 * What a provenance line needs to know, and nothing more.
 *
 * Narrower than the transport's `SkillProvenance` on purpose: the sentence is
 * built from a name, a version and at most one score, so those are what the
 * function asks for. Structural typing makes the transport shape assignable
 * without this module importing from the Angular side of the app.
 */
export interface ProvenanceSource {
  name: string;
  version: number;
  metric?: { key: string; value: number } | null;
}

/**
 * The i18n parameters of the provenance line a published Skill carries.
 *
 * One sentence — `models.publish.provenance` — serves both places it is shown:
 * the model card, where you have just published, and the skills catalog, where
 * a reader is deciding whether to trust a row among forty. Two keys saying
 * "Model Churn v3 — AUC 0.87" would be two sentences to keep in step.
 *
 * `evidence` is deliberately allowed to be empty. A regression whose primary
 * score has no absolute reading still deserves to say which version answers;
 * quoting a number nobody can interpret is worse than quoting none.
 */
export function provenanceLineParams(
  provenance: ProvenanceSource | null | undefined,
  metricName: (key: string) => string,
  locale = 'en',
): { name: string; version: number; evidence: string } | null {
  if (!provenance?.name) return null;
  const metric = provenance.metric;
  const evidence =
    metric && Number.isFinite(metric.value)
      ? `${metricName(metric.key)} ${formatMetric(metric.key, metric.value, locale)}`
      : '';
  return {
    name: provenance.name,
    version: Math.max(1, Math.round(provenance.version || 1)),
    evidence,
  };
}

/** The one score a list row and the header KPI show. */
export function primaryScore(model: ModelDto | null | undefined): MetricScore | null {
  const primary = model?.primary_metric ?? model?.metrics?.primary ?? null;
  return primary?.key ? primary : null;
}

/**
 * One Models-list row: a lineage, not a training attempt.
 *
 * The registry stores every fit as its own row. The list is about models (mo1):
 * versions live on the sheet (mo3), and the served version is a column rather
 * than a duplicate line. Navigation opens the version the row is about — an
 * active fit when one is running, otherwise the champion, otherwise the newest.
 */
export interface ModelListRow {
  /** Id used for navigation. */
  id: string;
  slug: string;
  name: string;
  task: ModelTask;
  algo: string;
  target: string;
  /** Version that currently answers, or null when none serves. */
  served_version: number | null;
  served_id: string | null;
  version_count: number;
  /** Representative version for status, score and progress. */
  row: ModelDto;
  versions: ModelDto[];
}

/**
 * Collapse version rows into one list row per model slug.
 *
 * Order follows the newest activity in each lineage so a fit in flight stays
 * at the top of the page rather than buried under older siblings.
 */
export function groupModelsBySlug(models: readonly ModelDto[]): ModelListRow[] {
  const bySlug = new Map<string, ModelDto[]>();
  for (const model of models) {
    const key = (model.slug || model.id || '').trim() || model.id;
    const bucket = bySlug.get(key);
    if (bucket) bucket.push(model);
    else bySlug.set(key, [model]);
  }
  const grouped: ModelListRow[] = [];
  for (const versions of bySlug.values()) {
    const ordered = [...versions].sort((left, right) => right.version - left.version);
    const champion = ordered.find((version) => version.is_champion) ?? null;
    const active = ordered.find((version) => isActiveStatus(version.status));
    const row = active ?? champion ?? ordered[0];
    const open = champion ?? ordered[0];
    grouped.push({
      id: (active ?? open).id,
      slug: row.slug,
      name: row.name,
      task: row.task,
      algo: row.algo,
      target: row.target,
      served_version: champion?.version ?? null,
      served_id: champion?.id ?? null,
      version_count: ordered.length,
      row,
      versions: ordered,
    });
  }
  return grouped.sort((left, right) => {
    const leftAt = left.row.updated_at || left.row.created_at || '';
    const rightAt = right.row.updated_at || right.row.created_at || '';
    return rightAt.localeCompare(leftAt);
  });
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

/** Colour the monitoring badge the same way a score is coloured. */
export function monitorTone(status: string | null | undefined): MetricTone {
  if (status === 'alert') return 'neg';
  if (status === 'watch') return 'warn';
  if (status === 'ok') return 'pos';
  return 'neutral';
}

/**
 * Feature-level PSI as the shared bar kit, so a drift panel and a feature
 * importance panel are the same drawing with different numbers.
 */
export function driftBars(
  features: readonly DriftFeature[] | undefined,
): VizBar[] {
  const rows = (features ?? []).filter(
    (row) => row?.name && row.value !== null && Number.isFinite(row.value),
  );
  if (!rows.length) return [];
  const widest = Math.max(...rows.map((row) => Number(row.value) || 0), 0.25);
  return rows.map((row) => {
    const value = Number(row.value) || 0;
    return {
      label: row.name,
      display: value.toFixed(2),
      width: widest ? Math.round((value / widest) * 100) : 0,
      negative: row.status === 'alert',
      emphasis: row.status === 'alert' || row.status === 'watch',
    };
  });
}

/** Train AUC → rolling AUC as two points the curve kit can draw. */
export function aucTrace(
  train: number | null | undefined,
  rolling: number | null | undefined,
): CurvePoint[] {
  if (train == null && rolling == null) return [];
  const left = Number(train ?? rolling ?? 0);
  const right = Number(rolling ?? train ?? 0);
  return [
    { x: 0, y: left },
    { x: 1, y: right },
  ];
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
export function clampKnob(knob: NumericKnobDescriptor, value: unknown): number {
  const raw = Number(value);
  const number = Number.isFinite(raw) ? raw : knob.default;
  const bounded = Math.max(knob.min, Math.min(knob.max, number));
  if (knob.kind === 'int') return Math.round(bounded);
  return Math.round(bounded * 1e6) / 1e6;
}

/** Whether a knob value means "let the estimator decide". */
export function knobIsAuto(knob: NumericKnobDescriptor, value: unknown): boolean {
  return knob.auto_at !== undefined && clampKnob(knob, value) === knob.auto_at;
}

export function defaultKnobs(algo: AlgoDescriptor | undefined): Record<string, number> {
  const knobs: Record<string, number> = {};
  for (const knob of numericKnobs(algo)) knobs[knob.key] = knob.default;
  return knobs;
}

/**
 * The tasks a form offers: those of the families a worker can train now.
 * A catalog served before families lists its tasks bare, all trainable.
 *
 * A family that needs a problem definition (a forecast's date column and
 * horizon) is offered only by a form that renders spec fields; one that does
 * not would submit a request the server can only refuse.
 */
export function trainableTasks(
  catalog: ModelCatalog | null | undefined,
  options: { specFields?: boolean } = {},
): ModelTask[] {
  const tasks = catalog?.tasks ?? [];
  const families = catalog?.families;
  if (!families?.length) return [...tasks];
  const offered = families.filter(
    (family) => family.available && (options.specFields || !(family.spec_fields ?? []).some((field) => field.required)),
  );
  const available = new Set(offered.flatMap((family) => family.tasks));
  return tasks.filter((task) => available.has(task));
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

/** Plan columns in the shape the shared table already reads. */
export function planColumnsAsTable(columns: readonly PlanColumn[]): TabularColumn[] {
  return columns.map((column) => ({
    name: column.name,
    kind: column.kind as TabularColumn['kind'],
    dtype: column.kind,
  }));
}

/** Ingest profiles keyed by name, so a picker header draws the same sparkline. */
export function planColumnStats(
  columns: readonly PlanColumn[],
): Record<string, TabularColumnStats> {
  const stats: Record<string, TabularColumnStats> = {};
  for (const column of columns) {
    stats[column.name] = column.profile ?? {
      kind: column.kind as TabularColumnStats['kind'],
      distinct: column.distinct,
      nulls: column.nulls,
    };
  }
  return stats;
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
  'ML_SPEC_INVALID',
  'ML_FAMILY_UNAVAILABLE',
  'ML_MODEL_NOT_READY',
  'ML_MODEL_NOT_FOUND',
  'ML_TS_TIME_COLUMN_REQUIRED',
  'ML_TS_TIME_COLUMN_NOT_DATETIME',
  'ML_TS_COLUMN_REUSED',
  'ML_TS_EXOG_NOT_NUMERIC',
  'ML_TS_PAST_NEEDS_MULTIVARIATE',
  'ML_TS_STATIC_NEEDS_PANEL',
  'ML_TS_MULTIVARIATE_NEEDS_SERIES',
  'ML_TS_DUPLICATE_TIMESTAMPS',
  'ML_TS_TOO_MANY_SERIES',
  'ML_TS_ALGO_SHAPE_MISMATCH',
  'ML_TS_HISTORY_TOO_SHORT',
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
): 'target' | 'features' | 'algo' | 'dataset' | 'spec' | null {
  // A forecast's refusals are about its problem definition (date column,
  // horizon, covariate roles), which the form renders as one block.
  if (code === 'ML_SPEC_INVALID' || (code ?? '').startsWith('ML_TS_')) {
    return code === 'ML_TS_ALGO_SHAPE_MISMATCH' ? 'algo' : 'spec';
  }
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

/**
 * Coded refusals the serving surfaces render.
 *
 * Kept apart from the training refusals because they are a different
 * conversation: a training refusal is a form answer about a choice not yet made,
 * whereas these are about a call that just happened — a field the model never
 * saw, a key that was revoked, an artifact that will not load.
 */
export const SERVING_ERROR_CODES = [
  'ML_PREDICT_DISABLED',
  'ML_PREDICT_ROWS_REQUIRED',
  'ML_PREDICT_ROW_NOT_OBJECT',
  'ML_PREDICT_TOO_MANY_ROWS',
  'ML_PREDICT_FIELD_UNKNOWN',
  'ML_PREDICT_FIELD_MISSING',
  'ML_PREDICT_FIELD_NOT_NUMERIC',
  'ML_PREDICT_FIELD_NOT_BOOLEAN',
  'ML_PREDICT_FAILED',
  'ML_CONTRACT_MISSING',
  'ML_ARTIFACT_UNLOADABLE',
  'ML_NOTHING_SERVES',
  'ML_VERSION_UNKNOWN',
  'ML_MODEL_NOT_READY',
  'ML_MODEL_NOT_FOUND',
  'ML_SCORE_TOO_MANY_ROWS',
  'ML_SCORE_COLUMN_MISSING',
  'ML_KEY_LIMIT',
  'ML_KEY_NOT_FOUND',
  'ML_KEY_REQUIRED',
  'ML_KEY_INVALID',
  'ML_KEY_REVOKED',
  'ML_KEY_WRONG_MODEL',
  'ML_PUBLISH_NAME_TAKEN',
  'ML_PUBLISH_NAME_INVALID',
  'ML_USE_FORECAST_ROUTE',
  'ML_FORECAST_TIMEOUT',
  'ML_FORECAST_INPUT_INVALID',
  'ML_FORECAST_PARAMS_INVALID',
  'ML_FORECAST_HORIZON_INVALID',
  'ML_FORECAST_FAILED',
  'ML_FORECAST_TOO_MANY_ROWS',
  'ML_ARTIFACT_TAMPERED',
  'ML_ARTIFACT_UNVERIFIED',
  'ML_USE_PREDICT_ROUTE',
  'ML_FAMILY_UNAVAILABLE',
] as const;

const SERVING_ERROR_SET: ReadonlySet<string> = new Set(SERVING_ERROR_CODES);

/**
 * Why two versions cannot be scored on one split.
 *
 * Separate from the serving vocabulary because these are not about a prediction
 * failing: each one names a mismatch between two versions, and the author's next
 * move differs per code — pick another version, or accept that no shared dataset
 * exists.
 */
export const COMPARE_ERROR_CODES = [
  'ML_COMPARE_SAME_VERSION',
  'ML_COMPARE_CROSS_WORKSPACE',
  'ML_COMPARE_DIFFERENT_QUESTION',
  'ML_COMPARE_NO_COMMON_DATASET',
  'ML_COMPARE_DATASET_TOO_LARGE',
  'ML_COMPARE_SPLIT_FAILED',
  'ML_COMPARE_FAILED',
  'ML_COMPARE_NOT_TABULAR',
] as const;

const COMPARE_ERROR_SET: ReadonlySet<string> = new Set(COMPARE_ERROR_CODES);

/** The dictionary key for a comparison refusal, serving's, or `null`. */
export function compareErrorKey(code: string | undefined | null): string | null {
  if (!code) return null;
  if (COMPARE_ERROR_SET.has(code)) return `models.compare.error.${code.toLowerCase()}`;
  return servingErrorKey(code);
}

/** The dictionary key for a serving refusal, or `null` to fall back to its own text. */
export function servingErrorKey(code: string | undefined | null): string | null {
  if (!code || !SERVING_ERROR_SET.has(code)) return null;
  return `models.serving.error.${code.toLowerCase()}`;
}

export const PLAN_WARNING_CODES = ['ML_FEATURE_IDENTIFIER', 'ML_SPEC_FIELD_IGNORED'] as const;

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

/**
 * The steps a training run reports, in order — a mirror of the backend's
 * `TRAIN_STEPS`.
 *
 * The first two are the worker's own; the rest belong to the harness, because
 * only the subprocess doing the fit knows when the fit ends and the scoring
 * begins. A row carries the current one as a bare code in `status_detail`, which
 * is what lets a minute-long fit read as a check-list in whichever language the
 * page is in.
 *
 * `validating` is in the middle and is conditional: only a run that asked for
 * folds ever reports it, which is why the check-list is built against a
 * requested fold count rather than against this list alone.
 */
export const TRAIN_STEPS: readonly string[] = [
  'queued',
  'reading',
  'tuning',
  'fitting',
  'calibrating',
  'scoring',
  'validating',
  'explaining',
  'saving',
];

/**
 * A forecast's steps, as `ml_forecast_harness` writes them: it is judged by
 * backtesting before its final fit, and a backtest counts its folds the way a
 * cross-validation does (`backtesting:2/3`).
 */
export const FORECAST_TRAIN_STEPS: readonly string[] = ['queued', 'reading', 'backtesting', 'fitting', 'saving'];

const KNOWN_TRAIN_STEPS: ReadonlySet<string> = new Set([...TRAIN_STEPS, ...FORECAST_TRAIN_STEPS]);

/**
 * The step, and the count it brought, out of a `status_detail`.
 *
 * The backend writes `fitting:6903` and `validating:3/5` for the same reason the
 * ingest plane writes `profiling:8412`: a count is the only part of a wait that
 * says how much of it is left, and it cannot be a translated sentence because
 * two locales poll the same row.
 *
 * Anything unrecognised falls back to the queued step rather than being shown:
 * a worker from an older deployment still writes an English sentence, and
 * rendering it would put that sentence on the French page.
 */
export function parseTrainDetail(detail: string | null | undefined): {
  step: string;
  rows: number | null;
  fold: number | null;
  folds: number | null;
} {
  const [head, tail] = (detail ?? '').trim().split(':', 2);
  const step = KNOWN_TRAIN_STEPS.has(head) ? head : TRAIN_STEPS[0];
  const empty = { step, rows: null, fold: null, folds: null };
  if (!tail) return empty;
  const [left, right] = tail.split('/', 2);
  const first = Number(left);
  if (!Number.isFinite(first) || first < 0) return empty;
  if (right === undefined) {
    return { ...empty, rows: first > 0 ? first : null };
  }
  const total = Number(right);
  if (!Number.isFinite(total) || total < 1) return empty;
  return { ...empty, fold: first, folds: total };
}

/** Dictionary key for the step a run is on, falling back to the queued one. */
export function trainStepKey(detail: string | null | undefined): string {
  return `models.progress.step.${parseTrainDetail(detail).step}`;
}

/** One line of the training check-list: what it is, and whether it is behind us. */
export interface TrainStep {
  /** The step's code, which is also the tail of its dictionary key. */
  step: string;
  /**
   * Dictionary key for this line's sentence — a `.counted` variant once the
   * number is known, so the template renders a key rather than choosing one.
   */
  key: string;
  /** Everything a `.counted` sentence interpolates, ready to pass through. */
  params: Record<string, string | number>;
  state: 'done' | 'active' | 'todo';
}

/**
 * The whole fit as a check-list, with the steps already passed ticked off.
 *
 * One line at a time is what a spinner is: it says something is happening and
 * nothing about how much is left. Because the step order is known on both sides,
 * a row that says `scoring` also says that reading and fitting are behind it —
 * so the list can be drawn complete from a single poll, without the worker
 * sending it.
 *
 * Three judgements the list makes:
 *
 *  - `validating` is dropped unless folds were asked for. A line that will never
 *    tick is worse than no line: it reads as a step that is stuck.
 *  - A run that is `training` without having claimed a step is shown at
 *    `reading`. It is past the queue, and no progress it did not claim is
 *    invented beyond that.
 *  - Every terminal status ticks the whole list, a failed one included. The
 *    check-list says how far the run got; the refusal beside it says what
 *    stopped it. That is also what makes the list settle rather than vanish —
 *    the reader sees the model was fitted, scored and saved, not merely that a
 *    spinner stopped.
 */
export function trainChecklist(
  status: string | undefined | null,
  detail: string | null | undefined,
  requestedFolds: number | null | undefined,
  locale = 'en',
  task?: ModelTask | null,
  spec?: Record<string, unknown> | null,
): TrainStep[] {
  const forecast = task === 'forecasting';
  // The step that counts folds: a cross-validation, or a forecast's backtest
  // (which always runs, one fold or several).
  const foldStep = forecast ? 'backtesting' : 'validating';
  const folds = forecast
    ? Math.max(1, Math.round(Number(requestedFolds) || 1))
    : Number(requestedFolds) >= 2
      ? Math.round(Number(requestedFolds))
      : 0;
  const parsed = parseTrainDetail(detail);
  const optional: Record<string, boolean> = {
    tuning: spec?.['tuning'] === 'budget',
    calibrating: (task === 'regression' && spec?.['intervals'] === 'conformal') ||
      (task === 'classification' && ['auto', 'sigmoid', 'isotonic'].includes(String(spec?.['calibration']))),
    explaining: spec?.['explain'] === 'pack',
  };
  const steps = forecast
    ? [...FORECAST_TRAIN_STEPS]
    : TRAIN_STEPS.filter((step) => (step !== 'validating' || folds >= 2) &&
      (!(step in optional) || optional[step] || parsed.step === step));
  const terminal = status === 'ready' || status === 'failed' || status === 'cancelled';
  const claimed = (detail ?? '').trim() ? parsed.step : null;
  const at = terminal
    ? steps.length
    : Math.max(0, steps.indexOf(claimed ?? (status === 'training' ? 'reading' : 'queued')));
  return steps.map((step, index): TrainStep => {
    // Each count belongs to the one line it is about. The fit's row count is
    // the learning rows, which is not what the scoring line counts, and the
    // fold counter is only a live number while the folds are running — on a
    // settled row it would freeze on the last one and still read as one.
    const withRows = step === 'fitting' && parsed.rows !== null;
    const onFold =
      (step === foldStep || step === 'tuning' || step === 'calibrating') &&
      !terminal &&
      parsed.step === step &&
      parsed.fold !== null;
    const params: Record<string, string | number> = {};
    if (withRows) params['rows'] = (parsed.rows as number).toLocaleString(locale);
    if (onFold) {
      params['fold'] = parsed.fold as number;
      params['folds'] = parsed.folds as number;
    } else if (step === foldStep) {
      params['folds'] = folds;
    }
    return {
      step,
      key: `models.progress.step.${step}${withRows || onFold ? '.counted' : ''}`,
      params,
      state: index < at ? 'done' : index === at ? 'active' : 'todo',
    };
  });
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
  'ML_RUNTIME_MISSING',
  'ML_TS_SERIES_UNUSABLE',
  'ML_TS_HISTORY_TOO_SHORT',
] as const;

const TRAINING_ERROR_SET: ReadonlySet<string> = new Set(TRAINING_ERROR_CODES);

/** The dictionary key for a settled run's failure, or `null` if it is unnamed. */
export function trainingErrorKey(code: string | undefined | null): string | null {
  if (!code || !TRAINING_ERROR_SET.has(code)) return null;
  return `models.error.${code.toLowerCase()}`;
}
