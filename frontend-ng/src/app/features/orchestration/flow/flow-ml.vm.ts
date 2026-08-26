/**
 * Model nodes — pure view-model helpers.
 *
 * Three Skills put the model plane on the canvas, and they are three shapes,
 * not three options of one node:
 *
 *  - `ml_train_sklearn_v1` — reads a dataset, writes a *model version*. It is
 *    the only one with a workshop, because a fit is authored: a target, a
 *    feature set, an estimator and a split are decisions, and they deserve the
 *    same room a statement gets.
 *  - `ml_batch_score_v1` — reads a dataset, writes a scored dataset. Nothing to
 *    author: pick which model answers, name the output.
 *  - `ml_predict_v1` — answers one record inline. Same: pick the model.
 *
 * So the serving nodes get a compact inspector section rather than a dialog. A
 * workshop for two dropdowns would be ceremony, and ceremony is what makes a
 * builder feel slow.
 *
 * Everything lives under `config.params`, keyed exactly as `dag.py` projects it
 * into `_train` / `_predict` — the param names here are a mirror of
 * `_TRAIN_PARAM_KEYS` and `_PREDICT_PARAM_KEYS`, and a rename on either side is
 * a bug on both. The server validates and refuses; this module only pre-reads
 * the bag so the surfaces can fail fast and speak the dictionary.
 *
 * Angular-free on purpose so `run-unit.mjs` can exercise it in plain Node.
 */
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import {
  TRAIN_STEPS,
  refusalKey,
  servingErrorKey,
  trainingErrorKey,
} from '@app/features/models/models.vm';
import type { ModelDto, ModelTask } from '@app/features/models/models.vm';

export const ML_TRAIN_SKILL_SLUG = 'ml_train_sklearn_v1';
export const ML_PREDICT_SKILL_SLUG = 'ml_predict_v1';
export const ML_SCORE_SKILL_SLUG = 'ml_batch_score_v1';

/** Mirror of `settings.ml_train_default_test_size`. */
export const TRAIN_TEST_SIZE_DEFAULT = 0.25;
export const TRAIN_TEST_SIZE_MIN = 0.05;
export const TRAIN_TEST_SIZE_MAX = 0.5;
/** Fold counts the studio offers; 0 means "no cross-validation". */
export const TRAIN_CV_OPTIONS: readonly number[] = [3, 5, 10];

/** Which serving shape a node is, or `null` when it is not a model node. */
export type MlNodeRole = 'train' | 'predict' | 'score';

/** One dataset the node reads, pinned by slug (follows) or by id (frozen). */
export interface MlSourcePin {
  dataset_slug?: string;
  dataset_id?: string;
}

/** The training spec a node carries, as `_train` receives it. */
export interface TrainNodeParams {
  task: ModelTask | null;
  target: string;
  /** `null` means "every column but the target", which is the server default. */
  features: string[] | null;
  algo: string;
  knobs: Record<string, number>;
  test_size: number;
  cross_validation: number;
  model_name: string;
  sources: MlSourcePin[];
}

/** The model reference a serving node carries, as `_predict` receives it. */
export interface PredictNodeParams {
  model_id: string;
  model_slug: string;
  /** A pinned version answers forever; unpinned follows the champion. */
  pinned_version: number | null;
  output_name: string;
  explain: boolean;
  sources: MlSourcePin[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function paramsOf(node: CanonicalFlowNode | null | undefined): Record<string, unknown> {
  const config = node && isRecord(node.config) ? node.config : {};
  return isRecord(config['params']) ? config['params'] : {};
}

function slugOf(node: CanonicalFlowNode | null | undefined): string {
  if (!node || (node.kind ?? 'task') !== 'task') return '';
  const config = isRecord(node.config) ? node.config : {};
  return typeof config['skill_slug'] === 'string' ? config['skill_slug'] : '';
}

/** Which model role a node plays, or `null` when it plays none. */
export function mlNodeRole(
  node: CanonicalFlowNode | null | undefined,
): MlNodeRole | null {
  switch (slugOf(node)) {
    case ML_TRAIN_SKILL_SLUG:
      return 'train';
    case ML_PREDICT_SKILL_SLUG:
      return 'predict';
    case ML_SCORE_SKILL_SLUG:
      return 'score';
    default:
      return null;
  }
}

export function isTrainNode(node: CanonicalFlowNode | null | undefined): boolean {
  return mlNodeRole(node) === 'train';
}

/** True for either serving shape: one record inline, or a whole dataset. */
export function isServingNode(node: CanonicalFlowNode | null | undefined): boolean {
  const role = mlNodeRole(node);
  return role === 'predict' || role === 'score';
}

export function isBatchScoreNode(node: CanonicalFlowNode | null | undefined): boolean {
  return mlNodeRole(node) === 'score';
}

/** Everything that differs between the two serving shapes, as data. */
export interface ServingRoleDescriptor {
  role: 'predict' | 'score';
  skillSlug: string;
  icon: string;
  /** A dataset node names what it writes; a single-record node writes nothing. */
  writesDataset: boolean;
  /** Only the inline shape can afford per-row contributions. */
  supportsExplain: boolean;
  copy: { section: string; hint: string };
}

export const SERVING_ROLES: Readonly<Record<'predict' | 'score', ServingRoleDescriptor>> =
  {
    predict: {
      role: 'predict',
      skillSlug: ML_PREDICT_SKILL_SLUG,
      icon: 'zap',
      writesDataset: false,
      supportsExplain: true,
      copy: {
        section: 'flow.inspector.section.predict',
        hint: 'flow.ml.predict.inspector.hint',
      },
    },
    score: {
      role: 'score',
      skillSlug: ML_SCORE_SKILL_SLUG,
      icon: 'target',
      writesDataset: true,
      supportsExplain: false,
      copy: {
        section: 'flow.inspector.section.score',
        hint: 'flow.ml.score.inspector.hint',
      },
    },
  };

export function servingDescriptor(
  node: CanonicalFlowNode | null | undefined,
): ServingRoleDescriptor | null {
  const role = mlNodeRole(node);
  if (role !== 'predict' && role !== 'score') return null;
  return SERVING_ROLES[role];
}

export function clampTestSize(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return TRAIN_TEST_SIZE_DEFAULT;
  return Math.min(TRAIN_TEST_SIZE_MAX, Math.max(TRAIN_TEST_SIZE_MIN, parsed));
}

/** Folds, or 0 for off. Anything not on the offered list rounds down to off. */
export function clampFolds(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(parsed)) return 0;
  const rounded = Math.round(parsed);
  return TRAIN_CV_OPTIONS.includes(rounded) ? rounded : 0;
}

function readPin(value: unknown): MlSourcePin | null {
  if (!isRecord(value)) return null;
  const pin: MlSourcePin = {};
  const id = value['dataset_id'];
  if (typeof id === 'string' && id.trim()) pin.dataset_id = id.trim();
  const slug = value['dataset_slug'] ?? value['slug'];
  if (typeof slug === 'string' && slug.trim()) pin.dataset_slug = slug.trim();
  return pin.dataset_id || pin.dataset_slug ? pin : null;
}

function readPins(value: unknown): MlSourcePin[] {
  if (!Array.isArray(value)) return [];
  return value.map(readPin).filter((pin): pin is MlSourcePin => pin !== null);
}

/** The `config.params` bag a freshly dropped training node carries. */
export function trainDefaultParams(): Record<string, unknown> {
  return {
    task: null,
    target: '',
    features: null,
    algo: '',
    knobs: {},
    test_size: TRAIN_TEST_SIZE_DEFAULT,
    cross_validation: 0,
    model_name: '',
    sources: [],
  };
}

/** The `config.params` bag a freshly dropped serving node carries. */
export function predictDefaultParams(role: 'predict' | 'score'): Record<string, unknown> {
  const params: Record<string, unknown> = {
    model_id: '',
    model_slug: '',
    pinned_version: null,
    sources: [],
  };
  if (SERVING_ROLES[role].writesDataset) params['output_name'] = '';
  if (SERVING_ROLES[role].supportsExplain) params['explain'] = false;
  return params;
}

export function readTrainParams(
  node: CanonicalFlowNode | null | undefined,
): TrainNodeParams {
  const params = paramsOf(node);
  const task = params['task'];
  const features = params['features'];
  const knobs: Record<string, number> = {};
  if (isRecord(params['knobs'])) {
    for (const [key, value] of Object.entries(params['knobs'])) {
      const parsed = typeof value === 'number' ? value : Number(value);
      if (Number.isFinite(parsed)) knobs[key] = parsed;
    }
  }
  return {
    task: task === 'classification' || task === 'regression' ? task : null,
    target: typeof params['target'] === 'string' ? params['target'].trim() : '',
    features: Array.isArray(features)
      ? features.filter((name): name is string => typeof name === 'string' && !!name)
      : null,
    algo: typeof params['algo'] === 'string' ? params['algo'].trim() : '',
    knobs,
    test_size: clampTestSize(params['test_size']),
    cross_validation: clampFolds(params['cross_validation']),
    model_name:
      typeof params['model_name'] === 'string' ? params['model_name'].trim() : '',
    sources: readPins(params['sources']),
  };
}

export function readPredictParams(
  node: CanonicalFlowNode | null | undefined,
): PredictNodeParams {
  const params = paramsOf(node);
  const version = params['pinned_version'];
  const parsedVersion = typeof version === 'number' ? version : Number(version);
  return {
    model_id: typeof params['model_id'] === 'string' ? params['model_id'].trim() : '',
    model_slug:
      typeof params['model_slug'] === 'string' ? params['model_slug'].trim() : '',
    pinned_version:
      version === null || version === undefined || !Number.isFinite(parsedVersion)
        ? null
        : Math.max(1, Math.round(parsedVersion)),
    output_name:
      typeof params['output_name'] === 'string' ? params['output_name'].trim() : '',
    explain: params['explain'] === true,
    sources: readPins(params['sources']),
  };
}

/** The one dataset a node reads, pinned. `null` when it takes the wire. */
export function pinnedDataset(pins: readonly MlSourcePin[]): MlSourcePin | null {
  return pins[0] ?? null;
}

export interface MlFailure {
  /** Dictionary key for the human sentence. */
  key: string;
  /** The offending value, when naming it is the actionable part. */
  detail?: string;
}

/**
 * Refusals the model NODES own, and nothing else.
 *
 * Deliberately short. Every refusal about a *spec* — a target that is not in
 * the table, one class, too few rows, an estimator that cannot do the task —
 * already has one sentence in the model plane's dictionary, and a second copy
 * under a `flow.` key would be a second sentence to keep true. What is left
 * here is the two the node wrappers raise about WIRING (`ML_NO_DATASET`,
 * `ML_SCORE_DATASET_REQUIRED` — a canvas concern the Models page cannot have)
 * and the two this module raises itself before spending a round-trip.
 */
export const FLOW_ML_ERROR_CODES: readonly string[] = [
  'ML_NO_DATASET',
  'ML_SCORE_DATASET_REQUIRED',
  'ML_MODEL_REQUIRED',
  'ML_TARGET_IN_FEATURES',
];

/**
 * Project a refusal code into a translated sentence plus its detail.
 *
 * Resolution order is a claim about ownership: a node refusal is a node
 * refusal, and everything else is the model plane's to phrase — the same
 * sentence whether the fit was dispatched from the Models page or from a node.
 * An unknown code keeps the server's own words rather than rendering a blank:
 * a refusal nobody can name is still a refusal the author has to read.
 */
export function mlFailure(
  code: string | null | undefined,
  message?: string | null,
): MlFailure {
  const normalized = (code ?? '').trim().toUpperCase();
  const detail = (message ?? '').trim() || undefined;
  if (FLOW_ML_ERROR_CODES.includes(normalized)) {
    return { key: `flow.ml.error.${normalized.toLowerCase()}` };
  }
  const shared =
    refusalKey(normalized) ??
    trainingErrorKey(normalized) ??
    servingErrorKey(normalized);
  if (shared) return { key: shared, detail };
  return { key: 'flow.ml.error.unknown', detail };
}

/**
 * Client-side pre-check of a training node, kept narrower than the server's.
 *
 * Only the refusals an author hits by construction are worth blocking a
 * round-trip for: no dataset to fit on, no column to predict, an empty feature
 * set, and the target smuggled into its own features. Everything else — too few
 * rows, a target with one class, a feature that memorises the table — is the
 * plan endpoint's call, and it answers it against the real data rather than
 * against this bag.
 */
export function preflightTrain(
  params: TrainNodeParams,
  options: { wired?: boolean } = {},
): MlFailure | null {
  if (params.sources.length === 0 && !options.wired) {
    return mlFailure('ML_NO_DATASET');
  }
  if (!params.target) return mlFailure('ML_TARGET_REQUIRED');
  if (params.features !== null && params.features.length === 0) {
    return mlFailure('ML_FEATURES_REQUIRED');
  }
  if (params.features !== null && params.features.includes(params.target)) {
    return { ...mlFailure('ML_TARGET_IN_FEATURES'), detail: params.target };
  }
  return null;
}

/** Client-side pre-check of a serving node: it has to name a model. */
export function preflightServing(
  params: PredictNodeParams,
  descriptor: ServingRoleDescriptor,
  options: { wired?: boolean } = {},
): MlFailure | null {
  if (!params.model_id && !params.model_slug) {
    return mlFailure('ML_MODEL_REQUIRED');
  }
  if (descriptor.writesDataset && params.sources.length === 0 && !options.wired) {
    return mlFailure('ML_SCORE_DATASET_REQUIRED');
  }
  return null;
}

/**
 * One-line summary of what a training node will fit, for the inspector.
 *
 * Deliberately the target and not the algorithm: on a canvas, "predicts churn"
 * identifies a node and "gradient boosting" does not.
 */
export function trainSummary(params: TrainNodeParams): string {
  if (!params.target) return '';
  const count =
    params.features === null ? null : params.features.length;
  return count === null ? params.target : `${params.target} · ${count}`;
}

/**
 * Which model version a serving node will call, spelled for the inspector.
 *
 * A pinned version and a following one are genuinely different promises, so
 * they read differently: `churn-risk v3` answers forever, `churn-risk` follows
 * whatever is promoted next.
 */
export function servingSummary(
  params: PredictNodeParams,
  models: readonly ModelDto[] = [],
): { label: string; pinned: boolean } | null {
  const byId = params.model_id
    ? models.find((model) => model.id === params.model_id)
    : undefined;
  const slug = params.model_slug || byId?.slug || '';
  const name = byId?.name || slug;
  if (!name) return null;
  const version = params.pinned_version ?? (params.model_id ? byId?.version : null);
  return {
    label: version ? `${name} v${version}` : name,
    pinned: params.pinned_version !== null || (!!params.model_id && !params.model_slug),
  };
}

/**
 * Models a serving node may call: the ready ones, newest lineage first.
 *
 * A model still training cannot answer, and offering it would turn a
 * configuration mistake into a run-time refusal — the picker is the right place
 * to make that impossible.
 */
export function servableModels(models: readonly ModelDto[]): ModelDto[] {
  return models
    .filter((model) => model.status === 'ready')
    .sort(
      (left, right) =>
        left.slug.localeCompare(right.slug) || right.version - left.version,
    );
}

/** Every version of one lineage, newest first — what the version pin offers. */
export function lineageVersions(
  models: readonly ModelDto[],
  slug: string,
): ModelDto[] {
  if (!slug) return [];
  return models
    .filter((model) => model.slug === slug && model.status === 'ready')
    .sort((left, right) => right.version - left.version);
}

/**
 * The params patch that points a node at a model.
 *
 * Choosing a lineage writes the SLUG and clears the id, so the node follows
 * whichever version is promoted — that is the whole champion/challenger story,
 * and it only works if the graph does not freeze an id behind the author's
 * back. Pinning a version is the explicit opposite gesture.
 */
export function chooseModelPatch(model: ModelDto): Record<string, unknown> {
  return { model_slug: model.slug, model_id: '', pinned_version: null };
}

export function pinVersionPatch(version: number | null): Record<string, unknown> {
  return { pinned_version: version && version > 0 ? Math.round(version) : null };
}

export { TRAIN_STEPS };
