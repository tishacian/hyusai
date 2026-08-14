/**
 * Pure /work projections: which apps a viewer may open, and how the
 * launcher behaves. Angular-free so `work-catalog.spec.ts` can run as a unit.
 *
 * Audience assumption (list API does not filter):
 * - `live` is visible to anyone with experience.view
 * - `pilot` is visible when `audience.roles` / `audience.role_templates`
 *   includes the viewer's role, or when that list is missing/empty
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

export function audienceAllows(audience: unknown, roles: readonly string[]): boolean {
  if (!audience || typeof audience !== 'object' || Array.isArray(audience)) return true;
  const rec = audience as Record<string, unknown>;
  const raw = rec['roles'] ?? rec['role_templates'];
  if (!Array.isArray(raw) || raw.length === 0) return true;
  const allowed = raw.filter((item): item is string => typeof item === 'string' && !!item.trim());
  if (allowed.length === 0) return true;
  return roles.some((role) => allowed.includes(role));
}

export function preferredChannel(
  deployments: WorkDeployment[] | undefined,
  roles: readonly string[],
): WorkChannel | null {
  const list = deployments ?? [];
  if (list.some((item) => item.channel === 'live')) return 'live';
  const pilot = list.find((item) => item.channel === 'pilot');
  if (pilot && audienceAllows(pilot.audience, roles)) return 'pilot';
  return null;
}

export function launchableApps(
  experiences: readonly WorkExperience[],
  roles: readonly string[],
): WorkExperience[] {
  return experiences.filter((item) => preferredChannel(item.deployments, roles) !== null);
}

export function hasDeployment(experience: WorkExperience): boolean {
  return (experience.deployments ?? []).some(
    (item) => item.channel === 'live' || item.channel === 'pilot',
  );
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

export function launcherDecision(apps: readonly WorkExperience[]): LauncherDecision {
  if (apps.length === 0) return { kind: 'empty' };
  if (apps.length === 1) {
    const only = apps[0]!;
    return { kind: 'redirect', slug: only.slug, href: launchHref(only) };
  }
  return { kind: 'list', apps: [...apps] };
}

export function viewerRoles(roleTemplate?: string | null, role?: string | null): string[] {
  return [roleTemplate, role].filter((item): item is string => !!item);
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

export function pendingValidationOrigins(snapshot: readonly Record<string, unknown>[]): string[] {
  return bindingKeys(snapshot).map((key) => `experience:${key}`);
}

export function workLocales(languages: readonly string[] | undefined): Array<'fr' | 'en'> {
  const out: Array<'fr' | 'en'> = [];
  for (const raw of languages ?? []) {
    const code = raw.toLowerCase().slice(0, 2);
    if ((code === 'fr' || code === 'en') && !out.includes(code)) out.push(code);
  }
  return out;
}
