import type { DataPrepSpec, PrepDraft, PrepExecution, PrepPreview } from './dataops.models';

/**
 * What the standalone preparation page may say about an execution (plan
 * UI/UX, lot 6, US21 and US22). A cancel asked for stays "requested" until
 * the server reports the run stopped, and a run is never "ready" unless the
 * server succeeded and returned the dataset it wrote.
 */
export type PrepPhase =
  | 'active'
  | 'cancel_requested'
  | 'succeeded'
  | 'incomplete'
  | 'failed'
  | 'cancelled'
  | 'timed_out';

const ACTIVE = new Set(['queued', 'running', 'pending', 'created']);

export function prepPhase(execution: PrepExecution | null): PrepPhase | null {
  if (!execution) return null;
  if (ACTIVE.has(execution.status)) return execution.cancel_requested ? 'cancel_requested' : 'active';
  if (execution.status === 'succeeded') return preparedOutputs(execution).length ? 'succeeded' : 'incomplete';
  if (execution.status === 'cancelled' || execution.status === 'timed_out') return execution.status;
  return 'failed';
}

export function prepIsActive(execution: PrepExecution | null): boolean {
  const phase = prepPhase(execution);
  return phase === 'active' || phase === 'cancel_requested';
}

export interface PreparedOutput {
  readonly port: string;
  readonly datasetId: string;
  readonly name: string | null;
  readonly version: number | null;
  /** A first version is a new dataset; any later one is a version of an existing dataset. */
  readonly kind: 'dataset' | 'version';
}

/** The datasets a succeeded execution confirmed, never those it only reserved. */
export function preparedOutputs(execution: PrepExecution | null): PreparedOutput[] {
  if (!execution || execution.status !== 'succeeded') return [];
  const output = execution.output_json ?? execution.output ?? {};
  const refs = output['outputs'];
  if (!refs || typeof refs !== 'object' || Array.isArray(refs)) return [];
  return Object.entries(refs as Record<string, unknown>).flatMap(([port, value]) => {
    if (!value || typeof value !== 'object') return [];
    const ref = value as Record<string, unknown>;
    if (typeof ref['dataset_id'] !== 'string' || !ref['dataset_id']) return [];
    const version = typeof ref['version'] === 'number' && Number.isInteger(ref['version']) && ref['version'] > 0 ? ref['version'] : null;
    return [{
      port,
      datasetId: ref['dataset_id'],
      name: typeof ref['name'] === 'string' && ref['name'] ? ref['name'] : null,
      version,
      kind: version !== null && version > 1 ? 'version' : 'dataset',
    }];
  });
}

/** What an output will create, said before the run from the draft alone. */
export function plannedOutputKind(spec: DataPrepSpec, port: string): 'dataset' | 'version' {
  return spec.outputs.find((output) => output.port === port)?.append_version_of ? 'version' : 'dataset';
}

export interface SampleSize {
  readonly rows: number;
  /** Rows of the input the sample was drawn from, when the server said. */
  readonly of: number | null;
}

/** The size of the sample a preview really read, or null when the server did not say. */
export function sampleSize(preview: PrepPreview | null): SampleSize | null {
  const info = preview?.sample_info;
  if (!info || typeof info.rows !== 'number' || !Number.isFinite(info.rows) || info.rows < 0) return null;
  const of = typeof info.of_rows === 'number' && Number.isFinite(info.of_rows) && info.of_rows >= 0 ? info.of_rows : null;
  return { rows: info.rows, of };
}

// --- Draft kept in the browser session (decision of 20 October) ------------

const DRAFT_KEY = 'agentium.dataprep.draft.';

export interface StoredPrepDraft {
  readonly draft: PrepDraft;
  readonly savedAt: number;
}

/** The session draft of one workspace; nothing is written on the server. */
export function readStoredDraft(storage: Storage | null, workspaceId: string | null): StoredPrepDraft | null {
  if (!storage || !workspaceId) return null;
  try {
    const raw = storage.getItem(DRAFT_KEY + workspaceId);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredPrepDraft>;
    const draft = parsed?.draft;
    if (!draft || typeof draft !== 'object' || !draft.spec || !Array.isArray(draft.spec.steps)
      || !Array.isArray(draft.spec.outputs) || !draft.inputs || typeof draft.inputs !== 'object') return null;
    return { draft, savedAt: typeof parsed.savedAt === 'number' ? parsed.savedAt : 0 };
  } catch {
    return null;
  }
}

export function writeStoredDraft(storage: Storage | null, workspaceId: string | null, draft: PrepDraft, now = Date.now()): boolean {
  if (!storage || !workspaceId) return false;
  try {
    storage.setItem(DRAFT_KEY + workspaceId, JSON.stringify({ draft, savedAt: now }));
    return true;
  } catch {
    return false;
  }
}

export function clearStoredDraft(storage: Storage | null, workspaceId: string | null): void {
  if (!storage || !workspaceId) return;
  try { storage.removeItem(DRAFT_KEY + workspaceId); } catch { /* storage blocked: nothing to clear */ }
}

/** Execution ids are server ids; anything else in the URL is ignored. */
export function executionIdFromQuery(value: string | null | undefined): string | null {
  return typeof value === 'string' && /^[A-Za-z0-9-]{1,64}$/.test(value) ? value : null;
}
