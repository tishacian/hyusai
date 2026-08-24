/**
 * Python recipe node — pure view-model helpers.
 *
 * A recipe node is an ordinary `task` node bound to the seeded
 * `python_recipe_v1` Skill; everything the execution plane needs lives under
 * `config.params` and is versioned with the flow. This module owns the
 * client-side reading/normalisation of that bag plus the status projections
 * the inspector, workshop and tests share. It mirrors — never replaces — the
 * backend rules in `app/services/recipe_envs.py`: the server stays the
 * authority, the client only pre-validates to fail fast in the UI.
 *
 * Dependency-light on purpose (no Angular imports) so `run-unit.mjs` can
 * exercise it in plain Node.
 */
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';

export const RECIPE_SKILL_SLUG = 'python_recipe_v1';

/** Mirror of the backend clamp (`recipe_execution_*_timeout_s`). */
export const RECIPE_TIMEOUT_DEFAULT_S = 120;
export const RECIPE_TIMEOUT_MAX_S = 600;

/** Mirror of `_MAX_REQUIREMENT_LINES` server-side. */
export const RECIPE_MAX_REQUIREMENT_LINES = 200;

/** The authoring contract, pre-filled so a dropped node runs as-is. */
export const RECIPE_DEFAULT_CODE = `def main(inputs: dict) -> dict:
    """Recipe entry point.

    'inputs' carries the upstream node payload; the returned dict is the
    node output (it must be JSON-serialisable).
    """
    return {"echo": inputs}
`;

export interface RecipeNodeParams {
  code: string;
  requirements_text: string;
  index_url: string;
  extra_index_urls: string[];
  timeout_s: number;
}

/** Statuses of a managed Python environment (mirrors `PythonEnv.status`). */
export type RecipeEnvStatus = 'pending' | 'building' | 'ready' | 'failed' | 'evicted';

/** Lifecycle of one recipe execution (mirrors `RecipeExecution.status`). */
export type RecipeExecutionStatus =
  | 'queued'
  | 'env_building'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'timed_out';

export const RECIPE_EXECUTION_ACTIVE_STATUSES: readonly RecipeExecutionStatus[] = [
  'queued',
  'env_building',
  'running',
];

/** The ordered timeline the Test tab renders (terminal state appended last). */
export const RECIPE_EXECUTION_TIMELINE: readonly RecipeExecutionStatus[] = [
  'queued',
  'env_building',
  'running',
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** True when the node is a `task` bound to the recipe Skill. */
export function isPythonRecipeNode(node: CanonicalFlowNode | null | undefined): boolean {
  if (!node || (node.kind ?? 'task') !== 'task') return false;
  const config = isRecord(node.config) ? node.config : {};
  return config['skill_slug'] === RECIPE_SKILL_SLUG;
}

/** Default `config.params` seeded on palette drop and read-fallback. */
export function recipeDefaultParams(): RecipeNodeParams {
  return {
    code: RECIPE_DEFAULT_CODE,
    requirements_text: '',
    index_url: '',
    extra_index_urls: [],
    timeout_s: RECIPE_TIMEOUT_DEFAULT_S,
  };
}

/** Clamp an authored timeout to the executable window (mirror of the server). */
export function clampRecipeTimeout(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number(String(value ?? '').trim());
  if (!Number.isFinite(parsed) || parsed <= 0) return RECIPE_TIMEOUT_DEFAULT_S;
  return Math.min(Math.max(Math.round(parsed), 1), RECIPE_TIMEOUT_MAX_S);
}

/** Read the recipe params off a node, with defaults for anything unset. */
export function readRecipeParams(node: CanonicalFlowNode | null | undefined): RecipeNodeParams {
  const defaults = recipeDefaultParams();
  const config = node && isRecord(node.config) ? node.config : {};
  const params = isRecord(config['params']) ? config['params'] : {};
  const extras = Array.isArray(params['extra_index_urls'])
    ? params['extra_index_urls'].map((item) => String(item ?? '').trim()).filter(Boolean)
    : defaults.extra_index_urls;
  return {
    code: typeof params['code'] === 'string' ? params['code'] : defaults.code,
    requirements_text:
      typeof params['requirements_text'] === 'string'
        ? params['requirements_text']
        : defaults.requirements_text,
    index_url: typeof params['index_url'] === 'string' ? params['index_url'].trim() : '',
    extra_index_urls: extras,
    timeout_s:
      params['timeout_s'] === undefined
        ? defaults.timeout_s
        : clampRecipeTimeout(params['timeout_s']),
  };
}

export interface RequirementsPreview {
  /** Canonical requirement lines (comments/blanks dropped, sorted, deduped). */
  lines: string[];
  /** Lines the server would refuse (pip options such as `-r`, `--index-url`). */
  invalid: string[];
  /** True when the count exceeds the server bound. */
  tooMany: boolean;
}

/**
 * Client-side preview of the server normalisation: same dropping of comments
 * and blanks, same whitespace collapse, same dedupe + casefold sort, same
 * fail-closed stance on pip option lines. Used to summarise a spec and to
 * warn before a request that would 422.
 */
export function previewRequirements(text: string): RequirementsPreview {
  const seen = new Set<string>();
  const invalid: string[] = [];
  for (const rawLine of text.split(/\r?\n/)) {
    const withoutComment = rawLine.split('#', 1)[0] ?? '';
    const line = withoutComment.trim().replace(/\s+/g, ' ');
    if (!line) continue;
    if (!/^[A-Za-z0-9]/.test(line)) {
      invalid.push(line);
      continue;
    }
    seen.add(line);
  }
  const lines = [...seen].sort((a, b) =>
    a.toLowerCase() < b.toLowerCase() ? -1 : a.toLowerCase() > b.toLowerCase() ? 1 : 0,
  );
  return {
    lines,
    invalid,
    tooMany: lines.length > RECIPE_MAX_REQUIREMENT_LINES,
  };
}

/**
 * Cache identity of a spec: exactly the fields the backend fingerprint
 * hashes (normalised requirements + registries) — never the script.
 */
export function recipeSpecKey(params: RecipeNodeParams): string {
  return JSON.stringify([
    previewRequirements(params.requirements_text).lines,
    params.index_url.trim(),
    params.extra_index_urls.map((url) => url.trim()).filter(Boolean),
  ]);
}

/** i18n key for an environment status (server value → dictionary key). */
export function recipeEnvStatusKey(status: string): string {
  return `flow.recipe.env.status.${status}`;
}

/** i18n key for an execution status (server value → dictionary key). */
export function recipeExecutionStatusKey(status: string): string {
  return `flow.recipe.execution.status.${status}`;
}

/** True while an execution can still be cancelled. */
export function isActiveRecipeExecution(status: string): boolean {
  return (RECIPE_EXECUTION_ACTIVE_STATUSES as readonly string[]).includes(status);
}

/** A localisable projection of `RecipeExecution.error` (a machine code). */
export interface RecipeExecutionReason {
  /** Dictionary key for the human sentence. */
  key: string;
  params?: Record<string, string | number>;
  /** Machine detail worth keeping next to the sentence (stderr line, build error). */
  detail?: string;
}

/**
 * Map the server's machine reason (`cancel_requested`, `recipe_exit_1: …`) to
 * an i18n key plus the detail worth surfacing. The raw code never reaches the
 * author untranslated; unknown codes fall back to a generic sentence with the
 * code kept as detail.
 */
export function recipeExecutionReason(error: string): RecipeExecutionReason {
  const raw = error.trim();
  const plain: Record<string, string> = {
    cancel_requested: 'flow.recipe.reason.cancel_requested',
    recipe_env_not_found: 'flow.recipe.reason.env_not_found',
    recipe_worker_lost_after_claim: 'flow.recipe.reason.worker_lost',
    recipe_execution_disabled: 'flow.recipe.reason.disabled',
    recipe_output_too_large: 'flow.recipe.reason.output_too_large',
    recipe_output_not_object: 'flow.recipe.reason.output_not_object',
    recipe_output_unreadable: 'flow.recipe.reason.output_unreadable',
  };
  if (plain[raw]) return { key: plain[raw] };
  const timeout = /^recipe_timeout_after_(\d+)s$/.exec(raw);
  if (timeout) {
    return { key: 'flow.recipe.reason.timeout', params: { seconds: timeout[1] } };
  }
  const build = /^recipe_env_build_failed(?::\s*([\s\S]*))?$/.exec(raw);
  if (build) {
    return { key: 'flow.recipe.reason.env_build_failed', detail: build[1] || undefined };
  }
  const exit = /^recipe_exit_(-?\d+)(?::\s*([\s\S]*))?$/.exec(raw);
  if (exit) {
    return {
      key: 'flow.recipe.reason.exit',
      params: { code: exit[1] },
      detail: exit[2] || undefined,
    };
  }
  return { key: 'flow.recipe.reason.unknown', detail: raw };
}

/** Visual step state for the Test-tab timeline. */
export type RecipeTimelineStepState = 'done' | 'current' | 'upcoming';

export interface RecipeTimelineStep {
  status: RecipeExecutionStatus;
  state: RecipeTimelineStepState;
}

/**
 * Project an execution status onto the fixed queued → env_building → running
 * timeline. A terminal status marks every phase as done; `env_building` may
 * be skipped entirely when the env was already ready — the projection then
 * marks it done rather than pretending it is pending.
 */
export function recipeTimeline(status: string): RecipeTimelineStep[] {
  const order = RECIPE_EXECUTION_TIMELINE as readonly string[];
  const index = order.indexOf(status);
  const terminal = !isActiveRecipeExecution(status) && status !== '';
  return order.map((step, stepIndex) => ({
    status: step as RecipeExecutionStatus,
    state: terminal
      ? 'done'
      : index === -1
        ? 'upcoming'
        : stepIndex < index
          ? 'done'
          : stepIndex === index
            ? 'current'
            : 'upcoming',
  }));
}

/** First characters of a fingerprint, enough to recognise an env in the UI. */
export function shortFingerprint(fingerprint: string | null | undefined): string {
  return (fingerprint ?? '').slice(0, 12);
}

/** Human-readable byte size (fr/en neutral: unit symbols only). */
export function formatBytes(bytes: number | null | undefined): string {
  const value = typeof bytes === 'number' && Number.isFinite(bytes) ? Math.max(bytes, 0) : 0;
  if (value < 1024) return `${value} o`;
  const units = ['Kio', 'Mio', 'Gio', 'Tio'];
  let scaled = value;
  let unit = 'o';
  for (const next of units) {
    if (scaled < 1024) break;
    scaled /= 1024;
    unit = next;
  }
  return `${scaled >= 10 ? Math.round(scaled) : Math.round(scaled * 10) / 10} ${unit}`;
}

/** One-line summary of the script for the inspector (first def / first line). */
export function recipeCodeSummary(code: string): string {
  const lines = code.split(/\r?\n/);
  const signature = lines.find((line) => line.trim().startsWith('def '));
  const first = signature ?? lines.find((line) => line.trim().length > 0) ?? '';
  return first.trim().slice(0, 80);
}

/** Line count of the authored script (empty script → 0). */
export function recipeCodeLineCount(code: string): number {
  if (!code.trim()) return 0;
  return code.replace(/\n$/, '').split('\n').length;
}
