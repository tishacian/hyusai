/**
 * Pure view logic for Intelligence: the watch list (Suivre › Intelligence)
 * and News Lab. Intelligence is a neutral product isolated per workspace:
 * the server decides which Systems are watches (`GET /intelligence/watch`)
 * and which knowledge collection the workspace writes to; this file only
 * shapes what it returns.
 */

export type Translate = (key: string, params?: Record<string, string | number>) => string;

export interface WatchSystem {
  id: string;
  name: string;
  status?: string | null;
  objective?: string | null;
  template_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface WatchListResponse {
  systems: WatchSystem[];
  can_create: boolean;
  template_id?: string;
}

export interface CreateWatchResponse {
  system: WatchSystem;
  created: boolean;
}

export type IntelligenceRow = {
  id: string;
  name: string;
  status: string;
  measure: string;
  updatedAt: string | null;
  systemId: string;
};

/** One row per watch the server listed — never a fallback list of other Systems. */
export function watchRows(response: WatchListResponse | null | undefined, absentMeasure: string): IntelligenceRow[] {
  return (response?.systems ?? []).map((system) => ({
    id: system.id,
    systemId: system.id,
    name: system.name || system.id,
    status: (system.status || 'draft').toLowerCase(),
    measure: system.objective?.trim() || absentMeasure,
    updatedAt: system.updated_at ?? system.created_at ?? null,
  }));
}

export type SetupStepKey = 'feed' | 'target';
export interface SetupStep {
  key: SetupStepKey;
  done: boolean;
}

/** What is still missing before the watch can run: a feed and a target. */
export function setupSteps(feedCount: number, targetCount: number): SetupStep[] {
  return [
    { key: 'feed', done: feedCount > 0 },
    { key: 'target', done: targetCount > 0 },
  ];
}

export function needsSetup(feedCount: number, targetCount: number): boolean {
  return setupSteps(feedCount, targetCount).some((step) => !step.done);
}

export interface KnowledgeCollectionRef {
  slug: string;
  name: string;
}

/** The workspace's own collection as the dashboard names it; never a hard-coded slug. */
export function knowledgeCollection(dashboard: {
  knowledge_collection?: Partial<KnowledgeCollectionRef> | null;
  synthesis?: { knowledge_reference?: { recommended_collection?: string } } | null;
} | null | undefined): KnowledgeCollectionRef | null {
  const declared = dashboard?.knowledge_collection;
  const slug = declared?.slug || dashboard?.synthesis?.knowledge_reference?.recommended_collection || '';
  if (!slug) return null;
  return { slug, name: declared?.name || slug };
}

export interface BatchEvent {
  type: string;
  code?: string;
  batch_id?: string;
  run_id?: string;
  system_id?: string;
  progress?: number;
  message?: string;
  source?: string;
  stored?: number;
  total_articles?: number;
  analyzed?: number;
  status?: string;
  collection_slug?: string;
}

const BATCH_ERROR_CODES = new Set(['no_feed', 'no_target', 'workspace_required']);

/** A refusal the server explains with a code reads in the user's language. */
export function batchErrorMessage(evt: BatchEvent, t: Translate): string {
  if (evt.code && BATCH_ERROR_CODES.has(evt.code)) return t(`intelligence.newsLab.error.${evt.code}`);
  return evt.message || t('intelligence.newsLab.error.unknown');
}

export function progressLabel(evt: BatchEvent, t: Translate): string {
  const shortId = (value?: string) => (value ?? '').slice(0, 8);
  switch (evt.type) {
    case 'batch_start':
      return t('intelligence.newsLab.progress.started', { id: evt.batch_id ?? '' });
    case 'batch_fetch':
      return t('intelligence.newsLab.progress.fetching', { source: evt.source ?? '' });
    case 'batch_analyze':
      return t('intelligence.newsLab.progress.analyzing');
    case 'run_started':
      return t('intelligence.newsLab.progress.recording', { id: shortId(evt.run_id) });
    case 'batch_store':
      return t('intelligence.newsLab.progress.storing');
    case 'batch_complete':
      return t('intelligence.newsLab.progress.done', {
        fetched: evt.total_articles ?? 0,
        analyzed: evt.analyzed ?? 0,
      });
    case 'batch_done':
      return t('intelligence.newsLab.progress.done', { fetched: evt.stored ?? 0, analyzed: evt.analyzed ?? 0 });
    case 'knowledge_sync_started':
      return t('intelligence.newsLab.progress.syncing', { collection: evt.collection_slug ?? '' });
    case 'run_completed':
      return t('intelligence.newsLab.progress.run_done', {
        id: shortId(evt.run_id),
        status: evt.status ?? 'completed',
      });
    case 'batch_error':
      return t('intelligence.newsLab.progress.error', { message: batchErrorMessage(evt, t) });
    default:
      return evt.message ?? evt.type ?? '';
  }
}

/** `3600` → `1h`, `900` → `15m`; `—` when the server gave no interval. */
export function schedulerInterval(seconds: number | null | undefined): string {
  const s = seconds ?? 0;
  if (!s) return '—';
  if (s % 3600 === 0) return `${s / 3600}h`;
  if (s % 60 === 0) return `${s / 60}m`;
  return `${s}s`;
}
