/**
 * "In production": where this version goes wrong on labelled production
 * samples, and for whom (M5), as pure functions.
 *
 * The report is aggregated by the server — error-tree rules and node counts,
 * per-group metrics, counts of samples used and excluded — and its error tree
 * and fairness sections have the shape of the training-time explanation pack,
 * so the card draws them with the same component and chart. What is new here
 * is the vocabulary around them: what was excluded and why, whether there were
 * enough labels, and the fairness badge with the gap that set it.
 */
import type { CurvePoint } from './models.vm';
import type { ExplainTree, ExplanationEvidence, FairnessEvidence } from './explanation-evidence.vm';

export type FairnessBadge = 'ok' | 'watch' | 'alert';
export type ReportStatus = 'queued' | 'running' | 'completed' | 'insufficient_data' | 'failed';

export interface FairnessGap {
  column: string;
  groups?: number;
  small_groups?: number;
  metric?: 'equalized_odds_difference' | 'accuracy_gap' | 'mae_gap_ratio' | string;
  gap?: number | null;
  badge?: FairnessBadge | null;
  reason?: string | null;
}

export interface ProductionReport {
  id: string;
  model_id: string;
  version: number;
  trigger: 'manual' | 'scheduled';
  status: ReportStatus;
  window: { from: string | null; until: string | null };
  counts: { labeled: number; used: number; excluded: Record<string, number> };
  metrics: { accuracy?: number | null; mae?: number | null; rmse?: number | null; rows?: number };
  report: {
    error_measure?: string;
    rows?: number;
    error_tree?: ExplainTree;
    fairness?: {
      reason?: string;
      columns?: FairnessEvidence[];
      gaps?: FairnessGap[];
      badge?: FairnessBadge | null;
      positive?: string | null;
      thresholds?: { watch: number; alert: number; min_group_rows: number };
    };
    minimum?: number;
    error?: string;
  };
  fairness_badge: FairnessBadge | null;
  error_code: string | null;
  created_by?: string | null;
  created_at: string | null;
  started_at?: string | null;
  completed_at: string | null;
}

export interface FairnessPoint {
  report_id: string;
  at: string | null;
  badge: FairnessBadge | null;
  gaps: { column: string; metric?: string; gap?: number | null }[];
}

export interface ProductionDebugView {
  supported: boolean;
  latest: ProductionReport | null;
  series: FairnessPoint[];
  fairness_columns: string[];
  limits: {
    min_rows: number;
    max_rows: number;
    interval_minutes: number;
    watch_gap: number;
    alert_gap: number;
    min_group_rows: number;
  };
}

export function isActive(report: ProductionReport | null | undefined): boolean {
  return report?.status === 'queued' || report?.status === 'running';
}

/** The button: a write permission, a supported model, nothing already running. */
export function canRun(
  view: ProductionDebugView | null,
  permissions: Record<string, boolean> | null | undefined,
): boolean {
  return !!view?.supported && !!permissions?.['score'] && !isActive(view.latest);
}

export function statusKey(report: ProductionReport): string {
  return `models.production.status.${report.status}`;
}

/**
 * The completed report as the training pack's evidence shape, so the same
 * component draws the production error tree and group table. Nothing for a
 * report that analysed nothing.
 */
export function productionEvidence(report: ProductionReport | null): ExplanationEvidence | null {
  if (!report || report.status !== 'completed' || report.report.error) return null;
  const columns = report.report.fairness?.columns;
  return {
    rows: report.counts.used,
    ...(report.report.error_tree ? { error_tree: report.report.error_tree } : {}),
    ...(columns?.length ? { fairness: columns } : {}),
  };
}

const EXCLUSIONS = ['inputs_not_retained', 'answer_missing', 'label_invalid', 'beyond_max_rows'];

/** Why labelled samples were left out, largest first, unknown reasons kept. */
export function exclusionRows(report: ProductionReport | null): { reason: string; key: string; count: number }[] {
  const excluded = report?.counts.excluded ?? {};
  return Object.entries(excluded)
    .filter(([, count]) => Number.isFinite(count) && count > 0)
    .map(([reason, count]) => ({
      reason,
      key: `models.production.excluded.${EXCLUSIONS.includes(reason) ? reason : 'other'}`,
      count,
    }))
    .sort((a, b) => b.count - a.count || a.reason.localeCompare(b.reason));
}

/** Neutral unless there is a real signal: amber for watch, red for alert. */
export function badgeTone(badge: FairnessBadge | null | undefined): 'neutral' | 'warn' | 'alert' {
  return badge === 'alert' ? 'alert' : badge === 'watch' ? 'warn' : 'neutral';
}

export function gapMetricKey(metric: string | null | undefined): string {
  const known = ['equalized_odds_difference', 'accuracy_gap', 'mae_gap_ratio'];
  return `models.production.gap.${metric && known.includes(metric) ? metric : 'other'}`;
}

export function fairnessReasonKey(reason: string | null | undefined): string {
  const known = ['no_sensitive_columns', 'not_in_inputs', 'insufficient_groups', 'too_many_groups'];
  return `models.production.fairness.${reason && known.includes(reason) ? reason : 'unavailable'}`;
}

export interface FairnessSeries {
  key: string;
  column: string;
  metric: string | null;
  points: CurvePoint[];
  dates: string[];
}

/**
 * One gap series per sensitive column, in report order. A report without a
 * gap for that column keeps its position and draws no point: no invented zero.
 */
export function fairnessSeries(series: readonly FairnessPoint[] | null | undefined): FairnessSeries[] {
  const rows = [...(series ?? [])];
  const byColumn = new Map<string, FairnessSeries>();
  rows.forEach((row, index) => {
    for (const gap of row.gaps ?? []) {
      if (typeof gap.gap !== 'number' || !Number.isFinite(gap.gap)) continue;
      const entry = byColumn.get(gap.column) ?? {
        key: gap.column,
        column: gap.column,
        metric: gap.metric ?? null,
        points: [],
        dates: rows.map((item) => item.at ?? ''),
      };
      entry.points.push({ x: index + 1, y: gap.gap });
      byColumn.set(gap.column, entry);
    }
  });
  return [...byColumn.values()];
}

/** The y-range of a gap chart: from zero, and always showing the alert line. */
export function gapDomain(points: readonly CurvePoint[], alert: number) {
  const xs = points.map((point) => point.x);
  const top = Math.max(alert * 1.2, ...points.map((point) => point.y));
  return { minX: Math.min(...xs, 1), maxX: Math.max(...xs, 2), minY: 0, maxY: top };
}

/** The window line: "all production", or the bounds the analysis was asked for. */
export function windowText(
  window: ProductionReport['window'] | undefined,
  locale: string,
  words: { all: string; since: string; until: string },
): string {
  const from = dateText(window?.from, locale), until = dateText(window?.until, locale);
  if (!from && !until) return words.all;
  return [from ? `${words.since} ${from}` : '', until ? `${words.until} ${until}` : '']
    .filter(Boolean)
    .join(' · ');
}

export function dateText(value: string | null | undefined, locale: string): string {
  if (!value) return '';
  const parsed = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
  return Number.isNaN(parsed.getTime())
    ? ''
    : parsed.toLocaleString(locale, { dateStyle: 'medium', timeStyle: 'short' });
}
