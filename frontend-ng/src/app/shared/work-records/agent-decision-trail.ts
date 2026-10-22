import type { Run, SkillInvocation } from '@app/core/canonical-api.service';
import { recordedModelExecution, type ModelResolution } from '@app/core/model-catalog';

export type AgentChoiceState = 'deciding' | 'selected' | 'running' | 'completed' | 'failed' | 'cancelled' | 'human' | 'blocked' | 'budget' | 'finished' | 'unavailable' | 'not_executed';
export interface AgentContextField { key: string; present: boolean; source: string | null; }
export interface AgentChoice {
  id: string;
  number: number;
  loopId: string | null;
  turn: number | null;
  skill: string | null;
  purpose: string | null;
  rationale: string | null;
  state: AgentChoiceState;
  normalized: boolean;
  invocationId: string | null;
  model: ModelResolution | null;
  context: { fields: AgentContextField[]; sha256: string | null; bytes: number | null } | null;
}

const row = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown, max = 400): string | null => typeof value === 'string' && value.trim() ? value.trim().slice(0, max) : null;
const positive = (value: unknown): number | null => typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : null;
const keyList = (value: unknown): string[] => Array.isArray(value) ? [...new Set(value.flatMap(item => text(item, 160) ? [text(item, 160)!] : []))].slice(0, 16) : [];

function sourceLabel(value: unknown): string | null {
  if (typeof value === 'string') return text(value, 240);
  const source = row(value), node = text(source['node_id'], 100);
  const reference = text(source['reference'], 240);
  if (reference) return reference;
  const path = Array.isArray(source['path']) ? source['path'].filter(part => typeof part === 'string' || typeof part === 'number').map(String) : [];
  return node ? [node, ...path].join(' › ').slice(0, 240) : null;
}

function contextEvidence(trace: Record<string, unknown>): AgentChoice['context'] {
  const evidence = row(trace['agent_loop_context']);
  if (evidence['schema_version'] !== 1 || !Array.isArray(evidence['keys'])) return null;
  const present = new Set(keyList(evidence['present_keys']));
  const sources = row(evidence['sources']);
  return {
    fields: keyList(evidence['keys']).map(key => ({ key, present: present.has(key), source: sourceLabel(sources[key]) })),
    sha256: typeof evidence['sha256'] === 'string' && /^[a-f0-9]{64}$/i.test(evidence['sha256']) ? evidence['sha256'] : null,
    bytes: typeof evidence['bytes'] === 'number' && Number.isSafeInteger(evidence['bytes']) && evidence['bytes'] >= 0 ? evidence['bytes'] : null,
  };
}

function sameTurn(decision: SkillInvocation, action: SkillInvocation): boolean {
  const a = row(decision.trace), b = row(action.trace);
  // Never pair on skill name or list position: another loop / resumed passage
  // may call the same tool. Missing identities leave execution unconfirmed.
  return b['membrane_attempt_kind'] === 'agent_loop_act'
    && !!text(a['passage_id']) && a['passage_id'] === b['passage_id']
    && !!text(a['node_id']) && a['node_id'] === b['node_id']
    && positive(a['membrane_attempt_index']) !== null
    && a['membrane_attempt_index'] === b['membrane_attempt_index'];
}

function recordedGate(run: Run, decision: SkillInvocation, skill: string | null): Record<string, unknown> | null {
  const trace = row(decision.trace);
  if (!skill || !text(trace['passage_id']) || !text(trace['node_id']) || !positive(trace['membrane_attempt_index'])) return null;
  return (run.checkpoints ?? []).find(checkpoint => checkpoint['kind'] === 'agent_loop_policy_block'
    && checkpoint['passage_id'] === trace['passage_id'] && checkpoint['node_id'] === trace['node_id']
    && checkpoint['turn'] === trace['membrane_attempt_index'] && checkpoint['skill'] === skill) ?? null;
}

function choiceState(run: Run, decision: SkillInvocation, effective: Record<string, unknown>, action: SkillInvocation | null, skill: string | null, gate: Record<string, unknown> | null): AgentChoiceState {
  if (decision.status === 'running' || decision.status === 'pending') return 'deciding';
  if (decision.status === 'failed') return 'failed';
  if (decision.status === 'cancelled') return 'cancelled';
  if (decision.status !== 'completed') return 'unavailable';
  if (effective['needs_human'] === true || effective['exit'] === 'ask_human') return 'human';
  if (effective['exit'] === 'budget') return 'budget';
  if (effective['exit'] === 'blocked' || effective['exit'] === 'policy_block') return 'blocked';
  if (action?.status === 'completed') return 'completed';
  if (action?.status === 'failed') return 'failed';
  if (action?.status === 'cancelled') return 'cancelled';
  if (action?.status === 'running' || action?.status === 'pending') return 'running';
  if (gate) return gate['reason'] === 'write_needs_approval'
    ? ['failed', 'cancelled', 'completed'].includes(run.status) ? 'not_executed' : 'human'
    : 'blocked';
  if (effective['exit'] === 'complete' || effective['done'] === true) return 'finished';
  if (!skill) return 'unavailable';
  return ['failed', 'cancelled', 'completed'].includes(run.status) ? 'not_executed' : 'selected';
}

/** Recorded choices, separated from actions actually executed by the runtime.
 * The normalized decision is authoritative; raw provider prose is never an
 * approval, an action receipt, or a statement about hidden model reasoning. */
export function agentDecisionTrail(run: Run | null): AgentChoice[] {
  if (!run) return [];
  const calls = run.skill_invocations ?? [];
  const decisions = calls.filter(call => row(call.trace)['membrane_attempt_kind'] === 'agent_loop_decide' || call.skill_slug === 'decide_next_v1');
  return decisions.map((call, index) => {
    const trace = row(call.trace), decision = row(trace['agent_loop_decision']), output = row(call.output_ref);
    const hasRecordedDecision = Object.hasOwn(decision, 'effective');
    const effective = hasRecordedDecision ? row(decision['effective']) : output;
    const skill = text(effective['next_skill'], 160);
    const matches = skill ? calls.filter(action => action.skill_slug === skill && sameTurn(call, action)) : [];
    // More than one matching invocation is ambiguous; do not pick a favourable
    // result from retries. The canonical Run remains the detailed audit source.
    const action = matches.length === 1 ? matches[0] : null;
    const gate = recordedGate(run, call, skill);
    const visible = Array.isArray(call.input_ref?.['visible_skills']) ? call.input_ref['visible_skills'] : [];
    const catalogue = visible.map(row).find(item => item['slug'] === skill);
    const model = recordedModelExecution(call);
    return {
      id: call.id || `${run.id}:choice:${index}`,
      number: index + 1,
      loopId: text(trace['node_id'], 100),
      turn: positive(trace['membrane_attempt_index']),
      skill,
      purpose: text(catalogue?.['purpose'], 240),
      rationale: call.status === 'completed' ? text(output['rationale'], 1000) : null,
      state: matches.length > 1 ? 'unavailable' : choiceState(run, call, effective, action, skill, gate),
      normalized: !!gate || Array.isArray(decision['normalization_reasons']) && decision['normalization_reasons'].length > 0,
      invocationId: text(action?.id, 100),
      model: model && text(model.provider, 160) && text(model.model, 240) ? model : null,
      context: contextEvidence(trace),
    };
  });
}

/** A readable fallback for tools without a translated catalogue label. */
export function agentToolLabel(skill: string): string {
  const name = skill.replace(/_v\d+$/, '').replace(/[_.-]+/g, ' ').trim();
  return name ? name[0].toUpperCase() + name.slice(1) : skill;
}
