/** Minimal storage surface used by the workspace-scoped persistence helpers. */
export type WorkspaceLocalStorage = Pick<
  Storage,
  'getItem' | 'setItem' | 'removeItem'
>;

export interface ReadWorkspaceLocalJsonOptions<T> {
  storage: WorkspaceLocalStorage;
  baseKey: string;
  workspaceSlug: string | null;
  knownWorkspaceSlugs: readonly string[];
  isValue: (value: unknown) => value is T;
  /** Optional provenance carried by newer values (legacy values may omit it). */
  valueWorkspaceSlug?: (value: T) => string | null;
  /** Only non-sensitive preferences may infer origin from a sole workspace. */
  allowUntaggedLegacyForSoleWorkspace?: boolean;
}

/** The only supported key shape for tenant-owned browser state. */
export function workspaceLocalStorageKey(baseKey: string, workspaceSlug: string): string {
  return `${baseKey}:${workspaceSlug}`;
}

/**
 * Read a workspace-scoped JSON value and, when necessary, consume the old
 * unsuffixed slot exactly once.
 *
 * An untagged legacy value is untrusted by default. Callers may explicitly
 * allow sole-workspace attribution for non-sensitive preferences only. In
 * every other case the slot is removed instead of guessing, so visiting
 * workspace B can never adopt workspace A's business data.
 */
export function readWorkspaceLocalJson<T>(
  options: ReadWorkspaceLocalJsonOptions<T>,
): T | null {
  const {
    storage,
    baseKey,
    workspaceSlug,
    knownWorkspaceSlugs,
    isValue,
    valueWorkspaceSlug,
    allowUntaggedLegacyForSoleWorkspace = false,
  } = options;

  if (!workspaceSlug) {
    removeQuietly(storage, baseKey);
    return null;
  }

  const scopedKey = workspaceLocalStorageKey(baseKey, workspaceSlug);
  const scopedRaw = getQuietly(storage, scopedKey);
  if (scopedRaw !== null) {
    // A scoped value wins. Retire a leftover legacy slot so another workspace
    // cannot attempt to migrate it later.
    removeQuietly(storage, baseKey);
    return parseScopedValue(
      storage,
      scopedKey,
      scopedRaw,
      workspaceSlug,
      isValue,
      valueWorkspaceSlug,
    );
  }

  const legacyRaw = getQuietly(storage, baseKey);
  if (legacyRaw === null) return null;

  // Consume before parsing/adopting: malformed or ambiguous data must not be
  // reconsidered under a different tenant on the next navigation.
  removeQuietly(storage, baseKey);

  let parsed: unknown;
  try {
    parsed = JSON.parse(legacyRaw) as unknown;
  } catch {
    return null;
  }
  if (!isValue(parsed)) return null;

  const embeddedSlug = valueWorkspaceSlug?.(parsed) || null;
  const attributable = embeddedSlug
    ? embeddedSlug === workspaceSlug
    : allowUntaggedLegacyForSoleWorkspace &&
      soleKnownWorkspaceSlug(knownWorkspaceSlugs) === workspaceSlug;
  if (!attributable) return null;

  try {
    storage.setItem(scopedKey, legacyRaw);
  } catch {
    return null;
  }
  return parsed;
}

/** Write JSON only when a real workspace scope exists. */
export function writeWorkspaceLocalJson<T>(
  storage: WorkspaceLocalStorage,
  baseKey: string,
  workspaceSlug: string | null,
  value: T,
): boolean {
  if (!workspaceSlug) return false;
  try {
    storage.setItem(
      workspaceLocalStorageKey(baseKey, workspaceSlug),
      JSON.stringify(value),
    );
    return true;
  } catch {
    return false;
  }
}

export function removeWorkspaceLocalValue(
  storage: WorkspaceLocalStorage,
  baseKey: string,
  workspaceSlug: string | null,
): void {
  if (workspaceSlug) {
    removeQuietly(storage, workspaceLocalStorageKey(baseKey, workspaceSlug));
  }
  // Clearing also retires the pre-workspace slot; otherwise it could be
  // resurrected by a later migration.
  removeQuietly(storage, baseKey);
}

function parseScopedValue<T>(
  storage: WorkspaceLocalStorage,
  scopedKey: string,
  raw: string,
  workspaceSlug: string,
  isValue: (value: unknown) => value is T,
  valueWorkspaceSlug?: (value: T) => string | null,
): T | null {
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!isValue(parsed)) {
      removeQuietly(storage, scopedKey);
      return null;
    }
    const embeddedSlug = valueWorkspaceSlug?.(parsed) || null;
    if (embeddedSlug && embeddedSlug !== workspaceSlug) {
      removeQuietly(storage, scopedKey);
      return null;
    }
    return parsed;
  } catch {
    removeQuietly(storage, scopedKey);
    return null;
  }
}

function soleKnownWorkspaceSlug(slugs: readonly string[]): string | null {
  const unique = new Set(slugs.filter((slug) => slug.length > 0));
  return unique.size === 1 ? [...unique][0] : null;
}

function getQuietly(storage: WorkspaceLocalStorage, key: string): string | null {
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}

function removeQuietly(storage: WorkspaceLocalStorage, key: string): void {
  try {
    storage.removeItem(key);
  } catch {
    // Storage can be disabled by the browser. There is no safe fallback slot.
  }
}
