/**
 * Studio inventory + wizard projections. Angular-free so `studio.spec.ts`
 * can run as a pure unit. Reuses `slugify` from System Home.
 */

import {
  CERTIFIED_TYPES,
  fieldsFromSchema,
  humanizeIdentifier,
  type CertifiedType,
  type ExperienceDocument,
  type ExperienceNode,
} from '../runtime/model';
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

export function isDataLedPattern(pattern: ExperiencePattern): boolean {
  return pattern === 'queue'
    || pattern === 'approval'
    || pattern === 'dashboard'
    || pattern === 'mission_cockpit';
}

export function templateOutputCompatible(pattern: ExperiencePattern, schema: unknown): boolean {
  if (!isDataLedPattern(pattern)) return true;
  if (!schema || typeof schema !== 'object' || Array.isArray(schema)) return false;
  const contract = schema as Record<string, unknown>;
  const type = contract['type'];
  if (pattern === 'queue') return true;
  if (pattern === 'approval') return type === undefined || type === 'object';
  if (type === undefined) return true;
  if (type === 'object') {
    const properties = contract['properties'];
    if (!properties || typeof properties !== 'object' || Array.isArray(properties)) return true;
    for (const key of ['items', 'rows', 'cases', 'requests', 'events', 'results', 'data']) {
      const candidate = (properties as Record<string, unknown>)[key];
      if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) continue;
      const collection = candidate as Record<string, unknown>;
      if (collection['type'] !== 'array') continue;
      const itemSchema = collection['items'];
      if (!itemSchema || typeof itemSchema !== 'object' || Array.isArray(itemSchema)) return true;
      const itemType = (itemSchema as Record<string, unknown>)['type'];
      return itemType === undefined || itemType === 'object';
    }
    return true;
  }
  if (type !== 'array') return false;
  const items = contract['items'];
  if (!items || typeof items !== 'object' || Array.isArray(items)) return true;
  const itemType = (items as Record<string, unknown>)['type'];
  return itemType === undefined || itemType === 'object';
}

export interface SchemaSelectorOption {
  value: string;
  label: string;
}

function schemaRecord(value: unknown): Record<string, unknown> | null {
  return !!value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function selectorTargetCompatible(type: string, schema: Record<string, unknown>): boolean {
  const valueType = schema['type'];
  if (type === 'approval_card') return valueType === undefined || valueType === 'object';
  if (type === 'evidence') return valueType === undefined || valueType === 'object' || valueType === 'array';
  if (type !== 'table') return true;
  if (valueType === undefined) return true;
  if (valueType === 'array') {
    const items = schemaRecord(schema['items']);
    return !items || items['type'] === undefined || items['type'] === 'object';
  }
  if (valueType !== 'object') return false;
  const properties = schemaRecord(schema['properties']);
  if (!properties) return true;
  for (const key of ['items', 'rows', 'cases', 'requests', 'events', 'results', 'data']) {
    const collection = schemaRecord(properties[key]);
    if (collection?.['type'] !== 'array') continue;
    const items = schemaRecord(collection['items']);
    return !items || items['type'] === undefined || items['type'] === 'object';
  }
  return true;
}

/**
 * Safe, finite paths an author can pick instead of writing a selector.
 * Open/polymorphic contracts deliberately expose only the whole result; the
 * exact selector remains available in Advanced for an expert.
 */
export function schemaSelectorOptions(schema: unknown, componentType: string): SchemaSelectorOption[] {
  const root = schemaRecord(schema);
  if (!root) return [];
  const options: SchemaSelectorOption[] = [];
  if (selectorTargetCompatible(componentType, root)) options.push({ value: '', label: '' });
  const visit = (current: Record<string, unknown>, prefix: string, depth: number): void => {
    if (depth > 4) return;
    const properties = schemaRecord(current['properties']);
    if (!properties) return;
    for (const [key, raw] of Object.entries(properties)) {
      const child = schemaRecord(raw);
      if (!child) continue;
      const value = prefix ? `${prefix}.${key}` : key;
      if (selectorTargetCompatible(componentType, child)) {
        options.push({ value, label: humanizeIdentifier(value) });
      }
      if (child['type'] === 'object' || child['type'] === undefined) visit(child, value, depth + 1);
    }
  };
  visit(root, '', 0);
  return options;
}

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
  description?: string | null;
  emblem?: string | null;
  slug: string;
  pattern: string;
  languages?: string[];
  theme?: Record<string, unknown>;
  access_policy?: Record<string, unknown>;
  updated_at?: string | null;
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
  let suffix = `-${n}`;
  let candidate = `${base.slice(0, 120 - suffix.length)}${suffix}`;
  while (taken.includes(candidate)) {
    n += 1;
    suffix = `-${n}`;
    candidate = `${base.slice(0, 120 - suffix.length)}${suffix}`;
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
  let suffix = `.${n}`;
  let candidate = `${base.slice(0, 120 - suffix.length)}${suffix}`;
  while (taken.includes(candidate)) {
    n += 1;
    suffix = `.${n}`;
    candidate = `${base.slice(0, 120 - suffix.length)}${suffix}`;
  }
  return candidate;
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

export interface InventoryAudience {
  kind: 'open' | 'restricted' | 'unknown';
  roles: string[];
  groups: string[];
}

function audienceValues(value: unknown, key: string): string[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
  const raw = (value as Record<string, unknown>)[key];
  return Array.isArray(raw)
    ? raw.filter((item): item is string => typeof item === 'string' && !!item.trim())
    : [];
}

function summarizeAudience(value: unknown): InventoryAudience {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return { kind: 'unknown', roles: [], groups: [] };
  }
  const directRoles = audienceValues(value, 'roles');
  const roles = directRoles.length > 0 ? directRoles : audienceValues(value, 'role_templates');
  const groups = audienceValues(value, 'groups');
  return { kind: roles.length || groups.length ? 'restricted' : 'open', roles, groups };
}

export function inventoryAudience(row: StudioExperience): InventoryAudience {
  const deployments = row.deployments ?? [];
  const deployment = deployments.find((item) => item.channel === 'live')
    ?? deployments.find((item) => item.channel === 'pilot');
  if (deployment) return summarizeAudience(deployment.audience);
  if (row.access_policy && Object.keys(row.access_policy).length > 0) {
    return summarizeAudience(row.access_policy);
  }
  const legacy = row.theme?.['audience'];
  return legacy === undefined
    ? { kind: 'unknown', roles: [], groups: [] }
    : summarizeAudience(legacy);
}

export function liveSlug(row: StudioExperience): string | null {
  return inventoryState(row.deployments) === 'draft' ? null : row.slug;
}

export function viewHref(row: StudioExperience): string | null {
  const slug = liveSlug(row);
  if (!slug) return null;
  // Resolve the immutable deployed Release (and its renderer pin) before any
  // dedicated business-app redirect stored in the Release theme.
  return `/work/${slug}`;
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

export interface GeneratedBinding {
  bindingKey: string;
  ingressId: string;
  inputSchema?: unknown;
}

/**
 * Turns the wizard's selected entry points into an immediately usable page.
 * The first form/action supplied by the template is reused; extra entry
 * points become certified forms (when they take inputs) or action buttons.
 */
export function bindSeedDocument(
  document: ExperienceDocument,
  links: readonly GeneratedBinding[],
): ExperienceDocument {
  const next = JSON.parse(JSON.stringify(document)) as ExperienceDocument;
  const page = next.pages[0];
  if (!page || links.length === 0) return next;

  links.forEach((link, index) => {
    const hasProvidedSchema = !!link.inputSchema && typeof link.inputSchema === 'object';
    const schema = hasProvidedSchema
      ? link.inputSchema
      : { type: 'object', properties: {} };
    const hasInputs = fieldsFromSchema(schema).length > 0;
    const existing = page.components.find(
      (node) =>
        (node.type === 'form' || node.type === 'action_button') &&
        node.props?.['bindingKey'] === link.bindingKey,
    );
    const reusable = existing ?? (index === 0
      ? page.components.find(
          (node) => (node.type === 'form' || node.type === 'action_button') && !node.props?.['bindingKey'],
        )
      : undefined);
    const target: ExperienceNode = reusable ?? {
      type: hasInputs ? 'form' : 'action_button',
      id: `wizard-${index + 1}-${slugify(link.bindingKey).slice(0, 32) || 'action'}`,
      props: {},
    };
    const label = humanizeIdentifier(link.ingressId) || link.bindingKey;
    target.props = {
      ...(target.props ?? {}),
      bindingKey: link.bindingKey,
      ...(target.type === 'form'
        ? {
            ...((hasProvidedSchema || !target.props?.['schema']) ? { schema } : {}),
            submitLabel: label,
          }
        : { label }),
    };
    if (!reusable) {
      const firstData = page.components.findIndex((node) => DATA_COMPONENTS.has(node.type));
      const targetIndex = firstData < 0 ? page.components.length : firstData;
      page.components.splice(targetIndex, 0, target);
      page.components.splice(targetIndex + 1, 0, {
        type: 'result',
        id: `wizard-result-${index + 1}`,
        props: { dataBinding: { source: 'run-output', componentId: target.id, selector: '' } },
      });
    }
  });
  const source = page.components.find(
    (node) => (node.type === 'form' || node.type === 'action_button') && !!node.props?.['bindingKey'],
  );
  if (source?.id) {
    for (const node of page.components) {
      if (!DATA_COMPONENTS.has(node.type)) continue;
      node.props = {
        ...(node.props ?? {}),
        dataBinding: { source: 'run-output', componentId: source.id, selector: '' },
      };
    }
  }
  return next;
}

const DATA_COMPONENTS = new Set(['kpi', 'table', 'queue', 'approval_card', 'history']);

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

function legacyThemeAudience(theme: Record<string, unknown> | undefined): string[] {
  const raw = theme?.['audience'];
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return [];
  const roles = (raw as Record<string, unknown>)['roles'];
  if (!Array.isArray(roles)) return [];
  return roles.filter((item): item is string => typeof item === 'string' && !!item.trim());
}

export function experienceAudience(row: Pick<StudioExperience, 'access_policy' | 'theme'> | null | undefined): string[] {
  const raw = experienceAccessPolicy(row)['roles'];
  if (Array.isArray(raw)) {
    return raw.filter((item): item is string => typeof item === 'string' && !!item.trim());
  }
  return [];
}

export function experienceAccessPolicy(
  row: Pick<StudioExperience, 'access_policy' | 'theme'> | null | undefined,
): Record<string, unknown> {
  const policy = row?.access_policy;
  if (policy && Object.keys(policy).length > 0) return policy;
  const legacyRoles = legacyThemeAudience(row?.theme);
  return legacyRoles.length > 0 ? { roles: legacyRoles } : {};
}

/** Local-only Studio access simulation. It never changes the signed-in principal. */
export function simulatedExperienceAccess(
  policy: Record<string, unknown>,
  role: string,
  group = '',
): boolean {
  const rawRoles = policy['roles'];
  const rawGroups = policy['groups'];
  const rolesDeclared = Array.isArray(rawRoles);
  const groupsDeclared = Array.isArray(rawGroups);
  if (!rolesDeclared && !groupsDeclared) return false;
  const roles = rolesDeclared
    ? rawRoles.filter((item): item is string => typeof item === 'string' && !!item.trim())
    : [];
  const groups = groupsDeclared
    ? rawGroups.filter((item): item is string => typeof item === 'string' && !!item.trim())
    : [];
  if (roles.length === 0 && groups.length === 0) return true;
  return (!!role && roles.includes(role)) || (!!group && groups.includes(group));
}
