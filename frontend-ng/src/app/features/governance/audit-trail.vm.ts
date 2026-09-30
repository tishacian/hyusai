export interface AuditLog {
  id: string | number;
  timestamp: string;
  event_type: string;
  actor?: string;
  severity?: string;
  details?: string | Record<string, unknown>;
  trace_id?: string | null;
  run_id?: string | null;
  agent_id?: string | null;
}

export interface AuditPage {
  logs: AuditLog[];
  total: number;
  has_more?: boolean;
  next_cursor?: string | null;
}

export interface AuditFilters {
  navigation: boolean;
  actor: string;
  eventType: string;
  since: string;
  until: string;
  trace: string;
  severity: string;
  search: string;
}

export function auditParams(filters: AuditFilters, before?: string | null, limit = 50): Record<string, string> {
  const params: Record<string, string> = { limit: String(limit), exclude_navigation: String(!filters.navigation) };
  for (const [key, value] of Object.entries({
    actor: filters.actor.trim(), event_type: filters.eventType.trim(), trace_id: filters.trace.trim(),
    severity: filters.severity, search: filters.search.trim(), before,
  })) if (value) params[key] = value;
  // Native datetime-local fields are in the reader's timezone; the API takes UTC.
  if (filters.since) params['since'] = new Date(filters.since).toISOString();
  if (filters.until) params['until'] = new Date(filters.until).toISOString();
  return params;
}

export function appendAuditPage(previous: AuditLog[], page: AuditPage): AuditLog[] {
  const ids = new Set(previous.map(row => row.id));
  return [...previous, ...page.logs.filter(row => !ids.has(row.id))];
}

const EVENT_KEYS: Record<string, string> = {
  'knowledge.collection.access_changed': 'access',
  'run.completed': 'run_completed', 'run.failed': 'run_failed', 'run.started': 'run_started',
  'run.hitl.approved': 'approved', 'run.hitl.rejected': 'rejected',
  'decision.accepted': 'approved', 'decision.rejected': 'rejected',
  'experience.released': 'published', 'experience.deployed': 'deployed',
};

export function auditEventKey(type: string): string {
  if (EVENT_KEYS[type]) return 'governance.audit.event.' + EVENT_KEYS[type];
  const family = type.startsWith('adoption.') ? 'adoption'
    : type.startsWith('knowledge.') ? 'knowledge'
    : type.startsWith('decision.') || type.includes('hitl') ? 'decision'
    : type.startsWith('chat_feedback') ? 'feedback'
    : type.startsWith('navigation.') ? 'navigation'
    : /^(experience|workspace_app|app)\./.test(type) ? (/deploy/.test(type) ? 'deployed' : /release|publish/.test(type) ? 'published' : 'app')
    : /^(run|runtime)\./.test(type) ? 'run'
    : /^(system|system360)\./.test(type) ? 'system'
    : 'other';
  return 'governance.audit.event.' + family;
}

export function auditCsv(rows: AuditLog[]): string {
  const escape = (value: unknown) => {
    let text = value == null ? '' : String(value);
    // Spreadsheet formula injection applies to actor names and free-form details too.
    if (/^[=+@\-\t\r]/.test(text)) text = "'" + text;
    return `"${text.replace(/"/g, '""')}"`;
  };
  return [['Timestamp', 'Event', 'Actor', 'Trace', 'Run', 'Severity', 'Details'], ...rows.map(row => [
    row.timestamp, row.event_type, row.actor, row.trace_id, row.run_id, row.severity || 'info',
    typeof row.details === 'string' ? row.details : JSON.stringify(row.details ?? {}),
  ])].map(row => row.map(escape).join(',')).join('\r\n');
}
