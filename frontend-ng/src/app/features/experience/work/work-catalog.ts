/**
 * Pure /work projections: which apps a viewer may open, and how the
 * launcher behaves. Angular-free so `work-catalog.spec.ts` can run as a unit.
 *
 * `/work` is already filtered by the server. This module deliberately contains
 * no audience evaluator: Studio may display access, but only the API decides
 * whether this principal receives Pilot or Live.
 */

import { onAccentColor } from '../runtime/style';
import { CERTIFIED_RENDERER_VERSION as CURRENT_RENDERER_VERSION } from '../runtime/model';
import { CERTIFIED_RENDERER_VERSION as LEGACY_RENDERER_VERSION } from '../runtime/v0_1/model';
import { isCataloguedReturnTo } from './work-return';

export type WorkChannel = 'live' | 'pilot';

export interface WorkDeployment {
  channel: string;
  audience?: Record<string, unknown> | null;
  release_id?: string;
}

export interface WorkExperience {
  id: string;
  name: string;
  description?: string | null;
  emblem?: string | null;
  slug: string;
  pattern: string;
  languages?: string[];
  theme?: Record<string, unknown> | null;
  created_by?: string | null;
  deployments?: WorkDeployment[];
}

/** L17 — optional; missing field keeps the launcher title fixed. */
export interface PendingDecisions {
  count: number;
  oldest_at?: string | null;
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
    identity_snapshot?: Record<string, unknown>;
  };
  /** Additive L14: Systems targeted by this release's bindings. */
  binding_system_ids?: string[];
  /** Additive L17: decisions this reader may treat for this app. */
  pending_decisions?: PendingDecisions | null;
}

export interface WorkResolve {
  experience: WorkExperience;
  channel: WorkChannel | string;
  release: {
    id: string;
    release_number?: number;
    pages: unknown;
    bindings_snapshot: Array<Record<string, unknown>>;
    languages?: string[];
    theme?: Record<string, unknown>;
    renderer_version?: string | null;
    identity_snapshot?: Record<string, unknown>;
  };
}

export type LauncherDecision =
  | { kind: 'empty' }
  | { kind: 'redirect'; slug: string; href: string }
  | { kind: 'list'; apps: WorkExperience[] };

export interface WorkIdentity {
  name: string;
  description: string;
  emblem: string;
}

/** Prefer the immutable release identity; fall back only for legacy releases. */
export function workIdentity(
  experience: WorkExperience,
  release?: { identity_snapshot?: Record<string, unknown> } | null,
): WorkIdentity {
  const snapshot = release?.identity_snapshot;
  const value = (key: 'name' | 'description' | 'emblem', fallback: unknown): string => {
    const raw = snapshot && Object.prototype.hasOwnProperty.call(snapshot, key) ? snapshot[key] : fallback;
    return typeof raw === 'string' ? raw.trim() : '';
  };
  return {
    name: value('name', experience.name) || experience.name,
    description: value('description', experience.description),
    emblem: value('emblem', experience.emblem),
  };
}

export function workEmblem(identity: WorkIdentity): string {
  if (identity.emblem && !/^[a-z][a-z0-9_-]{0,31}$/i.test(identity.emblem)) return identity.emblem;
  const source = identity.emblem || identity.name;
  // Split on any non-alphanumeric (Unicode letters/digits) so "NAWA — IT" → "NI".
  return source
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('') || 'A';
}

export function liveHref(theme: Record<string, unknown> | null | undefined): string | null {
  const href = theme?.['live_href'];
  if (typeof href !== 'string') return null;
  const trimmed = href.trim();
  if (!trimmed.startsWith('/') || trimmed.startsWith('//') || trimmed.includes('\\')) return null;
  return trimmed;
}

/** Dedicated Nawa shell opened from Work (L18) — leaves Work for a new tab. */
export function isNawaLiveHref(href: string): boolean {
  return href === '/nawa' || href.startsWith('/nawa/');
}

export function isNawaLiveLaunch(item: WorkCatalogItem): boolean {
  return isNawaLiveHref(catalogLaunchHref(item));
}

export function launchHref(app: WorkExperience): string {
  return liveHref(app.theme) ?? `/work/${app.slug}`;
}

export function catalogLaunchHref(item: WorkCatalogItem): string {
  if (
    item.release.renderer_version !== CURRENT_RENDERER_VERSION
    && item.release.renderer_version !== LEGACY_RENDERER_VERSION
  ) {
    return `/work/${item.experience.slug}`;
  }
  return liveHref(item.release.theme) ?? launchHref(item.experience);
}

export function workPageHref(slug: string, pageId?: string | null): string {
  const root = `/work/${encodeURIComponent(slug)}`;
  return pageId ? `${root}/${encodeURIComponent(pageId)}` : root;
}

export function isInternalWorkHref(href: string, slug: string): boolean {
  const root = `/work/${encodeURIComponent(slug)}`;
  return href === root || href.startsWith(`${root}/`);
}

export function workTheme(theme: Record<string, unknown> | null | undefined): {
  mode: 'light' | 'dark';
  accent: string;
  onAccent: string;
} {
  const mode = theme?.['mode'] === 'dark' ? 'dark' : 'light';
  const accent = typeof theme?.['accent'] === 'string' && /^#[0-9a-f]{6}$/i.test(theme['accent'])
    ? theme['accent']
    : '';
  return { mode, accent, onAccent: accent ? onAccentColor(accent) : '' };
}

export function launcherDecision(apps: readonly WorkExperience[]): LauncherDecision {
  if (apps.length === 0) return { kind: 'empty' };
  if (apps.length === 1) {
    const only = apps[0]!;
    return { kind: 'redirect', slug: only.slug, href: launchHref(only) };
  }
  return { kind: 'list', apps: [...apps] };
}

export function studioHref(
  experienceId: string | null | undefined,
  pageId?: string | null,
  returnTo?: string | null,
  releaseId?: string | null,
  releaseNumber?: number | null,
): string {
  if (!experienceId) return '/create/apps';
  const root = `/create/apps/${encodeURIComponent(experienceId)}`;
  const params = new URLSearchParams();
  const page = pageId?.trim() ?? '';
  if (/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(page)) params.set('pageId', page);
  const back = returnTo?.trim() ?? '';
  if (/^\/work(?:\/|$)/.test(back) && !back.includes('\\')) params.set('returnTo', back);
  const release = releaseId?.trim() ?? '';
  if (/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(release)) params.set('releaseId', release);
  if (Number.isSafeInteger(releaseNumber) && (releaseNumber ?? 0) > 0) {
    params.set('releaseNumber', String(releaseNumber));
  }
  const query = params.toString();
  return query ? `${root}?${query}` : root;
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

/** Focus selector restored on Cockpit return from Work (L14 / L3). */
export const OPEN_IN_WORK_FOCUS = '#open-in-work';

/** Public row for System → Work links (GET /work/systems/:id/apps). */
export interface SystemLinkedWorkApp {
  id: string;
  name: string;
  emblem: string;
  type: string;
  kind: 'experience' | 'automation' | string;
  channel: string;
  status: string;
  href: string;
  last_opened_at?: string | null;
}

export function withWorkReturnTo(href: string, returnTo: string | null | undefined): string {
  const back = returnTo?.trim() ?? '';
  if (!isCataloguedReturnTo(back)) return href;
  const sep = href.includes('?') ? '&' : '?';
  return `${href}${sep}returnTo=${encodeURIComponent(back)}`;
}

const STATUS_RANK: Record<string, number> = { live: 0, pilot: 1 };

export function sortSystemLinkedWorkApps(
  apps: readonly SystemLinkedWorkApp[],
): SystemLinkedWorkApp[] {
  return [...apps].sort((a, b) => {
    const aOpened = a.last_opened_at?.trim() || '';
    const bOpened = b.last_opened_at?.trim() || '';
    if (aOpened || bOpened) {
      if (aOpened && bOpened && aOpened !== bOpened) return aOpened < bOpened ? 1 : -1;
      if (aOpened !== bOpened) return aOpened ? -1 : 1;
    }
    const status = (STATUS_RANK[a.status] ?? 9) - (STATUS_RANK[b.status] ?? 9);
    if (status !== 0) return status;
    return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
  });
}

export function workLocales(languages: readonly string[] | undefined): Array<'fr' | 'en'> {
  const out: Array<'fr' | 'en'> = [];
  for (const raw of languages ?? []) {
    const code = raw.toLowerCase().slice(0, 2);
    if ((code === 'fr' || code === 'en') && !out.includes(code)) out.push(code);
  }
  return out;
}
