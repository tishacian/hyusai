/**
 * Certified Experience document + the two pure projections the renderer
 * needs: JSON Schema → form fields, and a Run → business follow-up.
 *
 * Keep this file free of Angular so `runtime.spec.ts` can run as a pure unit.
 *
 * `CERTIFIED_RENDERER_VERSION` is the SPA catalog pin. A release that names a
 * different `renderer_version` must not render — show the repair state instead.
 */

export const CERTIFIED_RENDERER_VERSION = 'certified-components-0.1.0';

export const CERTIFIED_TYPES = [
  'section',
  'header',
  'form',
  'action_button',
  'result',
  'table',
  'queue',
  'approval_card',
  'runtime_status',
  'evidence',
  'history',
  'kpi',
  'callout',
  'map_panel',
  'agenda_panel',
  'intelligence_feed',
  'decision_queue',
] as const;

export type CertifiedType = (typeof CERTIFIED_TYPES)[number];

export interface ExperienceNode {
  type: string;
  id?: string;
  props?: Record<string, unknown>;
}

export interface ExperiencePage {
  id: string;
  title: string;
  props?: Record<string, unknown>;
  components: ExperienceNode[];
}

export interface ExperienceDocument {
  pages: ExperiencePage[];
}

export type CatalogResolution =
  | { kind: 'skip' }
  | { kind: 'ok'; type: CertifiedType }
  | { kind: 'fallback'; type: string };

export function rendererPinMatches(
  releaseVersion: string | null | undefined,
  catalogVersion = CERTIFIED_RENDERER_VERSION,
): boolean {
  if (!releaseVersion) return true;
  return releaseVersion === catalogVersion;
}

export function resolveCatalogType(type: string): CatalogResolution {
  if (type === 'page') return { kind: 'skip' };
  if ((CERTIFIED_TYPES as readonly string[]).includes(type)) {
    return { kind: 'ok', type: type as CertifiedType };
  }
  return { kind: 'fallback', type };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

/**
 * A `form` renders its own submit, so an `action_button` on the same binding is
 * a second submit that sends a different payload. Releases are immutable, so
 * the duplicate is dropped at render time rather than by rewriting documents.
 */
export function renderableComponents(
  components: readonly ExperienceNode[],
): ExperienceNode[] {
  const bindingOf = (node: ExperienceNode) => String(node.props?.['bindingKey'] ?? '');
  const submitting = new Set(
    components.filter((node) => node.type === 'form').map(bindingOf),
  );
  return components.filter(
    (node) => node.type !== 'action_button' || !submitting.has(bindingOf(node)),
  );
}

export function parseDocument(raw: unknown): ExperienceDocument {
  if (!isRecord(raw) || !Array.isArray(raw['pages'])) return { pages: [] };
  const pages: ExperiencePage[] = [];
  for (const item of raw['pages']) {
    if (!isRecord(item)) continue;
    const id = typeof item['id'] === 'string' && item['id'] ? item['id'] : `page-${pages.length}`;
    const title = typeof item['title'] === 'string' ? item['title'] : id;
    const components: ExperienceNode[] = [];
    if (Array.isArray(item['components'])) {
      for (const node of item['components']) {
        if (!isRecord(node) || typeof node['type'] !== 'string') continue;
        components.push({
          type: node['type'],
          id: typeof node['id'] === 'string' ? node['id'] : undefined,
          props: isRecord(node['props']) ? node['props'] : undefined,
        });
      }
    }
    pages.push({
      id,
      title,
      props: isRecord(item['props']) ? item['props'] : undefined,
      components,
    });
  }
  return { pages };
}

// ---------------------------------------------------------------------------
// Schema → fields
// ---------------------------------------------------------------------------

export type RuntimeFieldKind =
  | 'string'
  | 'number'
  | 'integer'
  | 'boolean'
  | 'enum'
  | 'date'
  | 'file';

export interface RuntimeField {
  name: string;
  kind: RuntimeFieldKind;
  required: boolean;
  label: string;
  description: string;
  options: readonly string[];
}

export function fieldsFromSchema(schema: unknown): RuntimeField[] {
  if (!isRecord(schema)) return [];
  const properties = isRecord(schema['properties']) ? schema['properties'] : {};
  const required = new Set(
    (Array.isArray(schema['required']) ? schema['required'] : [])
      .filter((key): key is string => typeof key === 'string'),
  );
  const fields: RuntimeField[] = [];
  for (const [name, raw] of Object.entries(properties)) {
    const spec = isRecord(raw) ? raw : {};
    const options = Array.isArray(spec['enum'])
      ? spec['enum'].map((item) => String(item))
      : [];
    fields.push({
      name,
      kind: fieldKind(spec, options.length > 0),
      required: required.has(name),
      label: typeof spec['title'] === 'string' && spec['title'] ? spec['title'] : name,
      description: typeof spec['description'] === 'string' ? spec['description'] : '',
      options,
    });
  }
  return fields;
}

function fieldKind(spec: Record<string, unknown>, hasEnum: boolean): RuntimeFieldKind {
  if (hasEnum) return 'enum';
  const format = typeof spec['format'] === 'string' ? spec['format'] : '';
  if (format === 'date' || format === 'date-time') return 'date';
  if (
    format === 'binary'
    || format === 'data-url'
    || spec['contentMediaType']
    || spec['x-file'] === true
  ) {
    return 'file';
  }
  const type = typeof spec['type'] === 'string' ? spec['type'] : 'string';
  if (type === 'number' || type === 'integer' || type === 'boolean') return type;
  return 'string';
}

export function seedFromSchema(schema: unknown): Record<string, unknown> {
  if (!isRecord(schema)) return {};
  const properties = isRecord(schema['properties']) ? schema['properties'] : {};
  const seeded: Record<string, unknown> = {};
  for (const [name, raw] of Object.entries(properties)) {
    const spec = isRecord(raw) ? raw : {};
    if ('default' in spec) seeded[name] = spec['default'];
  }
  return seeded;
}

export function validateValues(
  fields: readonly RuntimeField[],
  values: Record<string, unknown>,
): Record<string, 'required' | 'invalid'> {
  const errors: Record<string, 'required' | 'invalid'> = {};
  for (const field of fields) {
    const value = values[field.name];
    const empty =
      value === undefined
      || value === null
      || (typeof value === 'string' && value.trim() === '');
    if (field.required && empty && field.kind !== 'boolean') {
      errors[field.name] = 'required';
      continue;
    }
    if (empty) continue;
    if (field.kind === 'number' || field.kind === 'integer') {
      const n = typeof value === 'number' ? value : Number(value);
      if (!Number.isFinite(n) || (field.kind === 'integer' && !Number.isInteger(n))) {
        errors[field.name] = 'invalid';
      }
    } else if (field.kind === 'enum' && !field.options.includes(String(value))) {
      errors[field.name] = 'invalid';
    } else if (field.kind === 'date' && Number.isNaN(Date.parse(String(value)))) {
      errors[field.name] = 'invalid';
    }
  }
  return errors;
}

export function valuesToPayload(
  fields: readonly RuntimeField[],
  values: Record<string, unknown>,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  for (const field of fields) {
    const value = values[field.name];
    if (value === undefined || value === null) continue;
    if (typeof value === 'string' && value.trim() === '' && field.kind !== 'string') continue;
    if (field.kind === 'number' || field.kind === 'integer') {
      const n = typeof value === 'number' ? value : Number(value);
      if (Number.isFinite(n)) payload[field.name] = field.kind === 'integer' ? Math.trunc(n) : n;
      continue;
    }
    if (field.kind === 'boolean') {
      payload[field.name] = value === true || value === 'true';
      continue;
    }
    payload[field.name] = value;
  }
  return payload;
}

// ---------------------------------------------------------------------------
// Run follow-up
// ---------------------------------------------------------------------------

export type BusinessRunStatus =
  | 'running'
  | 'pending_validation'
  | 'completed'
  | 'retry'
  | 'error';

export function mapRunStatus(status: string | null | undefined): BusinessRunStatus | null {
  switch (status) {
    case 'pending':
    case 'running':
    case 'debug_pending':
      return 'running';
    case 'hitl_pending':
      return 'pending_validation';
    case 'completed':
      return 'completed';
    case 'cancelled':
      return 'retry';
    case 'failed':
      return 'error';
    default:
      return null;
  }
}

export function runIsSettled(status: string | null | undefined): boolean {
  return (
    status === 'completed'
    || status === 'failed'
    || status === 'cancelled'
    || status === 'hitl_pending'
  );
}

export interface RuntimeCitation {
  title: string;
  source?: string;
  snippet?: string;
}

export function extractCitations(run: { output_ref?: Record<string, unknown> | null } | null): RuntimeCitation[] {
  if (!run?.output_ref) return [];
  const raw = run.output_ref['citations'] ?? run.output_ref['evidence'];
  if (!Array.isArray(raw)) return [];
  const out: RuntimeCitation[] = [];
  for (const item of raw) {
    if (typeof item === 'string' && item.trim()) {
      out.push({ title: item });
      continue;
    }
    if (!isRecord(item)) continue;
    const title =
      (typeof item['title'] === 'string' && item['title'])
      || (typeof item['source'] === 'string' && item['source'])
      || (typeof item['uri'] === 'string' && item['uri'])
      || '';
    if (!title) continue;
    out.push({
      title,
      source: typeof item['source'] === 'string' ? item['source'] : undefined,
      snippet: typeof item['snippet'] === 'string' ? item['snippet'] : undefined,
    });
  }
  return out;
}

export function extractResult(run: { output_ref?: Record<string, unknown> | null } | null): unknown {
  return run?.output_ref ?? null;
}

export type UnavailablePolicy = 'empty' | 'unavailable' | 'admin-repair';

export function unavailablePolicy(value: unknown): UnavailablePolicy {
  if (value === 'empty' || value === 'admin-repair') return value;
  return 'unavailable';
}
