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
  'chart',
  'prediction',
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
  /** Exact completed node output inside this authorized Run. */
  nodeId?: string;
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
    ...(typeof raw['nodeId'] === 'string' && raw['nodeId'].trim() ? { nodeId: raw['nodeId'].trim() } : {}),
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

/** An authored node selects only its latest attempt; failed retries never fall back. */
export function selectRuntimeRunData(run: {
  id?: string; output_ref?: Record<string, unknown>;
  skill_invocations?: Array<{ run_id?: string; status?: string; trace?: Record<string, unknown>; output_ref?: Record<string, unknown> }>;
} | null | undefined, binding: Pick<RuntimeDataBinding, 'selector' | 'nodeId'>): unknown {
  if (!binding.nodeId) return selectRuntimeData(run?.output_ref, binding.selector);
  const invocation = [...(run?.skill_invocations ?? [])].reverse().find(item => item.trace?.['node_id'] === binding.nodeId);
  if (!invocation || invocation.status !== 'completed' || (invocation.run_id && invocation.run_id !== run?.id)) return undefined;
  return selectRuntimeData(invocation.output_ref, binding.selector);
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
  minLength?: number;
  maxLength?: number;
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
      minLength: typeof spec['minLength'] === 'number' ? spec['minLength'] : undefined,
      maxLength: typeof spec['maxLength'] === 'number' ? spec['maxLength'] : undefined,
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
    'minLength', 'maxLength',
  ]);
  for (const raw of Object.values(properties)) {
    if (
      !isRecord(raw)
      || unsupported.some((key) => key in raw)
      || Object.keys(raw).some((key) => !supportedFieldKeys.has(key))
    ) return false;
    const valueType = raw['type'] ?? 'string';
    if (!['string', 'number', 'integer', 'boolean'].includes(String(valueType))) return false;
    if ('minLength' in raw || 'maxLength' in raw) {
      if (valueType !== 'string' || fieldKind(raw, false) === 'file') return false;
      for (const key of ['minLength', 'maxLength']) {
        if (key in raw && (typeof raw[key] !== 'number' || !Number.isSafeInteger(raw[key]) || raw[key] < 0)) return false;
      }
      if (typeof raw['minLength'] === 'number' && typeof raw['maxLength'] === 'number'
        && raw['minLength'] > raw['maxLength']) return false;
    }
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

// ---------------------------------------------------------------------------
// Categorical series
// ---------------------------------------------------------------------------

/** The shapes a certified chart draws. Anything else is read as bars. */
export const CHART_KINDS = ['bar', 'donut', 'timeseries'] as const;

export type ChartKind = (typeof CHART_KINDS)[number];

export function chartKind(value: unknown): ChartKind {
  return (CHART_KINDS as readonly unknown[]).includes(value) ? (value as ChartKind) : 'bar';
}

/**
 * How a series is coloured, which is a claim about what the categories *are*.
 *
 * `accent` says nothing: one hue for the whole series, so the only thing the
 * eye compares is length. `severity` walks green → amber → red across the
 * series in the order it was authored, which is right for bands that really
 * are ordered by how bad they are and actively misleading for anything else —
 * regions are not more severe than one another, and a ramp over them would
 * invent a ranking the data does not have. So it is opt-in, and the safe one
 * is the default.
 */
export const CHART_PALETTES = ['accent', 'severity'] as const;

export type ChartPalette = (typeof CHART_PALETTES)[number];

export function chartPalette(value: unknown): ChartPalette {
  return (CHART_PALETTES as readonly unknown[]).includes(value)
    ? (value as ChartPalette)
    : 'accent';
}

/**
 * `count` colours spread evenly across `stops`.
 *
 * A ramp has to work for however many bars the series turned out to have: three
 * bands and eleven both need the ends of the scale to mean the same thing, so
 * the stops are anchors rather than a lookup table. Anything that is not a hex
 * colour is passed straight back — a token can resolve to `rgb()` or to a name
 * on a browser this does not know, and a chart drawn in the wrong colour is
 * better than a chart drawn in `NaN`.
 *
 * Interpolated in OkLCH, which is the difference between a ramp and a smear.
 * Fading green to amber through their channel averages walks *through* grey,
 * because the shortest line between two saturated hues in sRGB passes near the
 * middle of the cube: the band between them comes out a dead olive that reads
 * as a rendering fault. Moving along the hue circle instead keeps the chroma
 * of the anchors, so the same two stops give the yellow everyone already
 * expects between green and orange.
 */
export function chartRamp(stops: readonly string[], count: number): string[] {
  if (count <= 0) return [];
  const parsed = stops.map(parseChartHex);
  if (stops.length === 0 || parsed.some((stop) => stop === null)) {
    return Array.from({ length: count }, (_, index) => stops[index % stops.length] ?? '');
  }
  const anchors = (parsed as Rgb[]).map(toOklch);
  if (count === 1) return [fromOklch(anchors[0]!)];
  return Array.from({ length: count }, (_, index) => {
    const position = (index / (count - 1)) * (anchors.length - 1);
    const lower = Math.floor(position);
    const upper = Math.min(lower + 1, anchors.length - 1);
    return fromOklch(mixOklch(anchors[lower]!, anchors[upper]!, position - lower));
  });
}

interface Rgb {
  r: number;
  g: number;
  b: number;
}

/** Lightness 0–1, chroma, hue in degrees. */
interface Oklch {
  l: number;
  c: number;
  h: number;
}

/** Below this a colour has no hue to interpolate, only a direction to borrow. */
const ACHROMATIC = 1e-4;

function parseChartHex(value: string): Rgb | null {
  const match = value.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (!match) return null;
  const hex =
    match[1]!.length === 3
      ? match[1]!.split('').map((channel) => channel + channel).join('')
      : match[1]!;
  return {
    r: Number.parseInt(hex.slice(0, 2), 16) / 255,
    g: Number.parseInt(hex.slice(2, 4), 16) / 255,
    b: Number.parseInt(hex.slice(4, 6), 16) / 255,
  };
}

function toLinear(channel: number): number {
  return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
}

function toGamma(channel: number): number {
  return channel <= 0.0031308 ? channel * 12.92 : 1.055 * channel ** (1 / 2.4) - 0.055;
}

function toOklch({ r, g, b }: Rgb): Oklch {
  const lr = toLinear(r);
  const lg = toLinear(g);
  const lb = toLinear(b);
  const long = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb);
  const medium = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb);
  const short = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb);
  const l = 0.2104542553 * long + 0.793617785 * medium - 0.0040720468 * short;
  const a = 1.9779984951 * long - 2.428592205 * medium + 0.4505937099 * short;
  const bAxis = 0.0259040371 * long + 0.7827717662 * medium - 0.808675766 * short;
  return {
    l,
    c: Math.hypot(a, bAxis),
    h: ((Math.atan2(bAxis, a) * 180) / Math.PI + 360) % 360,
  };
}

function fromOklch({ l, c, h }: Oklch): string {
  const radians = (h * Math.PI) / 180;
  const a = c * Math.cos(radians);
  const bAxis = c * Math.sin(radians);
  const long = (l + 0.3963377774 * a + 0.2158037573 * bAxis) ** 3;
  const medium = (l - 0.1055613458 * a - 0.0638541728 * bAxis) ** 3;
  const short = (l - 0.0894841775 * a - 1.291485548 * bAxis) ** 3;
  const channels = [
    4.0767416621 * long - 3.3077115913 * medium + 0.2309699292 * short,
    -1.2684380046 * long + 2.6097574011 * medium - 0.3413193965 * short,
    -0.0041960863 * long - 0.7034186147 * medium + 1.707614701 * short,
  ];
  // Clipped rather than gamut-mapped: an anchor is a real colour and the path
  // between two of them barely leaves sRGB, so the elaborate correction would
  // change nothing a reader could see.
  return `#${channels
    .map((channel) => Math.max(0, Math.min(255, Math.round(toGamma(channel) * 255))))
    .map((channel) => channel.toString(16).padStart(2, '0'))
    .join('')}`;
}

function mixOklch(from: Oklch, to: Oklch, ratio: number): Oklch {
  // Grey has coordinates but no hue: its `atan2` is whatever rounding left
  // behind, and interpolating towards it would swing the arc somewhere
  // arbitrary. Borrow the hue of the end that has one.
  const fromHue = from.c < ACHROMATIC ? to.h : from.h;
  const toHue = to.c < ACHROMATIC ? from.h : to.h;
  // The short way round, so green → red passes through yellow rather than
  // taking the long trip back through blue.
  const arc = (((toHue - fromHue + 540) % 360) - 180) * ratio;
  return {
    l: from.l + (to.l - from.l) * ratio,
    c: from.c + (to.c - from.c) * ratio,
    h: (fromHue + arc + 360) % 360,
  };
}

export interface ChartPoint {
  label: string;
  value: number;
  /** 0–100, relative to the largest magnitude actually plotted. */
  width: number;
  /**
   * 0–100, this point's share of the series total, or `null` when the series
   * is not a whole to take a share of.
   *
   * Length already ranks the bars against each other; the share is the other
   * question a reader asks of a band — "how much of the base is that" — and it
   * is the one they would otherwise do in their head, wrongly. It is withheld
   * when any value is negative, because a part of a total that some parts
   * subtract from is not a percentage of anything.
   */
  share: number | null;
}

export interface ChartSeries {
  points: ChartPoint[];
  /** Rows the cap left out, so the block can say so rather than quietly lie. */
  hidden: number;
}

/**
 * Twelve bars is what a reader compares at a glance; past that a chart is a
 * table with worse alignment. The feature-importance list of a model card
 * stops at the same twelve for the same reason.
 */
export const CHART_MAX_POINTS = 12;

/** A canvas legend does not ellipsize, so a pathological label is cut here. */
const CHART_MAX_LABEL = 32;

/**
 * A labelled series drawable as bars or slices, from whatever the author wrote
 * or the System returned.
 *
 * Both sides are untrusted: a released document passed a structural check that
 * says nothing about the numbers inside it, and a run output is whatever the
 * System produced this morning. A row without a usable label, or whose value is
 * not a number, is dropped rather than plotted at zero — a bar of length zero
 * reads as a measured nothing, which is a different claim from missing data.
 *
 * Over the cap the largest magnitudes win, drawn in the order they arrived:
 * ranking decides what is worth the space, but an authored order (critical,
 * high, medium, low) carries meaning that sorting would destroy.
 */
export function chartSeries(
  value: unknown,
  labelKey = 'label',
  valueKey = 'value',
  limit = CHART_MAX_POINTS,
): ChartSeries {
  const usable: { label: string; value: number }[] = [];
  for (const item of runtimeItems(value)) {
    if (!isRecord(item)) continue;
    const label = chartLabel(item[labelKey]);
    const number = chartValue(item[valueKey]);
    if (!label || number === null) continue;
    usable.push({ label, value: number });
  }
  const kept = usable.length <= limit ? usable : strongest(usable, limit);
  const peak = Math.max(...kept.map((point) => Math.abs(point.value)), 0);
  // The share is of what is drawn, not of what arrived: once the cap has hidden
  // rows the block says so, and percentages of a total the reader cannot see
  // would not add up on the page they are looking at.
  const total = kept.reduce((sum, point) => sum + point.value, 0);
  const whole = kept.every((point) => point.value >= 0) && total > 0;
  return {
    points: kept.map((point) => ({
      ...point,
      width: peak ? Math.round((Math.abs(point.value) / peak) * 100) : 0,
      share: whole ? (point.value / total) * 100 : null,
    })),
    hidden: usable.length - kept.length,
  };
}

function chartLabel(value: unknown): string {
  const text =
    typeof value === 'string'
      ? value.trim()
      : typeof value === 'number' && Number.isFinite(value)
        ? String(value)
        : '';
  return text.length > CHART_MAX_LABEL ? `${text.slice(0, CHART_MAX_LABEL - 1)}…` : text;
}

/** Numeric strings are accepted; `true`, `null` and `[]` are not numbers. */
function chartValue(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function strongest<T extends { value: number }>(points: readonly T[], limit: number): T[] {
  return points
    .map((point, index) => ({ point, index }))
    .sort((a, b) => Math.abs(b.point.value) - Math.abs(a.point.value) || a.index - b.index)
    .slice(0, limit)
    .sort((a, b) => a.index - b.index)
    .map((entry) => entry.point);
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
    const hasLengthConstraint = field.minLength !== undefined || field.maxLength !== undefined;
    const presentConstrainedText = hasLengthConstraint && field.kind === 'string' && typeof value === 'string';
    if (field.required && empty && !presentConstrainedText) {
      errors[field.name] = 'required';
      continue;
    }
    // Empty optional selections/dates are omitted by valuesToPayload, unlike text.
    if (empty && field.kind !== 'string') continue;
    if (hasLengthConstraint) {
      // JSON Schema counts Unicode code points; native minlength counts UTF-16 units.
      if (value !== undefined && value !== null) {
        const length = typeof value === 'string' ? Array.from(value).length : -1;
        if (length < 0 || length < (field.minLength ?? 0) || length > (field.maxLength ?? Infinity)) {
          errors[field.name] = 'invalid';
          continue;
        }
      }
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
