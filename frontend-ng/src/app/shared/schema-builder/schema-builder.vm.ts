/**
 * The projection between a JSON Schema object and the rows a form can edit.
 *
 * The schema stays the model. These functions only project it onto a list of
 * field rows and write edited rows back, which is what makes the "Advanced
 * JSON" tab a real round trip rather than a second source of truth:
 *
 * * {@link projectSchema} reports every construct the rows cannot express
 *   (`$ref`, `oneOf`, arrays of objects, a third nesting level…). A schema
 *   that carries one is still shown and still saved — the visual rows simply
 *   step aside and say why, instead of silently dropping it.
 *
 * * {@link applyFields} rewrites `properties` and `required` and copies every
 *   other key of the original object through untouched, so annotations the
 *   rows know nothing about (`title`, `$schema`, `additionalProperties`) are
 *   preserved by an edit made in the visual tab.
 *
 * Deliberately free of Angular imports: the unit runner bundles this module
 * as a pure spec.
 */

/** Types a field row offers. Anything else keeps the author in the JSON tab. */
export const SCHEMA_FIELD_TYPES = [
  'string',
  'number',
  'integer',
  'boolean',
  'object',
  'array',
] as const;

export type SchemaFieldType = (typeof SCHEMA_FIELD_TYPES)[number];

/** One editable property of an object schema. */
export interface SchemaField {
  name: string;
  type: SchemaFieldType;
  required: boolean;
  description: string;
  /** String enum members. Empty means "any value of the type". */
  enumValues: string[];
  /** Raw text; coerced to the field type on the way into the schema. */
  defaultValue: string;
  /** For `object`, its own properties. One level only. */
  children: SchemaField[];
  /** For `array`, the type of its items. Objects and nested arrays are not
   * expressible as a row, so they land in `unsupported` instead. */
  itemType: 'string' | 'number' | 'integer' | 'boolean' | null;
  /** For `array`, write minItems = maxItems. Null leaves both unset. */
  exactCount: number | null;
}

export interface SchemaProjection {
  readonly fields: readonly SchemaField[];
  /**
   * Plain-language reasons the rows are not the whole schema. Empty means the
   * projection is faithful and the visual tab may write.
   */
  readonly unsupported: readonly string[];
}

/** Root keys the rows rebuild; everything else is carried through verbatim. */
const REBUILT_ROOT_KEYS = new Set(['type', 'properties', 'required']);
/** Root keys the rows leave alone but do not consider a loss of fidelity. */
const CARRIED_ROOT_KEYS = new Set([
  '$schema',
  'title',
  'description',
  'additionalProperties',
]);
/** Property keys a row knows how to read. */
const KNOWN_FIELD_KEYS = new Set([
  'type',
  'description',
  'title',
  'enum',
  'default',
  'properties',
  'required',
  'items',
  'minItems',
  'maxItems',
]);

type Dict = Record<string, unknown>;

const isDict = (value: unknown): value is Dict =>
  !!value && typeof value === 'object' && !Array.isArray(value);

/** The schema a blank contract starts from. */
export function emptyObjectSchema(): Dict {
  return { type: 'object', properties: {} };
}

/** A blank row, so "add a field" has one definition. */
export function blankField(name = ''): SchemaField {
  return {
    name,
    type: 'string',
    required: false,
    description: '',
    enumValues: [],
    defaultValue: '',
    children: [],
    itemType: null,
    exactCount: null,
  };
}

/**
 * Read a schema as editable rows, and name what the rows cannot hold.
 *
 * `depth` is an implementation detail of the one nesting level the rows
 * support; callers pass a schema, not a depth.
 */
export function projectSchema(schema: unknown): SchemaProjection {
  const unsupported: string[] = [];
  if (!isDict(schema)) {
    return { fields: [], unsupported: ['This contract is not a JSON object.'] };
  }
  if (Object.keys(schema).length === 0) {
    return { fields: [], unsupported: [] };
  }
  if (schema['type'] !== undefined && schema['type'] !== 'object') {
    unsupported.push(`The contract declares the type "${String(schema['type'])}", not an object.`);
  }
  for (const key of Object.keys(schema)) {
    if (REBUILT_ROOT_KEYS.has(key) || CARRIED_ROOT_KEYS.has(key)) continue;
    unsupported.push(`"${key}" at the top level has no equivalent as a field row.`);
  }
  const properties = schema['properties'];
  if (properties !== undefined && !isDict(properties)) {
    unsupported.push('"properties" is not an object.');
    return { fields: [], unsupported };
  }
  const required = requiredNames(schema, unsupported);
  const fields = readFields(isDict(properties) ? properties : {}, required, unsupported, 0);
  return { fields, unsupported };
}

function requiredNames(schema: Dict, unsupported: string[]): Set<string> {
  const raw = schema['required'];
  if (raw === undefined) return new Set();
  if (!Array.isArray(raw) || raw.some((item) => typeof item !== 'string')) {
    unsupported.push('"required" is not a list of field names.');
    return new Set();
  }
  return new Set(raw as string[]);
}

function readFields(
  properties: Dict,
  required: Set<string>,
  unsupported: string[],
  depth: number,
): SchemaField[] {
  const fields: SchemaField[] = [];
  for (const [name, raw] of Object.entries(properties)) {
    if (!isDict(raw)) {
      unsupported.push(`"${name}" is not described by an object.`);
      continue;
    }
    for (const key of Object.keys(raw)) {
      if (!KNOWN_FIELD_KEYS.has(key)) {
        unsupported.push(`"${name}" uses "${key}", which no field row can hold.`);
      }
    }
    const field = blankField(name);
    field.required = required.has(name);
    field.description = typeof raw['description'] === 'string' ? raw['description'] : '';
    field.type = readType(name, raw['type'], unsupported);
    readEnum(field, raw['enum'], unsupported);
    if (raw['default'] !== undefined) field.defaultValue = writeScalar(raw['default']);
    if (field.type === 'object') readChildren(field, raw, unsupported, depth);
    if (field.type === 'array') {
      readItems(field, raw['items'], unsupported);
      field.exactCount = readExactCount(raw);
    }
    fields.push(field);
  }
  return fields;
}

function readType(name: string, raw: unknown, unsupported: string[]): SchemaFieldType {
  if (raw === undefined) return 'string';
  if (typeof raw === 'string' && (SCHEMA_FIELD_TYPES as readonly string[]).includes(raw)) {
    return raw as SchemaFieldType;
  }
  unsupported.push(`"${name}" declares a type a field row cannot offer.`);
  return 'string';
}

function readEnum(field: SchemaField, raw: unknown, unsupported: string[]): void {
  if (raw === undefined) return;
  if (!Array.isArray(raw) || raw.some((item) => typeof item !== 'string')) {
    unsupported.push(`The allowed values of "${field.name}" are not a list of text values.`);
    return;
  }
  field.enumValues = raw as string[];
}

function readChildren(
  field: SchemaField,
  raw: Dict,
  unsupported: string[],
  depth: number,
): void {
  const nested = raw['properties'];
  if (nested === undefined) return;
  if (!isDict(nested)) {
    unsupported.push(`The properties of "${field.name}" are not an object.`);
    return;
  }
  if (depth >= 1) {
    unsupported.push(`"${field.name}" nests a third level, deeper than the rows go.`);
    return;
  }
  field.children = readFields(nested, requiredNames(raw, unsupported), unsupported, depth + 1);
}

function readItems(field: SchemaField, raw: unknown, unsupported: string[]): void {
  if (raw === undefined) return;
  const type = isDict(raw) ? raw['type'] : undefined;
  if (
    !isDict(raw)
    || Object.keys(raw).some((key) => key !== 'type')
    || typeof type !== 'string'
    || !['string', 'number', 'integer', 'boolean'].includes(type)
  ) {
    unsupported.push(`The items of "${field.name}" are richer than a single value type.`);
    return;
  }
  field.itemType = type as SchemaField['itemType'];
}

function readExactCount(raw: Dict): number | null {
  const minimum = raw['minItems'];
  const maximum = raw['maxItems'];
  if (
    typeof minimum !== 'number'
    || typeof maximum !== 'number'
    || !Number.isInteger(minimum)
    || minimum !== maximum
    || minimum < 0
  ) return null;
  return minimum;
}

/**
 * Write rows back into a schema, keeping every key the rows do not own.
 *
 * `original` is the schema currently stored; passing `{}` produces a schema
 * built from the rows alone.
 */
export function applyFields(original: unknown, fields: readonly SchemaField[]): Dict {
  const base: Dict = isDict(original) ? { ...original } : {};
  delete base['properties'];
  delete base['required'];
  const built = buildObject(fields);
  return { ...base, type: 'object', ...built };
}

function buildObject(fields: readonly SchemaField[]): Dict {
  const properties: Dict = {};
  const required: string[] = [];
  for (const field of fields) {
    const name = field.name.trim();
    if (!name) continue;
    properties[name] = buildField(field);
    if (field.required) required.push(name);
  }
  const out: Dict = { properties };
  if (required.length) out['required'] = required;
  return out;
}

function buildField(field: SchemaField): Dict {
  const spec: Dict = { type: field.type };
  const description = field.description.trim();
  if (description) spec['description'] = description;
  if (field.enumValues.length) spec['enum'] = [...field.enumValues];
  if (field.type === 'object' && field.children.length) {
    Object.assign(spec, buildObject(field.children));
  }
  if (field.type === 'array' && field.itemType) spec['items'] = { type: field.itemType };
  if (field.type === 'array' && field.exactCount !== null) {
    spec['minItems'] = field.exactCount;
    spec['maxItems'] = field.exactCount;
  }
  const fallback = readScalar(field.defaultValue, field.type);
  if (fallback !== undefined) spec['default'] = fallback;
  return spec;
}

/** Text → the JSON value of that type, or `undefined` when there is none. */
function readScalar(raw: string, type: SchemaFieldType): unknown {
  const text = raw.trim();
  if (!text) return undefined;
  if (type === 'boolean') return text === 'true';
  if (type === 'number' || type === 'integer') {
    const parsed = Number(text);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  if (type === 'object' || type === 'array') {
    try {
      return JSON.parse(text);
    } catch {
      return undefined;
    }
  }
  return text;
}

function writeScalar(value: unknown): string {
  if (typeof value === 'string') return value;
  return JSON.stringify(value) ?? '';
}

// ---------------------------------------------------------------------------
// Value entry — the other direction: a schema describing values to be typed.
// ---------------------------------------------------------------------------

/** One value to enter, derived from a property of an input contract. */
export interface ValueField {
  readonly name: string;
  readonly type: SchemaFieldType;
  readonly required: boolean;
  readonly description: string;
  readonly options: readonly string[];
}

/**
 * The top-level properties of an input contract, as values to fill in.
 *
 * Used for preset inputs: the target Skill already declares what it accepts,
 * so the author picks values rather than writing an object.
 */
export function valueFieldsFromSchema(schema: unknown): ValueField[] {
  if (!isDict(schema)) return [];
  const properties = schema['properties'];
  if (!isDict(properties)) return [];
  const required = new Set(
    Array.isArray(schema['required'])
      ? (schema['required'] as unknown[]).filter((item): item is string => typeof item === 'string')
      : [],
  );
  return Object.entries(properties).map(([name, raw]) => {
    const spec = isDict(raw) ? raw : {};
    const type = typeof spec['type'] === 'string' ? String(spec['type']) : 'string';
    const options = Array.isArray(spec['enum'])
      ? (spec['enum'] as unknown[]).map((item) => String(item))
      : [];
    return {
      name,
      type: ((SCHEMA_FIELD_TYPES as readonly string[]).includes(type)
        ? type
        : 'string') as SchemaFieldType,
      required: required.has(name),
      description: typeof spec['description'] === 'string' ? spec['description'] : '',
      options,
    };
  });
}

/**
 * Turn entered text into the object the runtime receives.
 *
 * A blank entry is an absent key, not an empty string: presetting nothing is
 * how the caller keeps deciding that input at run time.
 */
export function valuesToObject(
  fields: readonly ValueField[],
  entered: Readonly<Record<string, string>>,
): Dict {
  const out: Dict = {};
  for (const field of fields) {
    const raw = entered[field.name] ?? '';
    if (!raw.trim()) continue;
    const value = readScalar(raw, field.type);
    if (value !== undefined) out[field.name] = value;
  }
  return out;
}

/** The entries an object of preset values contributes to the form. */
export function objectToValues(value: unknown): Record<string, string> {
  if (!isDict(value)) return {};
  const out: Record<string, string> = {};
  for (const [key, entry] of Object.entries(value)) out[key] = writeScalar(entry);
  return out;
}

/**
 * Keys of a preset object that the derived form has no row for — because the
 * target contract does not declare them. Named rather than dropped: the
 * runtime merges them all the same.
 */
export function extraValueKeys(
  fields: readonly ValueField[],
  value: unknown,
): string[] {
  if (!isDict(value)) return [];
  const known = new Set(fields.map((field) => field.name));
  return Object.keys(value).filter((key) => !known.has(key));
}
