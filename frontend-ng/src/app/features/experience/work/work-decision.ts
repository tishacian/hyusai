import type { Run } from '@app/core/canonical-api.service';

/** Bind the review to the exact gate shown, not just the reusable Run ID. */
export function workDecisionKey(run: Run): string {
  const h = run.hitl;
  return JSON.stringify([run.id, run.flow_sha256, h?.decision_id, h?.node_id,
    h?.decision_title, h?.prompt, h?.upstream, h?.expires_at]);
}

export function workDecisionAvailable(run: Run, now = Date.now()): boolean {
  const h = run.hitl;
  if (run.status !== 'hitl_pending' || !h?.decision_id || !['proposed', 'pending'].includes(h.decision_status ?? '')) return false;
  if (!h.expires_at) return true;
  const expires = workDecisionDate(h.expires_at).getTime();
  return Number.isFinite(expires) && expires > now;
}

/** Backend legacy timestamps are UTC even when .isoformat() omits the zone. */
export function workDecisionDate(value: string): Date {
  return new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`);
}

/** Only the payload already authorised and returned by the gate is displayed. */
export function workDecisionRows(run: Run): Array<{ label: string; value: string }> {
  const value = run.hitl?.upstream;
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
  return Object.entries(value).map(([label, field]) => ({
    label,
    value: typeof field === 'string' ? field : JSON.stringify(field) ?? '—',
  }));
}
