import type { Run, SkillInvocation } from '@app/core/canonical-api.service';
import { recordedTimeline } from '../observability/observability-chart.vm';

export interface TraceStepSummary {
  totalMs: number;
  longestMs: number;
  longestLabel: string;
  longestInvocationId: string | null;
}

export function invocationDurationMs(inv: SkillInvocation): number {
  if (typeof inv.latency_ms === 'number' && Number.isFinite(inv.latency_ms) && inv.latency_ms >= 0) {
    return inv.latency_ms;
  }
  const start = Date.parse(inv.started_at || '');
  const end = Date.parse(inv.completed_at || inv.ended_at || '');
  if (Number.isFinite(start) && Number.isFinite(end) && end >= start) return end - start;
  return 0;
}

export function traceStepSummary(run: Pick<Run, 'duration_ms' | 'skill_invocations'>): TraceStepSummary {
  const invocations = run.skill_invocations || [];
  let longestMs = 0;
  let longestLabel = '';
  let longestInvocationId: string | null = null;
  for (const inv of invocations) {
    const ms = invocationDurationMs(inv);
    if (ms > longestMs) {
      longestMs = ms;
      longestLabel = inv.skill_slug || inv.skill_id || inv.id || '';
      longestInvocationId = inv.id || null;
    }
  }
  const timeline = recordedTimeline(invocations);
  const totalMs =
    typeof run.duration_ms === 'number' && Number.isFinite(run.duration_ms) && run.duration_ms >= 0
      ? run.duration_ms
      : timeline.duration;
  return { totalMs, longestMs, longestLabel, longestInvocationId };
}

export function invocationTokens(inv: SkillInvocation): number | null {
  const metrics = inv.metrics;
  if (!metrics || typeof metrics !== 'object') return null;
  for (const key of ['tokens', 'total_tokens', 'token_count']) {
    const value = metrics[key];
    if (typeof value === 'number' && Number.isFinite(value) && value >= 0) return value;
  }
  const usage = metrics['usage'];
  if (usage && typeof usage === 'object') {
    const total = (usage as Record<string, unknown>)['total_tokens'];
    if (typeof total === 'number' && Number.isFinite(total) && total >= 0) return total;
  }
  return null;
}

export function invocationRetries(inv: SkillInvocation): number {
  const metrics = inv.metrics;
  if (metrics && typeof metrics === 'object') {
    const value = metrics['retries'];
    if (typeof value === 'number' && Number.isFinite(value) && value >= 0) return value;
  }
  return 0;
}

/** Index of the longest timed row in a recorded timeline, or -1. */
export function longestTimelineRowIndex(
  rows: Array<{ duration: number }>,
): number {
  let best = -1;
  let bestMs = -1;
  rows.forEach((row, index) => {
    if (row.duration > bestMs) {
      bestMs = row.duration;
      best = index;
    }
  });
  return best;
}
