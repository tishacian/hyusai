/**
 * Studio inventory + wizard projections. Angular-free so `studio.spec.ts`
 * can run as a pure unit. Reuses `slugify` from System Home.
 */

import { CERTIFIED_TYPES, type CertifiedType, type ExperienceDocument } from '../runtime/model';
import { slugify } from '../runtime/system-home';
import { liveHref, type WorkDeployment } from '../work/work-catalog';

export { slugify };

export const EXPERIENCE_PATTERNS = [
  'assistant',
  'form_result',
  'queue',
  'approval',
  'dashboard',
  'mission_cockpit',
] as const;

export type ExperiencePattern = (typeof EXPERIENCE_PATTERNS)[number];

export const INVENTORY_FILTERS = ['all', 'live', 'pilot', 'drafts'] as const;
export type InventoryFilter = (typeof INVENTORY_FILTERS)[number];

export type InventoryState = 'draft' | 'pilot' | 'live';

export const ACCESS_ROLES = [
  'workspace_viewer',
  'workspace_contributor',
  'workspace_reviewer',
  'workspace_admin',
] as const;

export const CONFIRMATION_POLICIES = ['direct-safe', 'confirm', 'hitl'] as const;
export const UNAVAILABLE_POLICIES = ['empty', 'unavailable', 'admin-repair'] as const;

export const ADDABLE_TYPES: readonly CertifiedType[] = CERTIFIED_TYPES;

export interface StudioExperience {
  id: string;
  name: string;
  slug: string;
  pattern: string;
  languages?: string[];
  theme?: Record<string, unknown>;
  binding_keys?: string[];
  draft_revision?: number;
  latest_release_number?: number | null;
  deployments?: WorkDeployment[];
  draft?: {
    pages?: unknown;
    binding_keys?: string[];
    revision?: number;
  };
}

export function experienceSlug(name: string): string {
  const base = slugify(name);
  if (!base) return 'app';
  const headed = /^[a-z]/.test(base) ? base : `app-${base}`;
  return headed.slice(0, 120);
}

export function uniqueExperienceSlug(name: string, taken: readonly string[]): string {
  const base = experienceSlug(name);
  if (!taken.includes(base)) return base;
  let n = 2;
  let candidate = `${base}-${n}`.slice(0, 120);
  while (taken.includes(candidate)) {
    n += 1;
    candidate = `${base}-${n}`.slice(0, 120);
  }
  return candidate;
}

export function bindingKeyFrom(name: string, ingressId: string): string {
  const head = slugify(name).replace(/-/g, '.') || 'app';
  const ingress = slugify(ingressId).replace(/-/g, '.') || 'submit';
  const key = `${head}.${ingress}`;
  return /^[a-z]/.test(key) ? key.slice(0, 120) : `app.${key}`.slice(0, 120);
}

export function uniqueBindingKey(
  name: string,
  systemId: string,
  ingressId: string,
  taken: readonly string[],
): string {
  const base = bindingKeyFrom(name, `${systemId}-${ingressId}`);
  if (!taken.includes(base)) return base;
  let n = 2;
  while (taken.includes(`${base}.${n}`)) n += 1;
  return `${base}.${n}`;
}

export function inventoryState(deployments: WorkDeployment[] | undefined): InventoryState {
  const list = deployments ?? [];
  if (list.some((item) => item.channel === 'live')) return 'live';
  if (list.some((item) => item.channel === 'pilot')) return 'pilot';
  return 'draft';
}

export function filterInventory(
  rows: readonly StudioExperience[],
  filter: InventoryFilter,
): StudioExperience[] {
  if (filter === 'all') return [...rows];
  return rows.filter((row) => {
    const state = inventoryState(row.deployments);
    if (filter === 'drafts') return state === 'draft';
    return state === filter;
  });
}

export function audienceLabel(deployments: WorkDeployment[] | undefined): string[] {
  const list = deployments ?? [];
  const live = list.find((item) => item.channel === 'live');
  const pilot = list.find((item) => item.channel === 'pilot');
  const audience = (live ?? pilot)?.audience;
  if (!audience || typeof audience !== 'object' || Array.isArray(audience)) return [];
  const raw = (audience as Record<string, unknown>)['roles']
    ?? (audience as Record<string, unknown>)['role_templates'];
  if (!Array.isArray(raw)) return [];
  return raw.filter((item): item is string => typeof item === 'string' && !!item.trim());
}

export function liveSlug(row: StudioExperience): string | null {
  return inventoryState(row.deployments) === 'draft' ? null : row.slug;
}

export function viewHref(row: StudioExperience): string | null {
  const slug = liveSlug(row);
  if (!slug) return null;
  return liveHref(row.theme) ?? `/work/${slug}`;
}

export function inventoryOrigin(row: StudioExperience): 'existing' | 'studio' {
  return liveHref(row.theme) ? 'existing' : 'studio';
}

/**
 * Names of the other applications that use a binding. A binding is a
 * workspace object, so its confirmation and unavailability rules are shared:
 * the author has to see who else is affected before changing them.
 */
export function bindingSharedWith(
  rows: readonly StudioExperience[],
  key: string,
  selfId: string | null,
): string[] {
  if (!key) return [];
  return rows
    .filter((row) => row.id !== selfId && (row.binding_keys ?? []).includes(key))
    .map((row) => row.name);
}

export interface SeedLabels {
  subtitle: string;
  empty: string;
  approvalBody: string;
}

export function seedDocument(
  pattern: ExperiencePattern,
  name: string,
  labels: SeedLabels,
): ExperienceDocument {
  const title = name.trim() || pattern;
  const header = {
    type: 'header',
    id: 'seed-head',
    props: { title, subtitle: labels.subtitle },
  };
  const form = {
    type: 'form',
    id: 'seed-form',
    props: { schema: { type: 'object', properties: {} } },
  };
  const empty = {
    type: 'callout',
    id: 'seed-empty',
    props: { body: labels.empty, empty_state: true },
  };
  switch (pattern) {
    case 'assistant':
      return page(title, [header, form, { type: 'result', id: 'seed-result' }, { type: 'history', id: 'seed-history' }]);
    case 'queue':
      return page(title, [
        header,
        { type: 'kpi', id: 'seed-kpi', props: { label: title, value: 0 } },
        { type: 'queue', id: 'seed-queue', props: { items: [] } },
        empty,
      ]);
    case 'approval':
      return page(title, [
        header,
        {
          type: 'approval_card',
          id: 'seed-approval',
          props: { title, body: labels.approvalBody },
        },
        { type: 'queue', id: 'seed-queue', props: { items: [] } },
        empty,
      ]);
    case 'dashboard':
      return page(title, [
        header,
        { type: 'kpi', id: 'seed-kpi', props: { label: title, value: 0 } },
        { type: 'table', id: 'seed-table', props: { caption: title, columns: [], rows: [] } },
        { type: 'callout', id: 'seed-note', props: { body: labels.subtitle } },
      ]);
    case 'mission_cockpit':
      return page(title, [
        header,
        { type: 'kpi', id: 'seed-kpi', props: { label: title, value: 0 } },
        { type: 'table', id: 'seed-table', props: { caption: title, columns: [], rows: [] } },
        { type: 'history', id: 'seed-history' },
      ]);
    case 'form_result':
    default:
      return page(title, [
        header,
        form,
        { type: 'runtime_status', id: 'seed-status' },
        { type: 'result', id: 'seed-result' },
        { type: 'evidence', id: 'seed-evidence' },
      ]);
  }
}

function page(title: string, components: ExperienceDocument['pages'][number]['components']): ExperienceDocument {
  return { pages: [{ id: 'home', title, components }] };
}

export function themeAudience(theme: Record<string, unknown> | undefined): string[] {
  const raw = theme?.['audience'];
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return [];
  const roles = (raw as Record<string, unknown>)['roles'];
  if (!Array.isArray(roles)) return [];
  return roles.filter((item): item is string => typeof item === 'string' && !!item.trim());
}

export function withAudience(
  theme: Record<string, unknown> | undefined,
  roles: readonly string[],
): Record<string, unknown> {
  return { ...(theme ?? {}), audience: { roles: [...roles] } };
}
