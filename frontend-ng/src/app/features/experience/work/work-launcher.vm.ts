/**
 * Pure L17 launcher projections: title from pending decisions, sections by
 * intention, and the channel summary line. Angular-free for unit specs.
 */

import {
  catalogLaunchHref,
  workIdentity,
  workPageHref,
  type PendingDecisions,
  type WorkCatalogItem,
} from './work-catalog';

export type LauncherSectionId = 'ask' | 'follow' | 'automate';

export type LauncherTitleModel =
  | { kind: 'fixed' }
  | { kind: 'one_app'; count: number; appName: string; href: string }
  | { kind: 'many_apps'; count: number; appCount: number; href: string };

export interface LauncherDecisionSource {
  name: string;
  href: string;
  pending: PendingDecisions | null | undefined;
}

export interface LauncherSummary {
  total: number;
  live: number;
  pilot: number;
}

export interface LauncherSection<T> {
  id: LauncherSectionId;
  items: T[];
}

export interface LauncherAutomationRef {
  job: { system_id: string; name?: string | null };
  pending_decisions?: PendingDecisions | null;
}

const FOLLOW_PATTERNS = new Set([
  'queue',
  'approval',
  'dashboard',
  'mission_cockpit',
]);

export function launcherSectionForPattern(pattern: string): Exclude<LauncherSectionId, 'automate'> {
  return FOLLOW_PATTERNS.has(pattern) ? 'follow' : 'ask';
}

export function pendingCount(pending: PendingDecisions | null | undefined): number {
  if (!pending || typeof pending.count !== 'number' || !Number.isFinite(pending.count)) {
    return 0;
  }
  return Math.max(0, Math.floor(pending.count));
}

export function decisionSources(
  items: readonly WorkCatalogItem[],
  jobs: readonly LauncherAutomationRef[] = [],
): LauncherDecisionSource[] {
  const apps = items.map((item) => ({
    name: workIdentity(item.experience, item.release).name,
    href: workPageHref(item.experience.slug, 'validations'),
    pending: item.pending_decisions,
  }));
  const automations = jobs.map((job) => ({
    name: (job.job.name || '').trim() || job.job.system_id,
    href: `/work/automation/${encodeURIComponent(job.job.system_id)}`,
    pending: job.pending_decisions,
  }));
  return [...apps, ...automations];
}

/** Title carries the wait when decisions exist; otherwise stays fixed. */
export function launcherTitleModel(
  sources: readonly LauncherDecisionSource[],
): LauncherTitleModel {
  const withDecisions = sources
    .map((source) => ({
      ...source,
      count: pendingCount(source.pending),
      oldestAt: source.pending?.oldest_at?.trim() || '',
    }))
    .filter((source) => source.count > 0);
  if (withDecisions.length === 0) return { kind: 'fixed' };

  const total = withDecisions.reduce((sum, source) => sum + source.count, 0);
  let oldest = withDecisions[0]!;
  for (const source of withDecisions.slice(1)) {
    if (!oldest.oldestAt && source.oldestAt) {
      oldest = source;
      continue;
    }
    if (source.oldestAt && (!oldest.oldestAt || source.oldestAt < oldest.oldestAt)) {
      oldest = source;
    }
  }
  if (withDecisions.length === 1) {
    return {
      kind: 'one_app',
      count: total,
      appName: oldest.name,
      href: oldest.href,
    };
  }
  return {
    kind: 'many_apps',
    count: total,
    appCount: withDecisions.length,
    href: oldest.href,
  };
}

export function launcherSummary(items: readonly WorkCatalogItem[]): LauncherSummary {
  let live = 0;
  let pilot = 0;
  for (const item of items) {
    if (item.channel === 'live') live += 1;
    else pilot += 1;
  }
  return { total: items.length, live, pilot };
}

export function groupLauncherApps(
  items: readonly WorkCatalogItem[],
): Array<LauncherSection<WorkCatalogItem>> {
  const ask: WorkCatalogItem[] = [];
  const follow: WorkCatalogItem[] = [];
  for (const item of items) {
    if (launcherSectionForPattern(item.experience.pattern) === 'follow') follow.push(item);
    else ask.push(item);
  }
  const sections: Array<LauncherSection<WorkCatalogItem>> = [];
  if (ask.length) sections.push({ id: 'ask', items: ask });
  if (follow.length) sections.push({ id: 'follow', items: follow });
  return sections;
}

export function catalogItemLaunchHref(item: WorkCatalogItem): string {
  return catalogLaunchHref(item);
}
