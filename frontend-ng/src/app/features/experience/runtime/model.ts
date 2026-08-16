/**
 * Certified Experience document + the two pure projections the renderer
 * needs: JSON Schema → form fields, and a Run → business follow-up.
 *
 * Keep this file free of Angular so `runtime.spec.ts` can run as a pure unit.
 *
 * `CERTIFIED_RENDERER_VERSION` is the SPA catalog pin. A release that names a
 * different `renderer_version` must not render — show the repair state instead.
 */

export const CERTIFIED_RENDERER_VERSION = 'certified-components-0.2.0';

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
  title: string | LocalizedText;
  props?: Record<string, unknown>;
  components: ExperienceNode[];
}

export interface ExperienceDocument {
  pages: ExperiencePage[];
  i18n?: Record<string, Record<string, string>>;
}

export interface LocalizedText {
  $i18n: string;
  fallback: string;
}

export function textFallback(value: string | LocalizedText): string {
  return typeof value === 'string' ? value : value.fallback || value.$i18n;
}

export type RuntimeMode = 'live' | 'preview';

export interface RuntimeNodeContext {
  experienceSlug: string;
  pageId: string;
  componentId: string;
  stateKey: string;
  sourceStateKey: string;
  mode: RuntimeMode;
}

export interface RuntimeDataBinding {
  source: 'run-output' | 'system-binding';
  componentId?: string;
  bindingKey?: string;
  selector: string;
  input: Record<string, unknown>;
}

export type RuntimeAfterSuccess =
  | { kind: 'stay' | 'result' | 'reset' }
  | { kind: 'page'; pageId: string };

/** Closed post-action catalog. Page ids are route segments, never URLs. */
export function runtimeAfterSuccess(value: unknown): RuntimeAfterSuccess {
  if (value === 'result' || value === 'reset') return { kind: value };
  if (typeof value === 'string' && value.startsWith('page:')) {
    const pageId = value.slice(5);
    if (/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(pageId)) return { kind: 'page', pageId };
  }
  return { kind: 'stay' };
}

export type CatalogResolution =
  | { kind: 'skip' }
  | { kind: 'ok'; type: CertifiedType }
  | { kind: 'fallback'; type: string };

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
    const rawTitle = item['title'];
    const title =
      typeof rawTitle === 'string'
        ? rawTitle
        : isRecord(rawTitle)
          && typeof rawTitle['$i18n'] === 'string'
          && typeof rawTitle['fallback'] === 'string'
            ? { $i18n: rawTitle['$i18n'], fallback: rawTitle['fallback'] }
            : id;
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
  const dictionaries: Record<string, Record<string, string>> = {};
  if (isRecord(raw['i18n'])) {
    for (const [locale, entries] of Object.entries(raw['i18n'])) {
      if (!isRecord(entries)) continue;
      const copy: Record<string, string> = {};
      for (const [key, value] of Object.entries(entries)) {
        if (typeof value === 'string') copy[key] = value;
      }
      dictionaries[locale] = copy;
    }
  }
  return Object.keys(dictionaries).length > 0 ? { pages, i18n: dictionaries } : { pages };
}

/**
 * Resolve explicit document copy references without guessing which strings are
 * translatable. A persisted document uses:
 *
 *   { "$i18n": "expense.title", "fallback": "Expense request" }
 *   i18n: { fr: { "expense.title": "Note de frais" } }
 *
 * Missing release copy falls back to the author-provided text. Ready-check is
 * responsible for rejecting missing declared-language entries before release.
 */
export function localizeDocument(raw: unknown, locale: string): ExperienceDocument {
  if (!isRecord(raw)) return parseDocument(raw);
  const dictionaries = isRecord(raw['i18n']) ? raw['i18n'] : {};
  const exact = isRecord(dictionaries[locale]) ? dictionaries[locale] : {};
  const baseCode = locale.toLowerCase().slice(0, 2);
  const base = isRecord(dictionaries[baseCode]) ? dictionaries[baseCode] : {};
  return parseDocument(resolveLocalizedValue(raw, exact, base));
}

function resolveLocalizedValue(
  value: unknown,
  exact: Record<string, unknown>,
  base: Record<string, unknown>,
): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => resolveLocalizedValue(item, exact, base));
  }
  if (!isRecord(value)) return value;
  const key = value['$i18n'];
  if (typeof key === 'string' && key.trim()) {
    const translated = exact[key] ?? base[key];
    if (typeof translated === 'string' && translated.trim()) return translated;
    return typeof value['fallback'] === 'string' ? value['fallback'] : key;
  }
  const out: Record<string, unknown> = {};
  for (const [name, item] of Object.entries(value)) {
    if (name !== 'i18n') out[name] = resolveLocalizedValue(item, exact, base);
  }
  return out;
}

export function runtimeDataBinding(node: ExperienceNode): RuntimeDataBinding | null {
  const direct = node.props?.['dataBinding'];
  const query = node.props?.['queryBinding'];
  const raw = isRecord(query) ? query : isRecord(direct) ? direct : null;
  if (!raw) return null;
  const source = isRecord(query) ? 'system-binding' : 'run-output';
  if (raw['source'] !== source) return null;
  const bindingKey = typeof raw['bindingKey'] === 'string' ? raw['bindingKey'].trim() : '';
  const componentId = typeof raw['componentId'] === 'string' ? raw['componentId'].trim() : '';
  if (source === 'system-binding' && !bindingKey) return null;
  if (source === 'run-output' && !componentId) return null;
  return {
    source,
    bindingKey: bindingKey || undefined,
    componentId: componentId || undefined,
    selector: typeof raw['selector'] === 'string' ? raw['selector'].trim() : '',
    input: isRecord(raw['input']) ? raw['input'] : {},
  };
}

/** Safe property projection only: no expressions, calls, or prototype keys. */
export function selectRuntimeData(value: unknown, selector: string): unknown {
  if (!selector) return value;
  const parts = selector.split('.').filter(Boolean);
  let current = value;
  for (const part of parts) {
    if (part === '__proto__' || part === 'prototype' || part === 'constructor') return undefined;
    if (Array.isArray(current) && /^\d+$/.test(part)) {
      current = current[Number(part)];
      continue;
    }
    if (!isRecord(current) || !Object.prototype.hasOwnProperty.call(current, part)) return undefined;
    current = current[part];
  }
  return current;
}

export function runtimeStateKey(slug: string, pageId: string, componentId: string): string {
  return [slug || 'preview', pageId, componentId].map((part) => encodeURIComponent(part)).join(':');
}

export function isReadyFileReference(value: unknown): value is {
  kind: 'document';
  document_id: string;
  filename: string;
} {
  return isRecord(value)
    && value['kind'] === 'document'
    && typeof value['document_id'] === 'string'
    && !!value['document_id'].trim()
    && typeof value['filename'] === 'string';
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
  valueType: string;
  required: boolean;
  label: string;
  description: string;
  options: readonly string[];
  optionLabels: readonly string[];
  accept: string;
}

export function humanizeIdentifier(value: string): string {
  const label = value
    .trim()
    .replace(/([a-z\d])([A-Z])/g, '$1 $2')
    .replace(/[._/-]+/g, ' ')
    .replace(/\s+/g, ' ');
  return label ? label[0]!.toUpperCase() + label.slice(1) : '';
}

export type RuntimeResultScalar = string | number | boolean | null;

export interface RuntimeResultRow {
  path: Array<string | number>;
  value: RuntimeResultScalar;
}

/**
 * Turns an arbitrary action result into a bounded list of business-readable
 * leaves. Work never falls back to a JSON/code view: object keys are humanised,
 * array positions stay explicit, and pathological depth/volume is truncated.
 */
export function runtimeResultRows(
  value: unknown,
  maxDepth = 6,
  maxRows = 200,
): RuntimeResultRow[] {
  const rows: RuntimeResultRow[] = [];
  const seen = new WeakSet<object>();
  let truncated = false;

  const push = (path: Array<string | number>, scalar: RuntimeResultScalar): void => {
    if (rows.length >= maxRows) {
      truncated = true;
      return;
    }
    rows.push({ path, value: scalar });
  };
  const visit = (current: unknown, path: Array<string | number>, depth: number): void => {
    if (rows.length >= maxRows) {
      truncated = true;
      return;
    }
    if (current === null || current === undefined) {
      push(path, null);
      return;
    }
    if (typeof current === 'string' || typeof current === 'number' || typeof current === 'boolean') {
      push(path, current);
      return;
    }
    if (typeof current !== 'object') {
      push(path, String(current));
      return;
    }
    if (depth >= maxDepth || seen.has(current)) {
      push(path, '…');
      return;
    }
    seen.add(current);
    if (Array.isArray(current)) {
      if (current.length === 0) push(path, null);
      current.forEach((item, index) => visit(item, [...path, index + 1], depth + 1));
      return;
    }
    const entries = Object.entries(current as Record<string, unknown>);
    if (entries.length === 0) {
      push(path, null);
      return;
    }
    for (const [key, item] of entries) {
      visit(item, [...path, humanizeIdentifier(key) || key], depth + 1);
    }
  };

  visit(value, [], 0);
  if (truncated) rows.push({ path: ['…'], value: '…' });
  return rows;
}

/**
 * Project the executable contract and its optional, document-owned copy.
 * `presentation` never changes field names, values, types, or schema hashes.
 */
export function fieldsFromSchema(schema: unknown, presentation?: unknown): RuntimeField[] {
  if (!isRecord(schema)) return [];
  const properties = isRecord(schema['properties']) ? schema['properties'] : {};
  const copyByField = isRecord(presentation) ? presentation : {};
  const required = new Set(
    (Array.isArray(schema['required']) ? schema['required'] : [])
      .filter((key): key is string => typeof key === 'string'),
  );
  const fields: RuntimeField[] = [];
  for (const [name, raw] of Object.entries(properties)) {
    const spec = isRecord(raw) ? raw : {};
    const copy = isRecord(copyByField[name]) ? copyByField[name] : {};
    const options = Array.isArray(spec['enum'])
      ? spec['enum'].map((item) => String(item))
      : [];
    const optionCopy = isRecord(copy['options']) ? copy['options'] : {};
    const schemaLabel = typeof spec['title'] === 'string' && spec['title']
      ? spec['title']
      : humanizeIdentifier(name);
    const schemaDescription = typeof spec['description'] === 'string' ? spec['description'] : '';
    fields.push({
      name,
      kind: fieldKind(spec, options.length > 0),
      valueType: typeof spec['type'] === 'string' ? spec['type'] : 'string',
      required: required.has(name),
      label: typeof copy['label'] === 'string' && copy['label'].trim() ? copy['label'] : schemaLabel,
      description: typeof copy['description'] === 'string' && copy['description'].trim()
        ? copy['description']
        : schemaDescription,
      options,
      optionLabels: options.map((option) => {
        const value = Object.prototype.hasOwnProperty.call(optionCopy, option)
          ? optionCopy[option]
          : undefined;
        return typeof value === 'string' && value.trim() ? value : option;
      }),
      accept: typeof spec['contentMediaType'] === 'string' ? spec['contentMediaType'] : '',
    });
  }
  return fields;
}

/** JSON Schema subset faithfully rendered by the certified no-code form. */
export function formSchemaSupported(schema: unknown): boolean {
  if (!isRecord(schema) || (schema['type'] ?? 'object') !== 'object') return false;
  const supportedRoot = new Set([
    '$schema', 'type', 'title', 'description', 'properties', 'required', 'additionalProperties',
  ]);
  if (Object.keys(schema).some((key) => !supportedRoot.has(key))) return false;
  const unsupportedRoot = [
    '$ref', 'oneOf', 'anyOf', 'allOf', 'not', 'if', 'then', 'else',
    'dependentRequired', 'patternProperties', 'unevaluatedProperties',
    'minProperties', 'maxProperties',
  ];
  if (unsupportedRoot.some((key) => key in schema)) return false;
  const properties = schema['properties'] ?? {};
  const required = schema['required'] ?? [];
  if (!isRecord(properties) || !Array.isArray(required)) return false;
  if (required.some((item) => typeof item !== 'string' || !(item in properties))) return false;
  const unsupported = ['$ref', 'oneOf', 'anyOf', 'allOf', 'items', 'properties'];
  const supportedFieldKeys = new Set([
    'type', 'title', 'description', 'default', 'enum', 'format', 'contentMediaType', 'x-file',
  ]);
  for (const raw of Object.values(properties)) {
    if (
      !isRecord(raw)
      || unsupported.some((key) => key in raw)
      || Object.keys(raw).some((key) => !supportedFieldKeys.has(key))
    ) return false;
    const valueType = raw['type'] ?? 'string';
    if (!['string', 'number', 'integer', 'boolean'].includes(String(valueType))) return false;
    const fieldFormat = raw['format'];
    if (fieldFormat !== undefined && fieldFormat !== 'date' && fieldFormat !== 'binary') return false;
    if ((fieldFormat === 'date' || fieldFormat === 'binary') && valueType !== 'string') return false;
    if ('contentMediaType' in raw && fieldFormat !== 'binary' && raw['x-file'] !== true) return false;
    if ('x-file' in raw && raw['x-file'] !== true) return false;
    const values = raw['enum'];
    if (
      ('contentMediaType' in raw || raw['x-file'] === true)
      && fieldFormat !== undefined
      && fieldFormat !== 'binary'
    ) return false;
    if (
      (fieldFormat === 'binary' || 'contentMediaType' in raw || raw['x-file'] === true)
      && (valueType !== 'string' || values !== undefined)
    ) return false;
    if (values !== undefined) {
      if (!Array.isArray(values) || values.length === 0) return false;
      if (valueType === 'string' && values.some((item) => typeof item !== 'string')) return false;
      if (valueType === 'number' && values.some((item) => typeof item !== 'number')) return false;
      if (valueType === 'integer' && values.some((item) => typeof item !== 'number' || !Number.isInteger(item))) return false;
      if (valueType === 'boolean' && values.some((item) => typeof item !== 'boolean')) return false;
    }
  }
  return true;
}

/** Common contract shapes projected without making authors write selectors. */
export function runtimeItems(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (!isRecord(value)) return value === undefined || value === null ? [] : [value];
  for (const key of ['items', 'rows', 'cases', 'requests', 'events', 'results', 'data']) {
    if (Array.isArray(value[key])) return value[key];
  }
  return [value];
}

export function runtimeSummary(value: unknown): unknown {
  if (Array.isArray(value)) return value.length;
  if (!isRecord(value)) return value;
  for (const key of ['count', 'total', 'value', 'status', 'state', 'summary']) {
    const item = value[key];
    if (item !== undefined && item !== null && !isRecord(item) && !Array.isArray(item)) return item;
  }
  const list = Object.values(value).find(Array.isArray);
  if (list) return list.length;
  return Object.values(value).find((item) => item !== undefined && item !== null && !isRecord(item));
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
    if (field.required && empty) {
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
    if (field.kind === 'enum') {
      if (field.valueType === 'number' || field.valueType === 'integer') {
        const n = Number(value);
        if (Number.isFinite(n)) payload[field.name] = field.valueType === 'integer' ? Math.trunc(n) : n;
        continue;
      }
      if (field.valueType === 'boolean') {
        payload[field.name] = value === true || value === 'true';
        continue;
      }
    }
    if (
      field.kind === 'file'
      && field.valueType === 'string'
      && isRecord(value)
      && typeof value['document_id'] === 'string'
    ) {
      payload[field.name] = value['document_id'];
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
