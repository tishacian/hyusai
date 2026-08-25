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
import { RECIPE_SKILL_SLUG, recipeDefaultParams } from './flow-recipe.vm';
import {
  POLARS_TRANSFORM_SKILL_SLUG,
  SQL_TRANSFORM_SKILL_SLUG,
  transformDefaultParams,
} from './flow-transform.vm';

export type NodeTone = 'brand' | 'cyan' | 'violet' | 'emerald' | 'amber' | 'rose';

/** Which palette group an entry belongs to. */
export type PaletteGroup = 'skill' | 'primitive';

/** Product taxonomy for Skills in the Flow Builder palette, in visual section
 * order. This mirrors `SKILL_CATEGORIES` in the backend seed catalog, which is
 * the single source of truth; the values arrive on `Skill.category`. */
export const SKILL_PALETTE_CATEGORIES = [
  'LLM',
  'Retrieval',
  'Connections',
  'Ingestion',
  'Voice',
  'Governance',
  'Analysis',
  'Decision Support',
  'Automation',
] as const;

export type SkillPaletteCategory = (typeof SKILL_PALETTE_CATEGORIES)[number];
export type SkillPaletteSection = SkillPaletteCategory | 'Other';
export type SkillRuntimeStatus = NonNullable<Skill['runtime_status']>;

/**
 * The visibility verdict `/skills` attaches to every catalog row.
 *
 * Declared here rather than on the shared `Skill` transport type: the palette
 * is the only consumer, and `reason` is the backend's machine code (see
 * `SkillVisibility` in `catalog_visibility.py`), not free text.
 */
export interface SkillVisibilityVerdict {
  visible: boolean;
  reason: string;
  /** Slugs of the Capabilities that carry this Skill in this workspace. */
  capabilities: string[];
  /** The excluding lever's key: an industry slug for `industry_not_allowed`,
   * a Capability slug for `capability_not_enabled`, empty otherwise. */
  key: string;
}

/** Read the verdict off a catalog row. Older backends omit it entirely, in
 * which case every returned row is by definition one the workspace sees. */
export function skillVisibilityVerdict(skill: Skill): SkillVisibilityVerdict | null {
  const raw = (skill as { visibility?: unknown }).visibility;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const record = raw as Record<string, unknown>;
  return {
    visible: record['visible'] !== false,
    reason: typeof record['reason'] === 'string' ? record['reason'] : 'unknown',
    capabilities: Array.isArray(record['capabilities'])
      ? record['capabilities'].map((slug) => String(slug)).filter(Boolean)
      : [],
    key: typeof record['key'] === 'string' ? record['key'] : '',
  };
}

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
  /** Workspace invocations aggregated by `/skills` (`metrics.calls`). Absent
   * for primitives, `0` for a catalog Skill this workspace never ran. */
  usageCalls?: number;
  /** Capability slugs carrying this Skill here — the palette's first
   * disclosure level, straight from the visibility verdict. */
  capabilitySlugs?: readonly string[];
  /** Set only on rows this workspace cannot use, carrying the backend
   * visibility reason. Such an entry explains itself and never drops. */
  unavailableReason?: string;
  /** The excluding lever's key, when it has one: the industry or Capability
   * the sentence has to name. */
  unavailableKey?: string;
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
    // `triggers.TRIGGER_TYPE_TO_EVENT` maps this type to `deposit.promoted`,
    // the one event allowed to feed a side-effecting downstream run.
    type: 'source.deposit_promoted',
    kind: 'source',
    label: 'Deposit promoted',
    description: 'Trigger when an operator promotes deposit files to a collection',
    icon: 'file-search',
    tone: 'emerald',
    outputs: [
      { name: 'collection_slug', schema: 'string' },
      { name: 'file_ids', schema: 'array' },
    ],
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
    type: 'agent_loop',
    kind: 'agent_loop',
    label: 'Agent loop',
    description: 'Bounded loop that chooses the next allowlisted skill',
    icon: 'repeat',
    tone: 'amber',
    inputs: [{ name: 'in', schema: 'object' }],
    outputs: [{ name: 'out', schema: 'object' }],
    config: {
      skill_slug: 'decide_next_v1',
      decide_skill: 'decide_next_v1',
      skill_allowlist: ['azure_llm_v1', 'audit_log_v1', 'semantic_search_v1'],
      confidence_floor: 0.55,
      privilege_tier: 'act_with_approval',
      on_budget: 'exit',
      budget: { max_turns: 6 },
      goal: { objective: '', done_when: [], status: 'active' },
    },
  },
  {
    type: 'hitl',
    kind: 'hitl',
    label: 'Human gate',
    description: 'Pause for a structured human decision, then resume',
    icon: 'shield',
    tone: 'rose',
    inputs: [{ name: 'in', schema: 'object' }],
    outputs: [
      { name: 'approved', schema: 'boolean' },
      { name: 'decision_id', schema: 'string' },
    ],
    config: { prompt: 'Approve this step?', prompt_kind: 'approve_write' },
  },
  {
    type: 'sink',
    kind: 'sink',
    label: 'Output',
    description: 'Where the Flow delivers its result',
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

const CATEGORY_BY_NAME = new Map<string, SkillPaletteCategory>(
  SKILL_PALETTE_CATEGORIES.map((category) => [category.toLowerCase(), category]),
);

/**
 * Resolve the palette section for a Skill from the catalog taxonomy.
 *
 * `category` is a free-text column so workspace-defined Skills can carry one
 * too; anything outside the canonical set stays visible under `Other` rather
 * than being dropped from the palette.
 */
export function skillPaletteSection(skill: Skill): SkillPaletteSection {
  const normalized = skill.category?.trim().toLowerCase();
  return (normalized && CATEGORY_BY_NAME.get(normalized)) || 'Other';
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
  if (skill.slug === RECIPE_SKILL_SLUG) return 'code-2';
  if (skill.slug === SQL_TRANSFORM_SKILL_SLUG) return 'database';
  if (skill.slug === POLARS_TRANSFORM_SKILL_SLUG) return 'code';
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
  let params = defaultParamsFromSchema(skill.input_schema);
  // The recipe Skill's catalog schema is generic object→object (the concrete
  // contract is authored on the node), so the executable defaults — the
  // `main` template and the timeout — are seeded here at drop time.
  if (skill.slug === RECIPE_SKILL_SLUG) {
    params = { ...recipeDefaultParams(), ...params };
  }
  // Same reason for the transform Skills: their catalog schema is a dataset
  // envelope, so the executable defaults — the starter program and the empty
  // pin list — are seeded here at drop time.
  if (skill.slug === SQL_TRANSFORM_SKILL_SLUG) {
    params = { ...transformDefaultParams('sql'), ...params };
  }
  if (skill.slug === POLARS_TRANSFORM_SKILL_SLUG) {
    params = { ...transformDefaultParams('polars'), ...params };
  }
  const category = skillPaletteSection(skill);

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
  const verdict = skillVisibilityVerdict(skill);
  const calls = skill.metrics?.calls;

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
    usageCalls: typeof calls === 'number' && Number.isFinite(calls) ? calls : 0,
    capabilitySlugs: verdict?.capabilities ?? [],
    ...(verdict && !verdict.visible
      ? {
          unavailableReason: verdict.reason,
          ...(verdict.key ? { unavailableKey: verdict.key } : {}),
        }
      : {}),
  };
}

/** The scratchpad opens empty (no System bound): the First-Flow guide on the
 *  empty canvas teaches the shape of a Flow, instead of a pre-wired template
 *  that raised checklist warnings before the user had done anything. */
export function emptyScratchFlow(): CanonicalFlow {
  return {
    source: 'flow',
    extended: false,
    schema_version: 3,
    nodes: [],
    edges: [],
  };
}
