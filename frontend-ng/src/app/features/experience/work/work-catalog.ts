/**
 * Pure /work projections: which apps a viewer may open, and how the
 * launcher behaves. Angular-free so `work-catalog.spec.ts` can run as a unit.
 *
 * `/work` is already filtered by the server. This module deliberately contains
 * no audience evaluator: Studio may display access, but only the API decides
 * whether this principal receives Pilot or Live.
 */

export type WorkChannel = 'live' | 'pilot';

export interface WorkDeployment {
  channel: string;
  audience?: Record<string, unknown> | null;
  release_id?: string;
}

export interface WorkExperience {
  id: string;
  name: string;
  slug: string;
  pattern: string;
  languages?: string[];
  theme?: Record<string, unknown> | null;
  created_by?: string | null;
  deployments?: WorkDeployment[];
}

export interface WorkCatalogItem {
  experience: WorkExperience;
  channel: WorkChannel | string;
  release: {
    id: string;
    release_number?: number;
    languages?: string[];
    theme?: Record<string, unknown>;
    renderer_version?: string | null;
  };
}

export interface WorkResolve {
  experience: WorkExperience;
  channel: WorkChannel | string;
  release: {
    id: string;
    pages: unknown;
    bindings_snapshot: Array<Record<string, unknown>>;
    languages?: string[];
    theme?: Record<string, unknown>;
    renderer_version?: string | null;
  };
}

export type LauncherDecision =
  | { kind: 'empty' }
  | { kind: 'redirect'; slug: string; href: string }
  | { kind: 'list'; apps: WorkExperience[] };

export function liveHref(theme: Record<string, unknown> | null | undefined): string | null {
  const href = theme?.['live_href'];
  if (typeof href !== 'string') return null;
  const trimmed = href.trim();
  if (!trimmed.startsWith('/') || trimmed.startsWith('//') || trimmed.includes('\\')) return null;
  return trimmed;
}

export function launchHref(app: WorkExperience): string {
  return liveHref(app.theme) ?? `/work/${app.slug}`;
}

export function catalogLaunchHref(item: WorkCatalogItem): string {
  return liveHref(item.release.theme) ?? launchHref(item.experience);
}

export function workPageHref(slug: string, pageId?: string | null): string {
  const root = `/work/${encodeURIComponent(slug)}`;
  return pageId ? `${root}/${encodeURIComponent(pageId)}` : root;
}

export function workTheme(theme: Record<string, unknown> | null | undefined): {
  mode: 'light' | 'dark';
  accent: string;
} {
  const mode = theme?.['mode'] === 'dark' ? 'dark' : 'light';
  const accent = typeof theme?.['accent'] === 'string' && /^#[0-9a-f]{6}$/i.test(theme['accent'])
    ? theme['accent']
    : '';
  return { mode, accent };
}

export function launcherDecision(apps: readonly WorkExperience[]): LauncherDecision {
  if (apps.length === 0) return { kind: 'empty' };
  if (apps.length === 1) {
    const only = apps[0]!;
    return { kind: 'redirect', slug: only.slug, href: launchHref(only) };
  }
  return { kind: 'list', apps: [...apps] };
}

export function studioHref(experienceId: string | null | undefined): string {
  return experienceId ? `/create/apps/${experienceId}` : '/create/apps';
}

export function canEditExperience(roleTemplate?: string | null, isAdmin = false): boolean {
  if (isAdmin) return true;
  return (
    roleTemplate === 'workspace_contributor'
    || roleTemplate === 'workspace_admin'
    || roleTemplate === 'workspace_owner'
  );
}

export function documentNeedsValidations(
  pages: readonly { components?: readonly { type: string }[] }[],
  pattern?: string,
): boolean {
  if (pattern === 'queue' || pattern === 'approval') return true;
  return pages.some((page) =>
    (page.components ?? []).some(
      (node) =>
        node.type === 'approval_card' || node.type === 'queue' || node.type === 'decision_queue',
    ),
  );
}

export function bindingSystemIds(snapshot: readonly Record<string, unknown>[]): string[] {
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const item of snapshot) {
    const id = item['system_id'];
    if (typeof id === 'string' && id && !seen.has(id)) {
      seen.add(id);
      ids.push(id);
    }
  }
  return ids;
}

export function bindingKeys(snapshot: readonly Record<string, unknown>[]): string[] {
  const keys: string[] = [];
  const seen = new Set<string>();
  for (const item of snapshot) {
    const key = item['binding_key'];
    if (typeof key === 'string' && key && !seen.has(key)) {
      seen.add(key);
      keys.push(key);
    }
  }
  return keys;
}

export function pendingValidationOrigins(
  _snapshot: readonly Record<string, unknown>[],
  experienceSlug: string,
): string[] {
  const slug = experienceSlug.trim();
  return slug ? [`experience:${slug}`] : [];
}

export function workLocales(languages: readonly string[] | undefined): Array<'fr' | 'en'> {
  const out: Array<'fr' | 'en'> = [];
  for (const raw of languages ?? []) {
    const code = raw.toLowerCase().slice(0, 2);
    if ((code === 'fr' || code === 'en') && !out.includes(code)) out.push(code);
  }
  return out;
}
