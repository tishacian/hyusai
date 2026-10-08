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
  return Math.min(n, 32);
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
