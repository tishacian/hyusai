import {
  readWorkspaceLocalJson,
  writeWorkspaceLocalJson,
  type WorkspaceLocalStorage,
} from './workspace-local-storage';

export const LAST_EVAL_CONTEXT_STORAGE_KEY = 'agentium:last_eval_context';

export interface LastEvalContext {
  agent_id: string | null;
  query: string;
  response: string;
}

interface StoredLastEvalContext extends LastEvalContext {
  workspace_slug?: string;
}

export function persistWorkspaceEvalContext(
  storage: WorkspaceLocalStorage,
  workspaceSlug: string | null,
  context: LastEvalContext,
): boolean {
  if (!workspaceSlug) return false;
  return writeWorkspaceLocalJson(storage, LAST_EVAL_CONTEXT_STORAGE_KEY, workspaceSlug, {
    ...context,
    workspace_slug: workspaceSlug,
  });
}

export function readWorkspaceEvalContext(
  storage: WorkspaceLocalStorage,
  workspaceSlug: string | null,
  knownWorkspaceSlugs: readonly string[],
): LastEvalContext | null {
  const stored = readWorkspaceLocalJson<StoredLastEvalContext>({
    storage,
    baseKey: LAST_EVAL_CONTEXT_STORAGE_KEY,
    workspaceSlug,
    knownWorkspaceSlugs,
    isValue: isStoredLastEvalContext,
    valueWorkspaceSlug: (value) => value.workspace_slug ?? null,
  });
  if (!stored) return null;

  // Storage provenance is deliberately stripped from the backend payload.
  return {
    agent_id: stored.agent_id,
    query: stored.query,
    response: stored.response,
  };
}

function isStoredLastEvalContext(value: unknown): value is StoredLastEvalContext {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  const validAgentId =
    candidate['agent_id'] === null || typeof candidate['agent_id'] === 'string';
  return (
    validAgentId &&
    typeof candidate['query'] === 'string' &&
    candidate['query'].length > 0 &&
    typeof candidate['response'] === 'string' &&
    candidate['response'].length > 0 &&
    (candidate['workspace_slug'] === undefined ||
      typeof candidate['workspace_slug'] === 'string')
  );
}
