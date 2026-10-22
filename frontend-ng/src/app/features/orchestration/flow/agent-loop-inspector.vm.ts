/**
 * Pure projection for the AgentLoop / HumanGate inspector.
 * The walker already owns the envelope; this file only reads and writes
 * the author-facing config without inventing kinds.
 */
import type {
  AgentLoopNodeConfig,
  CanonicalFlow,
  CanonicalFlowNode,
  HitlNodeConfig,
} from '@app/core/flow-serializer.service';
import type { PaletteItem } from './flow.types';
import { catalogModelName, selectableTextModel, type ModelCatalogEntry } from '@app/core/model-catalog';

export type PrivilegeTier = NonNullable<AgentLoopNodeConfig['privilege_tier']>;
export type PromptKind = NonNullable<HitlNodeConfig['prompt_kind']>;
export type OnBudget = NonNullable<AgentLoopNodeConfig['on_budget']>;

export const PRIVILEGE_TIERS: readonly PrivilegeTier[] = [
  'recommend',
  'act',
  'act_with_approval',
];

export const PROMPT_KINDS: readonly PromptKind[] = [
  'choice',
  'validate_draft',
  'missing_file',
  'approve_write',
  'review_dataset_labels',
  'approve_model_retraining',
];

export const ITSD_OVERLAY_ALLOWLIST = [
  'azure_llm_v1',
  'audit_log_v1',
  'semantic_search_v1',
] as const;

export function parseSlugList(text: string, max = 8): string[] {
  const seen = new Set<string>();
  const slugs: string[] = [];
  for (const raw of text.split(/[\n,]+/)) {
    const slug = raw.trim();
    if (!slug || seen.has(slug)) continue;
    seen.add(slug);
    slugs.push(slug);
    if (slugs.length >= max) break;
  }
  return slugs;
}

export function formatSlugList(slugs: readonly string[]): string {
  return slugs.filter((slug) => slug.trim()).join('\n');
}

export function parseDoneWhen(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 12);
}

export function formatDoneWhen(items: readonly string[]): string {
  return items.filter((item) => item.trim()).join('\n');
}

export function clampTurns(value: unknown, fallback = 6): number {
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isSafeInteger(n) || n < 1) return fallback;
  return Math.min(n, 20);
}

export function clampConfidence(value: unknown, fallback = 0.55): number {
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(1, Math.max(0, n));
}

export function deadlineMinutes(ms: number | undefined): string {
  if (typeof ms !== 'number' || !Number.isFinite(ms) || ms <= 0) return '';
  return String(Math.round(ms / 60_000));
}

export function minutesToDeadlineMs(value: string): number | undefined {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return undefined;
  return Math.round(n * 60_000);
}

export function parseOptionalCost(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n < 0) return undefined;
  return n;
}

export function readAgentLoopConfig(node: CanonicalFlowNode): AgentLoopNodeConfig {
  const cfg = (node.config ?? {}) as Record<string, unknown>;
  const budget = (cfg['budget'] ?? {}) as Record<string, unknown>;
  const goal = (cfg['goal'] ?? {}) as Record<string, unknown>;
  const allowlist = Array.isArray(cfg['skill_allowlist'])
    ? cfg['skill_allowlist'].map((slug) => String(slug ?? '').trim()).filter(Boolean)
    : [];
  const doneWhen = Array.isArray(goal['done_when'])
    ? goal['done_when'].map((item) => String(item ?? '').trim()).filter(Boolean)
    : [];
  const privilege = cfg['privilege_tier'];
  const onBudget = cfg['on_budget'];
  return {
    decide_skill: 'decide_next_v1',
    ...(typeof cfg['model'] === 'string' && cfg['model'].trim() ? { model: cfg['model'].trim() } : {}),
    decision_context: readDecisionContext(node),
    skill_allowlist: allowlist.slice(0, 8),
    confidence_floor: clampConfidence(cfg['confidence_floor']),
    privilege_tier: PRIVILEGE_TIERS.includes(privilege as PrivilegeTier)
      ? (privilege as PrivilegeTier)
      : 'act_with_approval',
    on_budget: onBudget === 'ask_human' ? 'ask_human' : 'exit',
    budget: {
      max_turns: clampTurns(budget['max_turns'] ?? cfg['max_turns']),
      max_cost: typeof budget['max_cost'] === 'number' ? budget['max_cost'] : undefined,
      deadline_ms:
        typeof budget['deadline_ms'] === 'number' ? budget['deadline_ms'] : undefined,
    },
    goal: {
      objective: typeof goal['objective'] === 'string' ? goal['objective'] : '',
      done_when: doneWhen,
      status: 'active',
    },
  };
}

const RESERVED_CONTEXT_KEYS = new Set([
  'goal', 'observations', 'visible_skills', 'budget', 'model', 'confidence_floor',
  'agent_loop_node_id', 'context', 'context_evidence',
]);

const SECRET_CONTEXT_KEYS = new Set([
  'password', 'passwd', 'secret', 'api_key', 'apikey', 'access_token', 'refresh_token',
  'session_token', 'private_key', 'authorization', 'bearer', 'credential', 'credentials', 'dsn', 'token',
]);

export function authorizedContextKey(key: string): boolean {
  const name = key.trim().toLowerCase();
  return !!key && key === key.trim() && key.length <= 128 && !name.startsWith('_')
    && !RESERVED_CONTEXT_KEYS.has(key) && !SECRET_CONTEXT_KEYS.has(name)
    && ![...SECRET_CONTEXT_KEYS].some(suffix => name.endsWith(`_${suffix}`));
}

export function readDecisionContext(node: CanonicalFlowNode): { keys: string[]; max_bytes: number } {
  const cfg = node.config as Record<string, unknown> | undefined;
  const raw = cfg?.['decision_context'];
  const context = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, unknown> : {};
  return {
    // Keep invalid persisted selections visible. Reading must never silently repair a draft.
    keys: Array.isArray(context['keys']) ? [...new Set(context['keys'].filter((v): v is string => typeof v === 'string'))] : [],
    max_bytes: typeof context['max_bytes'] === 'number' ? context['max_bytes'] : 16_384,
  };
}

export interface AgentContextOption { key: string; label: string; source: string; available: boolean; selected: boolean; }

export function agentContextOptions(node: CanonicalFlowNode, nodes: readonly CanonicalFlowNode[]): AgentContextOption[] {
  const cfg = node.config as Record<string, unknown> | undefined;
  const raw = cfg?.['inputs_map'];
  const mappings = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, unknown> : {};
  const selected = new Set(readDecisionContext(node).keys);
  return [...new Set([...selected, ...Object.keys(mappings).filter(authorizedContextKey)])].map(key => {
    const binding = mappings[key];
    let source = '';
    if (typeof binding === 'string') source = binding;
    else if (binding && typeof binding === 'object' && !Array.isArray(binding)) {
      const ref = binding as Record<string, unknown>;
      const id = typeof ref['node_id'] === 'string' ? ref['node_id'] : '';
      const path = Array.isArray(ref['path']) ? ref['path'].join(' · ') : '';
      source = [nodes.find(item => item.id === id)?.label || id, path].filter(Boolean).join(' → ');
    }
    return { key, label: readableIdentifier(key), source, available: Object.hasOwn(mappings, key) && authorizedContextKey(key), selected: selected.has(key) };
  });
}

function readableIdentifier(value: string): string {
  const words = value.replace(/[_-]+/g, ' ').trim();
  return words ? words[0].toUpperCase() + words.slice(1) : value;
}

export interface AgentToolOption { slug: string; label: string; description: string; available: boolean; selected: boolean; }

/** The workspace catalogue supplies names and purposes; saved unavailable tools stay removable. */
export function agentToolOptions(items: readonly PaletteItem[], saved: readonly string[], query = ''): AgentToolOption[] {
  const selected = new Set(saved);
  const bySlug = new Map<string, AgentToolOption>();
  for (const item of items) {
    const slug = item.config?.['skill_slug'];
    if (typeof slug !== 'string' || !slug || ['decide_next_v1', 'skill_search_v1'].includes(slug)) continue;
    if (!bySlug.has(slug)) bySlug.set(slug, { slug, label: item.label || readableIdentifier(slug), description: item.description || '', available: !item.unavailableReason && item.runtimeStatus === 'bound', selected: selected.has(slug) });
  }
  for (const slug of saved) if (!bySlug.has(slug)) bySlug.set(slug, { slug, label: readableIdentifier(slug), description: '', available: false, selected: true });
  const needle = query.trim().toLocaleLowerCase();
  return [...bySlug.values()].filter(item => item.selected || !needle || `${item.label} ${item.description} ${item.slug}`.toLocaleLowerCase().includes(needle))
    .sort((a, b) => Number(b.selected) - Number(a.selected) || a.label.localeCompare(b.label));
}

export function toggleAgentSelection(saved: readonly string[], key: string, selected: boolean, limit: number): string[] {
  const existing = [...new Set(saved)];
  if (!selected) return existing.filter(item => item !== key);
  if (existing.includes(key) || existing.length >= limit) return existing;
  return [...existing, key];
}

export function agentModelOptions(models: readonly ModelCatalogEntry[], saved = ''): Array<{ value: string; label: string; available: boolean }> {
  const options = new Map<string, { value: string; label: string; available: boolean }>();
  for (const model of models.filter(selectableTextModel)) {
    const value = `${model.provider}:${catalogModelName(model)}`;
    options.set(value, { value, label: `${model.provider} · ${catalogModelName(model)}`, available: true });
  }
  if (saved && !options.has(saved)) options.set(saved, { value: saved, label: saved, available: false });
  return [...options.values()].sort((a, b) => a.label.localeCompare(b.label));
}

export function readHitlConfig(node: CanonicalFlowNode): HitlNodeConfig {
  const cfg = (node.config ?? {}) as Record<string, unknown>;
  const kind = cfg['prompt_kind'];
  return {
    prompt: typeof cfg['prompt'] === 'string' ? cfg['prompt'] : '',
    prompt_kind: PROMPT_KINDS.includes(kind as PromptKind)
      ? (kind as PromptKind)
      : 'approve_write',
  };
}

export function itsdOverlayLoopConfig(): AgentLoopNodeConfig {
  return {
    decide_skill: 'decide_next_v1',
    skill_allowlist: [...ITSD_OVERLAY_ALLOWLIST],
    confidence_floor: 0.55,
    privilege_tier: 'act_with_approval',
    on_budget: 'exit',
    budget: { max_turns: 6 },
    goal: {
      objective: 'Reset the requester AD password under ITSD policy',
      done_when: ['audit_log_v1'],
      status: 'active',
    },
  };
}

/** Trigger → Agent loop → Human gate → Output. Overlay config on the loop. */
export function itsdAgentLoopStarterFlow(): CanonicalFlow {
  const loop = itsdOverlayLoopConfig();
  return {
    schema_version: 3,
    source: 'flow',
    nodes: [
      {
        id: 'source.request',
        type: 'source',
        kind: 'source',
        label: 'Trigger',
        position: { x: 80, y: 200 },
        outputs: [{ name: 'goal', schema: 'string' }],
      },
      {
        id: 'loop.itsd',
        type: 'agent_loop',
        kind: 'agent_loop',
        label: 'ITSD agent loop',
        position: { x: 320, y: 160 },
        config: {
          skill_slug: 'decide_next_v1',
          ...loop,
        },
      },
      {
        id: 'hitl.gate',
        type: 'hitl',
        kind: 'hitl',
        label: 'Human gate',
        position: { x: 620, y: 160 },
        config: {
          prompt: 'Approve the next AgentLoop step?',
          prompt_kind: 'choice',
        },
      },
      {
        id: 'sink.result',
        type: 'sink',
        kind: 'sink',
        label: 'Output',
        position: { x: 900, y: 200 },
        inputs: [{ name: 'result', schema: 'object' }],
      },
    ],
    edges: [
      { from: 'source.request', to: 'loop.itsd', kind: 'data' },
      { from: 'loop.itsd', to: 'hitl.gate', kind: 'data' },
      { from: 'hitl.gate', to: 'sink.result', kind: 'data' },
    ],
  };
}

export function agentLoopEnvelopeParts(node: CanonicalFlowNode): {
  objective: string;
  turns: number;
  skills: number;
  privilege: PrivilegeTier;
} | null {
  if ((node.kind ?? 'task') !== 'agent_loop') return null;
  const cfg = readAgentLoopConfig(node);
  return {
    objective: cfg.goal.objective.trim(),
    turns: cfg.budget.max_turns,
    skills: cfg.skill_allowlist.length,
    privilege: cfg.privilege_tier ?? 'act_with_approval',
  };
}

export function formatAgentLoopEnvelopeLine(
  parts: NonNullable<ReturnType<typeof agentLoopEnvelopeParts>>,
  turnsWord = 'turns',
  skillsWord = 'skills',
): string {
  const head = parts.objective || '—';
  return `${head} · ${parts.turns} ${turnsWord} · ${parts.skills}/8 ${skillsWord} · ${parts.privilege}`;
}

export function agentLoopEnvelopeLine(node: CanonicalFlowNode): string | null {
  const parts = agentLoopEnvelopeParts(node);
  return parts ? formatAgentLoopEnvelopeLine(parts) : null;
}

/** Server-owned retraining mode is readable but cannot be selected on an ordinary gate. */
export function availableHitlPromptKinds(node: CanonicalFlowNode): readonly PromptKind[] {
  return readHitlConfig(node).prompt_kind === 'approve_model_retraining' ? PROMPT_KINDS : PROMPT_KINDS.filter(kind => kind !== 'approve_model_retraining');
}
