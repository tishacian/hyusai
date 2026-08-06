import type { CanonicalFlow } from '@app/core/flow-serializer.service';
import {
  readWorkspaceLocalJson,
  removeWorkspaceLocalValue,
  writeWorkspaceLocalJson,
  type WorkspaceLocalStorage,
} from '@app/core/workspace-local-storage';

export const SCRATCH_DRAFT_STORAGE_KEY = 'agentium.flow.draft.scratch';

interface DraftEnvelope {
  v: 1;
  workspace_slug?: string;
  saved_at: number;
  flow: CanonicalFlow;
}

type StoredDraft = DraftEnvelope | CanonicalFlow;

export interface WorkspaceFlowDraft {
  flow: CanonicalFlow;
  savedAt: number | null;
}

export function persistWorkspaceFlowDraft(
  storage: WorkspaceLocalStorage,
  workspaceSlug: string | null,
  flow: CanonicalFlow,
  savedAt = Date.now(),
): WorkspaceFlowDraft | null {
  if (!workspaceSlug) return null;
  const envelope: DraftEnvelope = {
    v: 1,
    workspace_slug: workspaceSlug,
    saved_at: savedAt,
    flow,
  };
  if (!writeWorkspaceLocalJson(storage, SCRATCH_DRAFT_STORAGE_KEY, workspaceSlug, envelope)) {
    return null;
  }
  return { flow, savedAt };
}

export function readWorkspaceFlowDraft(
  storage: WorkspaceLocalStorage,
  workspaceSlug: string | null,
  knownWorkspaceSlugs: readonly string[],
): WorkspaceFlowDraft | null {
  const stored = readWorkspaceLocalJson<StoredDraft>({
    storage,
    baseKey: SCRATCH_DRAFT_STORAGE_KEY,
    workspaceSlug,
    knownWorkspaceSlugs,
    isValue: isStoredDraft,
    valueWorkspaceSlug: draftWorkspaceSlug,
  });
  if (!stored) return null;

  if (isDraftEnvelope(stored)) {
    return { flow: stored.flow, savedAt: stored.saved_at };
  }
  return { flow: stored, savedAt: null };
}

export function clearWorkspaceFlowDraft(
  storage: WorkspaceLocalStorage,
  workspaceSlug: string | null,
): void {
  removeWorkspaceLocalValue(storage, SCRATCH_DRAFT_STORAGE_KEY, workspaceSlug);
}

function isStoredDraft(value: unknown): value is StoredDraft {
  return isFlowLike(value) || isDraftEnvelope(value);
}

function isDraftEnvelope(value: unknown): value is DraftEnvelope {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  return (
    candidate['v'] === 1 &&
    typeof candidate['saved_at'] === 'number' &&
    Number.isFinite(candidate['saved_at']) &&
    isFlowLike(candidate['flow']) &&
    (candidate['workspace_slug'] === undefined ||
      typeof candidate['workspace_slug'] === 'string')
  );
}

function isPortList(value: unknown): boolean {
  return (
    value === undefined ||
    (Array.isArray(value) &&
      value.every(
        (port) =>
          !!port &&
          typeof port === 'object' &&
          !Array.isArray(port) &&
          typeof (port as { name?: unknown }).name === 'string' &&
          ((port as { schema?: unknown }).schema === undefined ||
            typeof (port as { schema?: unknown }).schema === 'string'),
      ))
  );
}

function isFlowLike(value: unknown): value is CanonicalFlow {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const candidate = value as {
    nodes?: unknown;
    edges?: unknown;
    variable_namespaces?: unknown;
  };
  return (
    (candidate.variable_namespaces === undefined ||
      (Array.isArray(candidate.variable_namespaces) &&
        candidate.variable_namespaces.every((item) => typeof item === 'string'))) &&
    Array.isArray(candidate.nodes) &&
    candidate.nodes.every(
      (node) =>
        !!node &&
        typeof node === 'object' &&
        !Array.isArray(node) &&
        typeof (node as { id?: unknown }).id === 'string' &&
        isPortList((node as { inputs?: unknown }).inputs) &&
        isPortList((node as { outputs?: unknown }).outputs) &&
        ((node as { config?: unknown }).config === undefined ||
          (!!(node as { config?: unknown }).config &&
            typeof (node as { config?: unknown }).config === 'object' &&
            !Array.isArray((node as { config?: unknown }).config))),
    ) &&
    Array.isArray(candidate.edges) &&
    candidate.edges.every(
      (edge) =>
        !!edge &&
        typeof edge === 'object' &&
        !Array.isArray(edge) &&
        typeof (edge as { from?: unknown }).from === 'string' &&
        typeof (edge as { to?: unknown }).to === 'string',
    )
  );
}

function draftWorkspaceSlug(value: StoredDraft): string | null {
  return isDraftEnvelope(value) ? value.workspace_slug ?? null : null;
}
