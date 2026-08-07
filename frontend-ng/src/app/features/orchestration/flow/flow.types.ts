/**
 * Shared types + defaults for the Flow Builder feature.
 *
 * P3 (dynamic-palette): `DEFAULT_PALETTE` now carries only the structural
 * graph primitives (source / sink / decision / fork / join / loop). The skill
 * entries are derived at runtime from `CanonicalApiService.listSkills()` via
 * `skillToPaletteItem()` (see `flow-catalog.service.ts`). Both flow through the
 * exact same `PaletteItem` shape, and `paletteItemToNode()` materializes the
 * binding (`skill_slug` / `skill_id` / `runtime_ref` + typed params) so a
 * dropped skill node is immediately operational when the skill is bound.
 */
import type {
  CanonicalFlow,
  CanonicalFlowNode,
  NodeKind,
  NodePort,
} from '@app/core/flow-serializer.service';
import type { Skill } from '@app/core/canonical-api.service';

export type NodeTone = 'brand' | 'cyan' | 'violet' | 'emerald' | 'amber' | 'rose';

/** Which palette group an entry belongs to. */
export type PaletteGroup = 'skill' | 'primitive';

/** Product taxonomy for Skills in the Flow Builder palette. Keep this order:
 * it is both the visual section order and the deterministic tie-breaker used
 * by the compatibility classifier for catalogs that predate `category`. */
export const SKILL_PALETTE_CATEGORIES = [
  'LLM',
  'Retrieval',
  'Connections',
  'Ingestion',
  'Voice',
  'Governance',
] as const;

export type SkillPaletteCategory = (typeof SKILL_PALETTE_CATEGORIES)[number];
export type SkillPaletteSection = SkillPaletteCategory | 'Other';
export type SkillRuntimeStatus = NonNullable<Skill['runtime_status']>;

/** A palette entry. `paletteItemToNode()` yields the node for `store.addNode`. */
export interface PaletteItem {
  /** Canonical node `type`. */
  type: string;
  kind: NodeKind;
  label: string;
  description: string;
  /** Lucide icon name (registered in icon-registry). */
  icon: string;
  tone: NodeTone;
  /** Typed input ports (empty = single implicit passthrough). */
  inputs?: NodePort[];
  /** Typed output ports (empty = single implicit passthrough). */
  outputs?: NodePort[];
  /**
   * Canonical `config` bag seeded on drop. For skills this carries the
   * binding (`skill_slug` / `skill_id` / `runtime_ref`) + `params` typed from
   * the skill `input_schema`. For structural primitives it seeds kind-specific
   * config (decision branches, loop budget, …).
   */
  config?: Record<string, unknown>;
  /** Canonical `data` bag seeded on drop (description, `runtime_status`). */
  data?: Record<string, unknown>;
  /** Short status tag rendered in the palette (e.g. a skill binding state). */
  badge?: string;
  /** Palette presentation taxonomy. Catalog Skills also persist the same
   * value under `config.skill_category` so inspectors/runtime adapters do not
   * need to re-infer product semantics from a mutable slug. */
  skillCategory?: SkillPaletteSection;
  /** Palette-only runtime state rendered as an explicit status badge. */
  runtimeStatus?: SkillRuntimeStatus;
}

/** Convert a palette item into a node payload for the store. */
export function paletteItemToNode(
  item: PaletteItem,
  position?: { x: number; y: number },
): Partial<CanonicalFlowNode> & { type: string } {
  return {
    type: item.type,
    kind: item.kind,
    label: item.label,
    data: { description: item.description, ...(item.data ?? {}) },
    inputs: item.inputs ?? [],
    outputs: item.outputs ?? [],
    config: { ...(item.config ?? {}) },
    position: position ?? { x: 160, y: 160 },
  };
}

/**
 * Structural graph primitives — the manifest "unit types" that stay as
 * graph semantics regardless of the live skill catalog. Skills are layered
 * on top dynamically (see `skillToPaletteItem`). Each primitive seeds the
 * kind-specific config the validator expects (decision branches, loop
 * budget, …) so a freshly dropped node starts valid.
 */
export const DEFAULT_PALETTE: PaletteItem[] = [
  {
    type: 'source',
    kind: 'source',
    label: 'Trigger',
    description: 'Flow input / objective',
    icon: 'crosshair',
    tone: 'emerald',
    outputs: [{ name: 'goal', schema: 'string' }],
  },
  {
    type: 'source.collection',
    kind: 'asset',
    label: 'Collection',
    description: 'Knowledge collection as a data source',
    icon: 'database',
    tone: 'cyan',
    outputs: [{ name: 'collection', schema: 'object' }],
    config: { collection_slug: '', workspace_scoped: true },
  },
  {
    type: 'source.sftp_arrival',
    kind: 'source',
    label: 'SFTP arrival',
    description: 'File-arrival trigger (staging close / reconciliation)',
    icon: 'server',
    tone: 'emerald',
    outputs: [{ name: 'file', schema: 'object' }],
    badge: 'event',
  },
  {
    type: 'source.schedule',
    kind: 'source',
    label: 'Schedule',
    description: 'Cron-driven trigger (managed in Triggers panel)',
    icon: 'clock',
    tone: 'emerald',
    outputs: [{ name: 'tick', schema: 'object' }],
    badge: 'cron',
  },
  {
    type: 'source.webhook',
    kind: 'source',
    label: 'Webhook',
    description: 'HMAC inbound webhook trigger',
    icon: 'globe',
    tone: 'emerald',
    outputs: [{ name: 'payload', schema: 'object' }],
    badge: 'http',
  },
  {
    type: 'decision',
    kind: 'decision',
    label: 'Decision',
    description: 'Branch on a condition',
    icon: 'git-branch',
    tone: 'violet',
    // `any` is intentionally outside the primitive incompatibility set: a
    // generic Decision can inspect scalar or structured upstream values.
    inputs: [{ name: 'value', schema: 'any' }],
    outputs: [
      { name: 'yes', schema: 'object' },
      { name: 'no', schema: 'object' },
    ],
    config: {
      passthrough_inputs: ['value'],
      branches: [
        { label: 'yes', condition: 'value == True' },
        { label: 'no', condition: 'value == False' },
      ],
      default_branch: 'no',
    },
  },
  {
    type: 'fork',
    kind: 'fork',
    label: 'Fork',
    description: 'Fan out parallel branches',
    icon: 'split',
    tone: 'violet',
    inputs: [{ name: 'in', schema: 'object' }],
    outputs: [
      { name: 'a', schema: 'object' },
      { name: 'b', schema: 'object' },
    ],
    config: { branches: ['a', 'b'] },
  },
  {
    type: 'join',
    kind: 'join',
    label: 'Join',
    description: 'Fan in parallel branches',
    icon: 'merge',
    tone: 'violet',
    inputs: [
      { name: 'a', schema: 'object' },
      { name: 'b', schema: 'object' },
    ],
    outputs: [{ name: 'out', schema: 'object' }],
    config: { strategy: 'all' },
  },
  {
    type: 'loop',
    kind: 'loop',
    label: 'Loop',
    description: 'Repeat until a budget or condition',
    icon: 'repeat',
    tone: 'amber',
    inputs: [{ name: 'in', schema: 'object' }],
    outputs: [{ name: 'out', schema: 'object' }],
    config: { max_iterations: 3 },
  },
  {
    type: 'sink',
    kind: 'sink',
    label: 'Output',
    description: 'Flow output / sink',
    icon: 'flag',
    tone: 'emerald',
    inputs: [{ name: 'result', schema: 'object' }],
  },
];

// ---------------------------------------------------------------------------
// Skill → palette projection (P3). Derives palette entries from the real
// `/skills` catalog (each carrying its typed `input_schema`). The produced
// `PaletteItem` carries the full skill binding so `paletteItemToNode()` yields
// a node that the serializer/manifest recognise as a bound skill unit.
// ---------------------------------------------------------------------------

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

const CATEGORY_ALIASES: ReadonlyArray<readonly [SkillPaletteCategory, RegExp]> = [
  ['LLM', /^(?:llm|language[ _-]?model|generation|generative)$/i],
  ['Retrieval', /^(?:retrieval|rag|search|knowledge)$/i],
  [
    'Connections',
    /^(?:connection|connections|connector|connectors|integration|integrations|tool|tools)$/i,
  ],
  ['Ingestion', /^(?:ingestion|ingest|document[ _-]?processing)$/i],
  ['Voice', /^(?:voice|speech|audio)$/i],
  [
    'Governance',
    /^(?:governance|policy|guardrail|guardrails|safety|compliance|evaluation)$/i,
  ],
];

const CATEGORY_HEURISTICS: ReadonlyArray<readonly [SkillPaletteCategory, RegExp]> = [
  [
    'LLM',
    /\b(?:llm|language model|model|generat\w*|summari\w*|synthesi\w*|answer\w*|draft\w*|completion|prompt|planner|planning|explain\w*|translat\w*|vision)\b/i,
  ],
  [
    'Retrieval',
    /\b(?:retriev\w*|rag|search\w*|lookup|vector\w*|embedd\w*|knowledge)\b/i,
  ],
  [
    'Connections',
    /\b(?:connect\w*|integration|webhook|http|api|sftp|email|calendar|slack|teams|jira|salesforce|sharepoint|tool)\b/i,
  ],
  [
    'Ingestion',
    /\b(?:ingest\w*|import\w*|upload\w*|extract\w*|pars\w*|chunk\w*|ocr|document processing)\b/i,
  ],
  ['Voice', /\b(?:voice|speech|audio|transcri\w*|tts|stt|livekit|speak\w*)\b/i],
  [
    'Governance',
    /\b(?:govern\w*|policy|guard\w*|safe\w*|moderat\w*|complian\w*|audit\w*|validat\w*|evaluation|eval|score|pii|approval|risk)\b/i,
  ],
];

function capabilityTerms(value: Skill['capabilities']): string[] {
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === 'string');
  }
  if (!value || typeof value !== 'object') return [];
  const terms: string[] = [];
  for (const [key, raw] of Object.entries(value)) {
    terms.push(key);
    if (typeof raw === 'string') terms.push(raw);
    if (Array.isArray(raw)) {
      terms.push(...raw.filter((item): item is string => typeof item === 'string'));
    }
  }
  return terms;
}

function canonicalCategory(value: string | null | undefined): SkillPaletteCategory | null {
  const normalized = value?.trim();
  if (!normalized) return null;
  for (const [category, pattern] of CATEGORY_ALIASES) {
    if (pattern.test(normalized)) return category;
  }
  return null;
}

/**
 * Resolve a Skill to the six-section product taxonomy. Explicit catalog
 * metadata wins. Older catalogs are classified from stable public fields in
 * a fixed rule order; genuinely unknown skills stay visible under `Other`.
 */
export function skillPaletteCategory(skill: Skill): SkillPaletteSection {
  const explicit = canonicalCategory(skill.category);
  if (explicit) return explicit;

  const capabilities = capabilityTerms(skill.capabilities);
  for (const term of capabilities) {
    const category = canonicalCategory(term);
    if (category) return category;
  }

  const typeCategory = canonicalCategory(skill.type);
  if (typeCategory) return typeCategory;

  const haystack = [
    skill.type,
    skill.slug,
    skill.name,
    skill.provider,
    skill.description,
    ...capabilities,
  ]
    .filter((value): value is string => typeof value === 'string' && value.length > 0)
    .join(' ')
    .replace(/[_-]+/g, ' ');
  for (const [category, pattern] of CATEGORY_HEURISTICS) {
    if (pattern.test(haystack)) return category;
  }
  return 'Other';
}

/** A type-appropriate empty value, used to seed required params with no default. */
function zeroForType(type: string): unknown {
  switch (type) {
    case 'integer':
    case 'number':
      return 0;
    case 'boolean':
      return false;
    case 'array':
      return [];
    case 'object':
      return {};
    case 'string':
      return '';
    default:
      return null;
  }
}

/**
 * Seed typed default params from a JSON-schema-ish `input_schema`. Properties
 * with an explicit `default` keep it; required properties without a default
 * get a typed empty value; optional defaultless properties are left unset so
 * the inspector can surface them as "to configure".
 */
export function defaultParamsFromSchema(
  schema: Record<string, unknown> | undefined | null,
): Record<string, unknown> {
  const root = asRecord(schema);
  const properties = asRecord(root['properties']);
  const required = new Set(
    (Array.isArray(root['required']) ? root['required'] : []).map((k) => String(k)),
  );
  const params: Record<string, unknown> = {};
  for (const [key, raw] of Object.entries(properties)) {
    const def = asRecord(raw);
    if ('default' in def) {
      params[key] = def['default'];
    } else if (required.has(key)) {
      params[key] = zeroForType(String(def['type'] ?? 'string'));
    }
  }
  return params;
}

/**
 * Derive typed dataflow ports (v3) from a JSON-schema-ish `output_schema`.
 * Each top-level property becomes a {@link NodePort} carrying its declared
 * primitive `type` (defaulting to `object`), so a dropped skill node
 * exposes a real output signature the validator/picker can reason about.
 * Returns `[]` when the schema declares no properties (ports stay
 * implicit — a single passthrough connector).
 */
export function portsFromSchema(
  schema: Record<string, unknown> | undefined | null,
): NodePort[] {
  const root = asRecord(schema);
  const properties = asRecord(root['properties']);
  const required = new Set(
    (Array.isArray(root['required']) ? root['required'] : []).map((k) => String(k)),
  );
  const ports: NodePort[] = [];
  for (const [name, raw] of Object.entries(properties)) {
    const def = asRecord(raw);
    const type = typeof def['type'] === 'string' ? (def['type'] as string) : 'object';
    const port: NodePort = { name, schema: type };
    if (required.has(name)) port.required = true;
    const desc = def['description'];
    if (typeof desc === 'string' && desc.length > 0) port.description = desc;
    ports.push(port);
  }
  return ports;
}

/** Pick a Lucide icon (registered in icon-registry) for a skill. */
function iconForSkill(skill: Skill): string {
  const hay = `${skill.type ?? ''} ${skill.slug} ${skill.name ?? ''}`.toLowerCase();
  if (/retriev|rag|search|lookup|fetch/.test(hay)) return 'search';
  if (/generat|answer|llm|summar|writ|draft/.test(hay)) return 'cpu';
  if (/guard|valid|policy|safe|moderat|complian/.test(hay)) return 'shield';
  if (/analy|insight|gap|score|eval|classif/.test(hay)) return 'microscope';
  if (/embed|vector|index/.test(hay)) return 'binary';
  if (/extract|parse|capture|ingest/.test(hay)) return 'file-search';
  return 'box';
}

/** Tone a skill chip by its runtime binding state (AA-contrast tokens). */
function toneForSkill(status: Skill['runtime_status']): NodeTone {
  switch (status) {
    case 'bound':
      return 'cyan';
    case 'stub':
      return 'amber';
    default:
      return 'violet';
  }
}

/**
 * Project a catalog Skill into a palette entry. The resulting node config
 * mirrors the canonical skill-node shape emitted by the backend bootstrap
 * (`config.skill_slug` / `skill_id` / `inputs_map` / `outputs_map`): on drop
 * the node is a recognised, parameterised skill unit. `runtime_ref` is only
 * stamped for *bound* skills so the manifest's `operational` flag (which is
 * `skill bound OR runtime_ref present`) stays truthful for stub/unbound ones.
 */
export function skillToPaletteItem(skill: Skill): PaletteItem {
  const status = skill.runtime_status ?? 'catalog_only';
  const bound = status === 'bound';
  const description = (skill.description ?? '').trim() || skill.slug;
  const params = defaultParamsFromSchema(skill.input_schema);
  const category = skillPaletteCategory(skill);

  const config: Record<string, unknown> = {
    skill_slug: skill.slug,
    skill_id: skill.id,
    skill_category: category,
    inputs_map: {},
    outputs_map: {},
  };
  if (Object.keys(params).length > 0) config['params'] = params;
  if (bound) config['runtime_ref'] = `skill:${skill.slug}`;

  // v3: surface the skill's declared outputs as typed dataflow ports so
  // the dropped node carries a real output signature. Inputs stay
  // implicit — the `input_schema` properties are params, not ports.
  const outputs = portsFromSchema(skill.output_schema);

  return {
    type: 'skill',
    kind: 'task',
    label: skill.name || skill.slug,
    description,
    icon: iconForSkill(skill),
    tone: toneForSkill(status),
    ...(outputs.length > 0 ? { outputs } : {}),
    config,
    data: { description, runtime_status: status },
    badge: status.replace(/_/g, ' '),
    skillCategory: category,
    runtimeStatus: status,
  };
}

/** A starter graph for the scratchpad (no System bound). */
export function defaultScratchFlow(): CanonicalFlow {
  return {
    source: 'flow',
    extended: false,
    schema_version: 3,
    nodes: [
      {
        id: 'flow.start',
        type: 'source',
        kind: 'source',
        label: 'Objective',
        data: { description: 'User objective' },
        outputs: [{ name: 'goal', schema: 'string' }],
        position: { x: 80, y: 160 },
      },
      {
        id: 'flow.retrieve',
        type: 'retrieve',
        kind: 'task',
        label: 'Retrieve',
        data: { description: 'Ground with knowledge' },
        inputs: [{ name: 'query', schema: 'string' }],
        outputs: [{ name: 'context', schema: 'object' }],
        position: { x: 380, y: 160 },
      },
      {
        id: 'flow.generate',
        type: 'llm',
        kind: 'task',
        label: 'Generate',
        data: { description: 'LLM answer' },
        inputs: [{ name: 'context', schema: 'object' }],
        outputs: [{ name: 'answer', schema: 'string' }],
        position: { x: 680, y: 160 },
      },
      {
        id: 'flow.output',
        type: 'sink',
        kind: 'sink',
        label: 'Output',
        data: { description: 'Flow result' },
        inputs: [{ name: 'result', schema: 'object' }],
        position: { x: 980, y: 160 },
      },
    ],
    edges: [
      { from: 'flow.start', to: 'flow.retrieve', kind: 'data' },
      { from: 'flow.retrieve', to: 'flow.generate', kind: 'data' },
      { from: 'flow.generate', to: 'flow.output', kind: 'data' },
    ],
  };
}
