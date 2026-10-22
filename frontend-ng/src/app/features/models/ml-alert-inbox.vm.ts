import type { MLAlert } from './endpoints.vm';

export interface MLAlertInboxSummary {
  loaded: number;
  total: number;
  partial: boolean;
  unread: number;
  severe: number;
  items: MLAlert[];
}

/** This is a window of historical events, not a current model-health verdict.
 * The API total includes acknowledged events and must never become an unread
 * count. Unknown future event kinds remain visible rather than being dropped.
 */
export function summarizeMLAlerts(items: readonly MLAlert[], total: number): MLAlertInboxSummary {
  const recorded = Math.max(items.length, Number.isSafeInteger(total) && total >= 0 ? total : items.length);
  const unread = items.filter(item => !item.acknowledged_at);
  const rank = (item: MLAlert): number => item.state === 'alert' || item.state === 'failed' ? 0
    : item.state === 'watch' || item.state === 'expiring' ? 1 : 2;
  const visible = [...unread].sort((left, right) => rank(left) - rank(right)
    || (Date.parse(right.created_at) || 0) - (Date.parse(left.created_at) || 0));
  return {
    loaded: items.length,
    total: recorded,
    partial: recorded > items.length,
    unread: unread.length,
    severe: unread.filter(item => rank(item) === 0).length,
    items: visible.slice(0, 5),
  };
}

export function mlAlertEventKey(event: string): string | null {
  return ({
    monitor_transition: 'models.endpoints.transition',
    monitor_failed: 'models.endpoints.monitor_failed',
    key_expiring: 'models.endpoints.key_expiring',
    fairness_gap: 'models.endpoints.fairness_gap',
    quota_reached: 'models.endpoints.quota',
  } as Record<string, string>)[event] ?? null;
}

export function mlAlertStateKey(state: string): string | null {
  return ({
    ok: 'models.alert_inbox.state.recovered',
    watch: 'models.endpoints.watch',
    alert: 'models.endpoints.alert',
    failed: 'models.alert_inbox.state.failed',
    expiring: 'models.alert_inbox.state.expiring',
  } as Record<string, string>)[state] ?? null;
}
