export type ExperienceGovernanceChannel = 'all' | 'draft' | 'pilot' | 'live';

export interface ExperienceGovernanceDeployment {
  channel: string;
  release_id?: string;
  audience?: Record<string, unknown> | null;
}

export interface ExperienceGovernanceRow {
  id: string;
  name: string;
  slug: string;
  latest_release_number?: number | null;
  binding_keys?: string[];
  deployments?: ExperienceGovernanceDeployment[];
}

export interface ExperienceAuditRow {
  id: string;
  timestamp?: string | null;
  event_type: string;
  actor?: string | null;
  agent_id?: string | null;
  severity?: string | null;
  details?: Record<string, unknown> | null;
}

export interface ExperienceAuditFilter {
  eventType: string;
  experienceId: string;
  query: string;
}

export interface AudienceProjection {
  kind: 'open' | 'restricted';
  roles: string[];
  groups: string[];
}

const GOVERNANCE_ROLES = new Set([
  'workspace_reviewer',
  'workspace_admin',
  'workspace_owner',
]);

export function canGovernExperiences(
  roleTemplate?: string | null,
  role?: string | null,
  isAdmin = false,
): boolean {
  return isAdmin
    || role === 'owner'
    || role === 'admin'
    || GOVERNANCE_ROLES.has(roleTemplate ?? '');
}

export function experienceGovernanceChannel(
  row: ExperienceGovernanceRow,
): Exclude<ExperienceGovernanceChannel, 'all'> {
  const channels = new Set((row.deployments ?? []).map((item) => item.channel));
  if (channels.has('live')) return 'live';
  if (channels.has('pilot')) return 'pilot';
  return 'draft';
}

export function filterExperienceInventory(
  rows: readonly ExperienceGovernanceRow[],
  query: string,
  channel: ExperienceGovernanceChannel,
): ExperienceGovernanceRow[] {
  const needle = query.trim().toLocaleLowerCase();
  return rows.filter((row) => {
    if (channel !== 'all' && experienceGovernanceChannel(row) !== channel) return false;
    return !needle || `${row.name} ${row.slug}`.toLocaleLowerCase().includes(needle);
  });
}

function values(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string' && !!item.trim())
    : [];
}

export function projectAudience(value: unknown): AudienceProjection {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return { kind: 'open', roles: [], groups: [] };
  }
  const record = value as Record<string, unknown>;
  const roles = values(record['roles']).length > 0
    ? values(record['roles'])
    : values(record['role_templates']);
  const groups = values(record['groups']);
  return {
    kind: roles.length > 0 || groups.length > 0 ? 'restricted' : 'open',
    roles,
    groups,
  };
}

function auditMatchesExperience(
  log: ExperienceAuditRow,
  app: ExperienceGovernanceRow,
): boolean {
  const details = log.details ?? {};
  if (details['experience_id'] === app.id || log.agent_id === app.id) return true;
  const bindingKey = details['binding_key'];
  return typeof bindingKey === 'string' && (app.binding_keys ?? []).includes(bindingKey);
}

export function filterExperienceAudit(
  logs: readonly ExperienceAuditRow[],
  applications: readonly ExperienceGovernanceRow[],
  filter: ExperienceAuditFilter,
): ExperienceAuditRow[] {
  const selected = filter.experienceId
    ? applications.find((row) => row.id === filter.experienceId)
    : null;
  const needle = filter.query.trim().toLocaleLowerCase();
  return logs.filter((log) => {
    if (filter.eventType && log.event_type !== filter.eventType) return false;
    if (filter.experienceId && (!selected || !auditMatchesExperience(log, selected))) return false;
    if (!needle) return true;
    return `${log.event_type} ${log.actor ?? ''} ${JSON.stringify(log.details ?? {})}`
      .toLocaleLowerCase()
      .includes(needle);
  });
}

export function driftCountFor(
  row: ExperienceGovernanceRow,
  bindingKeys: readonly string[],
): number {
  const drifted = new Set(bindingKeys);
  return (row.binding_keys ?? []).filter((key) => drifted.has(key)).length;
}
