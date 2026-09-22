import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Skill } from '@app/core/canonical-api.service';
import {
  automationFlow,
  automationName,
  automationSystemBody,
  selectAutomationSkill,
} from './automation-draft.model';

const skill: Skill = {
  id: 'skill-llm',
  slug: 'llm_rag_answer_v1',
  name: 'RAG Answer',
  category: 'LLM',
  runtime_status: 'bound',
  input_schema: {
    type: 'object',
    required: ['query'],
    properties: { query: { type: 'string' } },
  },
  output_schema: {
    type: 'object',
    properties: { answer: { type: 'string' } },
  },
};

test('automation-first keeps the Sim shape but stays a canonical System draft', () => {
  const body = automationSystemBody(skill, 'SPARK-365 meeting minutes');
  assert.equal(body.status, 'draft');
  assert.deepEqual(body.skill_ids, ['skill-llm']);
  assert.equal(body.name, 'SPARK-365 meeting minutes');

  const flow = body.flow_definition as ReturnType<typeof automationFlow>;
  assert.deepEqual(flow.nodes.map((node) => node.label), ['Trigger', 'Agent', 'Output']);
  assert.deepEqual(flow.edges.map((edge) => `${edge.from}->${edge.to}`), [
    'trigger->agent',
    'agent->output',
  ]);
  assert.equal(flow.variant, 'automation_v1');
  assert.equal(flow.nodes.length, 3, 'the first screen has three objects, not a registry');
  assert.equal(flow.nodes[2].inputs?.[0]?.schema, flow.nodes[1].outputs?.[0]?.schema);
});

test('automation input and skill query stay linked without JSON authoring', () => {
  const flow = automationFlow(skill, 'Summarise this meeting');
  const trigger = flow.nodes.find((node) => node.id === 'trigger');
  const agent = flow.nodes.find((node) => node.id === 'agent');
  const inputSchema = trigger?.config?.['input_schema'] as { properties?: Record<string, unknown> };
  assert.equal((inputSchema.properties?.transcript as { default?: string }).default, 'Summarise this meeting');
  assert.deepEqual(
    (agent?.config as Record<string, unknown>)?.inputs_map,
    { query: 'run.transcript' },
  );
});

test('the model prefers the workspace LLM over retrieval', () => {
  assert.equal(
    selectAutomationSkill([skill, { ...skill, id: 'ws', slug: 'workspace_llm_v1' }])?.slug,
    'workspace_llm_v1',
  );
  assert.equal(selectAutomationSkill([skill])?.slug, 'llm_rag_answer_v1');
  assert.equal(selectAutomationSkill([]), null);
  const flow = automationFlow({ ...skill, id: 'ws', slug: 'workspace_llm_v1' }, 'Draft the minutes');
  const agent = flow.nodes.find((node) => node.id === 'agent');
  const config = agent?.config as Record<string, unknown>;
  assert.deepEqual(config?.inputs_map, { transcript: 'run.transcript' });
  assert.deepEqual(config?.params, { instruction: 'Draft the minutes' });
  assert.equal(automationName('  Meeting   minutes  '), 'Meeting minutes');
});
