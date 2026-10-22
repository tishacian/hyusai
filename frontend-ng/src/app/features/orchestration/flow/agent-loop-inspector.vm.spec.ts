import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import {
  agentLoopEnvelopeLine,
  clampConfidence,
  clampTurns,
  deadlineMinutes,
  formatSlugList,
  minutesToDeadlineMs,
  parseOptionalCost,
  itsdAgentLoopStarterFlow,
  itsdOverlayLoopConfig,
  parseDoneWhen,
  parseSlugList,
  readAgentLoopConfig,
  readHitlConfig,
  availableHitlPromptKinds,
  agentContextOptions,
  agentModelOptions,
  agentToolOptions,
  readDecisionContext,
  toggleAgentSelection,
} from './agent-loop-inspector.vm';
import type { PaletteItem } from './flow.types';
import type { ModelCatalogEntry } from '@app/core/model-catalog';

function loop(config: Record<string, unknown>): CanonicalFlowNode {
  return { id: 'loop.itsd', type: 'agent_loop', kind: 'agent_loop', config };
}

describe('agent-loop inspector projection', () => {
  test('parses allowlist lines and drops blanks, dupes, and a 9th slug', () => {
    assert.deepEqual(
      parseSlugList('azure_llm_v1\n\nazure_llm_v1\naudit_log_v1, semantic_search_v1\nextra_a\nextra_b\nextra_c\nextra_d\nextra_e\nextra_f'),
      [
        'azure_llm_v1',
        'audit_log_v1',
        'semantic_search_v1',
        'extra_a',
        'extra_b',
        'extra_c',
        'extra_d',
        'extra_e',
      ],
    );
    assert.equal(formatSlugList(['a', 'b']), 'a\nb');
  });

  test('reads a fail-closed envelope when the config bag is thin', () => {
    const cfg = readAgentLoopConfig(loop({}));
    assert.equal(cfg.privilege_tier, 'act_with_approval');
    assert.equal(cfg.budget.max_turns, 6);
    assert.equal(cfg.confidence_floor, 0.55);
    assert.deepEqual(cfg.skill_allowlist, []);
    assert.equal(cfg.goal.status, 'active');
  });

  test('clamps turns and confidence to the pinned envelope', () => {
    assert.equal(clampTurns(0), 6);
    assert.equal(clampTurns(99), 20);
    assert.equal(clampConfidence(-1), 0);
    assert.equal(clampConfidence(2), 1);
  });

  test('HumanGate prompt_kind falls back to approve_write', () => {
    const hitl = readHitlConfig({
      id: 'hitl.gate',
      type: 'hitl',
      kind: 'hitl',
      config: { prompt: 'Approve the write?', prompt_kind: 'not-a-kind' },
    });
    assert.equal(hitl.prompt_kind, 'approve_write');
    assert.equal(hitl.prompt, 'Approve the write?');
  });

  test('ITSD overlay starter is Trigger → Agent loop → Human gate → Output with a 1–8 allowlist', () => {
    const flow = itsdAgentLoopStarterFlow();
    const kinds = flow.nodes.map((node) => node.kind);
    assert.deepEqual(kinds, ['source', 'agent_loop', 'hitl', 'sink']);
    assert.equal(flow.edges.length, 3);
    const loopCfg = itsdOverlayLoopConfig();
    assert.ok(loopCfg.skill_allowlist.length >= 1);
    assert.ok(loopCfg.skill_allowlist.length <= 8);
    assert.equal(loopCfg.privilege_tier, 'act_with_approval');
    assert.match(loopCfg.goal.objective, /password/i);
    const gate = flow.nodes.find((node) => node.kind === 'hitl');
    assert.equal((gate?.config as { prompt_kind?: string } | undefined)?.prompt_kind, 'choice');
  });

  test('canvas line names the objective, budget, allowlist size and tier', () => {
    const line = agentLoopEnvelopeLine(
      loop({
        skill_allowlist: ['azure_llm_v1'],
        privilege_tier: 'recommend',
        budget: { max_turns: 4 },
        goal: { objective: 'Reset the password', done_when: [] },
      }),
    );
    assert.equal(line, 'Reset the password · 4 turns · 1/8 skills · recommend');
  });

  test('done_when keeps one criterion per line', () => {
    assert.deepEqual(parseDoneWhen('audit_log_v1\n\nidentity_verified'), [
      'audit_log_v1',
      'identity_verified',
    ]);
  });

  test('optional budget fields keep cost and a minute deadline or stay unset', () => {
    assert.equal(minutesToDeadlineMs('10'), 600_000);
    assert.equal(deadlineMinutes(600_000), '10');
    assert.equal(minutesToDeadlineMs(''), undefined);
    assert.equal(parseOptionalCost('1.5'), 1.5);
    assert.equal(parseOptionalCost('0'), 0);
    assert.equal(parseOptionalCost(''), undefined);
  });
});

test('agent tool catalogue explains saved unavailable tools without silently dropping them', () => {
  const item = (slug: string, label: string, unavailableReason?: string): PaletteItem => ({
    kind: 'task', type: 'skill', label, description: `${label} purpose`, icon: 'circle', tone: 'cyan',
    runtimeStatus: 'bound', config: { skill_slug: slug }, ...(unavailableReason ? { unavailableReason } : {}),
  });
  const options = agentToolOptions([
    item('read_order', 'Read order'), { ...item('payment_stub', 'Payment stub'), runtimeStatus: 'stub' }, item('send_payment', 'Send payment', 'not_allowed'), item('decide_next_v1', 'Planner'),
  ], ['missing_tool', 'read_order'], 'payment');
  assert.deepEqual(options.map(row => [row.slug, row.available, row.selected]), [
    ['missing_tool', false, true], ['read_order', true, true], ['payment_stub', false, false], ['send_payment', false, false],
  ]);
  assert.equal(options[1].description, 'Read order purpose');
  assert.deepEqual(toggleAgentSelection(['a', 'b'], 'c', true, 2), ['a', 'b']);
  assert.deepEqual(toggleAgentSelection(['a', 'b'], 'a', false, 2), ['b']);
});

test('agent context picker offers only declared business inputs and preserves a removed selection', () => {
  const node = loop({
    inputs_map: { risk_score: { node_id: 'risk', path: ['score'] }, context: 'run.context', model: 'run.model', _secret: 'run._secret', ' risk ': 'run.risk', password: 'run.password', db_access_token: 'run.token', case_id: 'run.case_id' },
    decision_context: { keys: ['risk_score', 'old_input', 'model'], max_bytes: 8192 },
  });
  const options = agentContextOptions(node, [{ id: 'risk', type: 'skill', label: 'Prioritize cases' }]);
  assert.deepEqual(options.map(row => [row.key, row.available, row.selected]), [
    ['risk_score', true, true], ['old_input', false, true], ['model', false, true], ['case_id', true, false],
  ]);
  assert.equal(options[0].source, 'Prioritize cases → score');
  assert.equal(readDecisionContext(node).max_bytes, 8192);
  assert.deepEqual(readDecisionContext(loop({})), { keys: [], max_bytes: 16384 });
  assert.deepEqual((node.config as Record<string, unknown>)['decision_context'], { keys: ['risk_score', 'old_input', 'model'], max_bytes: 8192 });
});

test('decision model picker allows configured text runtimes and preserves an unavailable saved model', () => {
  const model = (provider: string, name: string, configured = true): ModelCatalogEntry => ({
    provider, model: name, configured, discovered: true, runtime_available: true, compatibility: 'text_generation', status: 'configured',
  });
  const options = agentModelOptions([model('openai', 'gpt-5'), model('ollama', 'qwen3', false), { ...model('openai', 'embedding'), compatibility: 'other' }], 'azure_openai:previous');
  assert.deepEqual(options.map(row => [row.value, row.available]), [['azure_openai:previous', false], ['openai:gpt-5', true]]);
  const cfg = readAgentLoopConfig(loop({ model: 'openai:gpt-5', decision_context: { keys: ['risk'], max_bytes: 4096 } }));
  assert.equal(cfg.model, 'openai:gpt-5');
  assert.deepEqual(cfg.decision_context, { keys: ['risk'], max_bytes: 4096 });
});

test('generated retraining gate survives read/write while ordinary gates cannot select its mode', () => {
  const generated = {id:'review',kind:'hitl' as const,config:{prompt_kind:'approve_model_retraining',prompt:'Review proposed model'}};
  const reread = readHitlConfig({...generated,config:readHitlConfig(generated)});
  assert.equal(reread.prompt_kind,'approve_model_retraining');
  assert.ok(availableHitlPromptKinds(generated).includes('approve_model_retraining'));
  assert.ok(!availableHitlPromptKinds({...generated,config:{prompt_kind:'approve_write'}}).includes('approve_model_retraining'));
});
