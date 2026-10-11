/**
 * L33 — the Work home « À faire », as pure projections of `GET /work/_home`.
 *
 * Every count and line comes from the payload; a field the server left out
 * (or `null`) drops the element that would show it, never a guessed value.
 * Angular-free so the unit spec pins it without a TestBed.
 */

import type { Run } from '@app/core/canonical-api.service';
import { formatReceiptAmount, formatReceiptDuration, readSystemLabel, workReceipt } from './pr-to-po-receipt';
import { FACTORY_EXPERIENCE_SLUG } from './pr-to-po-runtime';
import { proposalFromRun, studioNodesFromRun } from './pr-to-po-studio';
import { workPageHref } from './work-catalog';

export interface HomeSource {
  kind: 'app' | 'automation' | string;
  slug?: string;
  system_id?: string;
  name: string;
}

export interface HomeReceipt {
  steps?: number | null;
  agent_ms?: number | null;
  write?: 'sealed' | 'done' | string | null;
  passages_read?: number | null;
  passages_cited?: number | null;
}

export interface HomeDecision {
  run_id: string;
  decision_id?: string | null;
  title?: string | null;
  started_at?: string | null;
  source?: HomeSource | null;
}

export interface HomeReview {
  decision_id: string;
  run_id?: string | null;
  title?: string | null;
  created_at?: string | null;
  source?: HomeSource | null;
}

export interface HomeWork {
  run_id: string;
  completed_at?: string | null;
  source?: HomeSource | null;
  receipt?: HomeReceipt | null;
}

export interface WorkHome {
  window_days?: number;
  decisions?: { count?: number; oldest_at?: string | null; items?: HomeDecision[] } | null;
  /** `null` when the reader may not review: the tile is hidden, not zero. */
  reviews?: { count?: number; oldest_at?: string | null; items?: HomeReview[] } | null;
  results?: { items?: HomeWork[] } | null;
  agent_work?: { items?: HomeWork[] } | null;
}

/** A key and its params, translated by the component. */
export interface Phrase {
  key: string;
  params?: Record<string, string | number>;
}

/** Known auto-evaluation notices; custom titles stay as authored. */
export function homeReviewPhrase(title: string | null, locale: string): Phrase | null {
  if (title === 'Run flagged for review') return { key: 'experience.work.home.review.flagged' };
  const hallucination = /^Run has high hallucination rate \((\d+(?:\.\d+)?)%\)$/.exec(title ?? '');
  const quality = /^Run below composite threshold \((\d+(?:\.\d+)?)\/100\)$/.exec(title ?? '');
  const match = hallucination ?? quality;
  if (!match) return null;
  const value = Number(match[1]);
  if (!Number.isFinite(value) || value < 0 || value > 100) return null;
  const formatted = new Intl.NumberFormat(locale, { maximumFractionDigits: 20 }).format(value);
  return hallucination
    ? { key: 'experience.work.home.review.hallucination', params: { rate: formatted } }
    : { key: 'experience.work.home.review.quality', params: { score: formatted } };
}

export type QueueKind = 'decision' | 'review' | 'result';

export type QueueTarget =
  | { kind: 'work'; url: string }
  | { kind: 'review'; decisionId: string };

export interface QueueItem {
  kind: QueueKind;
  /** Stable track id. */
  id: string;
  runId: string | null;
  title: string | null;
  source: HomeSource | null;
  at: string | null;
  receipt: HomeReceipt | null;
  target: QueueTarget | null;
}

const count = (value: unknown): number =>
  typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;

const text = (value: unknown): string => (value == null ? '' : String(value).trim());

/** Server stamps are naive UTC ISO; a string without an offset is read as UTC. */
export function parseUtc(value: string | null | undefined): number | null {
  const raw = text(value);
  if (!raw) return null;
  const zoned = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw) ? raw : `${raw}Z`;
  const ms = Date.parse(zoned);
  return Number.isFinite(ms) ? ms : null;
}

export function sourceHref(source: HomeSource | null | undefined, page?: 'validations'): string | null {
  if (!source) return null;
  if (source.kind === 'automation' && text(source.system_id)) {
    return `/work/automation/${encodeURIComponent(text(source.system_id))}`;
  }
  if (source.kind === 'app' && text(source.slug)) return workPageHref(text(source.slug), page ?? null);
  return null;
}

function byAge(a: string | null, b: string | null, direction: 1 | -1): number {
  const left = parseUtc(a);
  const right = parseUtc(b);
  if (left == null && right == null) return 0;
  if (left == null) return 1;
  if (right == null) return -1;
  return (left - right) * direction;
}

/**
 * The prioritised list: decisions, oldest first; then reviews, oldest first;
 * then new results, newest first. Each links where it is treated.
 */
export function homeQueue(home: WorkHome | null | undefined): QueueItem[] {
  if (!home) return [];
  const decisions = [...(home.decisions?.items ?? [])]
    .sort((a, b) => byAge(a.started_at ?? null, b.started_at ?? null, 1))
    .map((item): QueueItem => {
      const url = sourceHref(item.source, 'validations');
      return {
        kind: 'decision',
        id: `decision:${item.run_id}`,
        runId: item.run_id,
        title: text(item.title) || null,
        source: item.source ?? null,
        at: item.started_at ?? null,
        receipt: null,
        target: url ? { kind: 'work', url } : null,
      };
    });
  const reviews = [...(home.reviews?.items ?? [])]
    .sort((a, b) => byAge(a.created_at ?? null, b.created_at ?? null, 1))
    .map((item): QueueItem => ({
      kind: 'review',
      id: `review:${item.decision_id}`,
      runId: item.run_id ?? null,
      title: text(item.title) || null,
      source: item.source ?? null,
      at: item.created_at ?? null,
      receipt: null,
      target: { kind: 'review', decisionId: item.decision_id },
    }));
  const results = [...(home.results?.items ?? [])]
    .sort((a, b) => byAge(a.completed_at ?? null, b.completed_at ?? null, -1))
    .map((item): QueueItem => {
      const url = sourceHref(item.source);
      return {
        kind: 'result',
        id: `result:${item.run_id}`,
        runId: item.run_id,
        title: null,
        source: item.source ?? null,
        at: item.completed_at ?? null,
        receipt: item.receipt ?? null,
        target: url ? { kind: 'work', url } : null,
      };
    });
  return [...decisions, ...reviews, ...results];
}

/** Everything waiting, including what the server listed beyond the page. */
export function homeWaitingTotal(home: WorkHome | null | undefined): number {
  if (!home) return 0;
  const decisions = Math.max(count(home.decisions?.count), home.decisions?.items?.length ?? 0);
  const reviews = home.reviews ? Math.max(count(home.reviews.count), home.reviews.items?.length ?? 0) : 0;
  return decisions + reviews + (home.results?.items?.length ?? 0);
}

/** H1: « {n} choses vous attendent », « Une chose vous attend », or the fixed title. */
export function homeTitle(total: number): Phrase | null {
  if (total > 1) return { key: 'experience.work.home.title.many', params: { n: total } };
  if (total === 1) return { key: 'experience.work.home.title.one' };
  return null;
}

/** « 2 h », « 3 jours » — the age of a stamp; unknown stamps have no age. */
export function agePhrase(iso: string | null | undefined, now: number): Phrase | null {
  const at = parseUtc(iso);
  if (at == null) return null;
  const minutes = Math.max(0, Math.floor((now - at) / 60_000));
  if (minutes < 1) return { key: 'experience.work.home.age.now' };
  if (minutes < 60) return { key: 'experience.work.home.age.minutes', params: { n: minutes } };
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return { key: 'experience.work.home.age.hours', params: { n: hours } };
  const days = Math.floor(hours / 24);
  return { key: 'experience.work.home.age.days', params: { n: days } };
}

export type TileId = 'decisions' | 'reviews' | 'apps';

export interface HomeTile {
  id: TileId;
  count: number;
  label: Phrase;
  /** The one factual line under the label; `null` omits it. */
  note: Phrase | null;
  /** `oldest` note carries an age phrase to translate first. */
  noteAge: Phrase | null;
  emphasis: boolean;
  target: QueueTarget | 'apps' | null;
}

export interface CatalogueSplit {
  total: number;
  live: number;
  pilot: number;
}

const plural = (base: string, n: number): string => `${base}.${n === 1 ? 'one' : 'many'}`;
/** Tile labels also carry a zero form: French says « 0 décision attendue ». */
const tileLabel = (base: string, n: number): string => (n === 0 ? `${base}.zero` : plural(base, n));

/**
 * The three tiles. Decisions and reviews need the home payload; reviews need
 * a reader the review queue admits; apps need the catalogue. Only the first
 * actionable tile is filled.
 */
export function homeTiles(
  home: WorkHome | null | undefined,
  apps: CatalogueSplit | null,
  queue: readonly QueueItem[],
  now: number,
): HomeTile[] {
  const tiles: HomeTile[] = [];
  if (home) {
    const n = Math.max(count(home.decisions?.count), home.decisions?.items?.length ?? 0);
    const age = n > 0 ? agePhrase(home.decisions?.oldest_at, now) : null;
    const first = queue.find((item) => item.kind === 'decision');
    tiles.push({
      id: 'decisions',
      count: n,
      label: { key: tileLabel('experience.work.home.tile.decisions', n) },
      note: n === 0 ? { key: 'experience.work.home.tile.decisions.none' } : age ? { key: 'experience.work.home.tile.oldest' } : null,
      noteAge: age,
      emphasis: false,
      target: n > 0 ? first?.target ?? null : null,
    });
  }
  if (home?.reviews) {
    const n = Math.max(count(home.reviews.count), home.reviews.items?.length ?? 0);
    const age = n > 0 ? agePhrase(home.reviews.oldest_at, now) : null;
    const first = queue.find((item) => item.kind === 'review');
    tiles.push({
      id: 'reviews',
      count: n,
      label: { key: tileLabel('experience.work.home.tile.reviews', n) },
      note: n === 0 ? { key: 'experience.work.home.tile.reviews.none' } : age ? { key: 'experience.work.home.tile.oldest' } : null,
      noteAge: age,
      emphasis: false,
      target: n > 0 ? first?.target ?? null : null,
    });
  }
  if (apps) {
    tiles.push({
      id: 'apps',
      count: apps.total,
      label: { key: tileLabel('experience.work.home.tile.apps', apps.total) },
      note: apps.total > 0
        ? { key: 'experience.work.home.tile.apps.split', params: { live: apps.live, pilot: apps.pilot } }
        : null,
      noteAge: null,
      emphasis: false,
      target: apps.total > 0 ? 'apps' : null,
    });
  }
  const lead = tiles.find((tile) => tile.id !== 'apps' && tile.count > 0 && tile.target);
  if (lead) lead.emphasis = true;
  return tiles;
}

/** « 8 étapes · 18 s · écriture scellée · 3 passages lus · 2 cités » — measured parts only. */
export function receiptPhrases(receipt: HomeReceipt | null | undefined, locale: string): Phrase[] {
  if (!receipt) return [];
  const out: Phrase[] = [];
  const steps = receipt.steps;
  if (typeof steps === 'number' && steps > 0) {
    out.push({ key: plural('experience.work.home.receipt.steps', steps), params: { n: steps } });
  }
  const ms = receipt.agent_ms;
  if (typeof ms === 'number' && ms > 0) {
    out.push({ key: 'experience.work.home.receipt.duration', params: { value: formatReceiptDuration(ms, locale) } });
  }
  if (receipt.write === 'sealed') out.push({ key: 'experience.work.home.receipt.write.sealed' });
  else if (receipt.write === 'done') out.push({ key: 'experience.work.home.receipt.write.done' });
  const read = receipt.passages_read;
  if (typeof read === 'number' && read > 0) {
    out.push({ key: plural('experience.work.home.receipt.read', read), params: { n: read } });
  }
  const cited = receipt.passages_cited;
  if (typeof cited === 'number' && cited > 0) {
    out.push({ key: plural('experience.work.home.receipt.cited', cited), params: { n: cited } });
  }
  return out;
}

/** The decisions the page enriches with the L32 receipt (one Run read each). */
export function isPrToPoDecision(item: QueueItem): boolean {
  return item.kind === 'decision' && item.source?.kind === 'app' && item.source.slug === FACTORY_EXPERIENCE_SLUG;
}

/**
 * « 42 800,00 EUR · contrôle budgétaire OK · 3 lectures SAP » for a PR to PO
 * decision, from the same Run projections as the Studio receipt (L32).
 */
export function prToPoMeta(run: Run | null | undefined, locale: string): Phrase[] {
  if (!run) return [];
  const out: Phrase[] = [];
  const proposal = proposalFromRun(run);
  if (proposal && !proposal.priceMissing && proposal.amount > 0) {
    out.push({
      key: 'experience.work.home.meta.amount',
      params: { value: formatReceiptAmount(proposal.amount, proposal.currency, locale) },
    });
  }
  const receipt = workReceipt(run, studioNodesFromRun(run));
  if (receipt.budget) {
    out.push({ key: receipt.budget.ok ? 'experience.work.home.meta.budget_ok' : 'experience.work.home.meta.budget_ko' });
  }
  for (const read of receipt.reads) {
    out.push({
      key: plural('experience.work.home.meta.reads', read.count),
      params: { n: read.count, source: readSystemLabel(read.server) },
    });
  }
  return out;
}

/** First 8 characters of an identifier, as the rail and the list print it. */
export function shortId(id: string | null | undefined): string {
  return text(id).slice(0, 8);
}
