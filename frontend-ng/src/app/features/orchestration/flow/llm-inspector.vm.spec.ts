import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { FLOW_EN, FLOW_FR } from '@app/core/i18n/flow.dict';
import {
  isCompletionShaped,
  readBoundPromptSource,
  resolveLlmBinding,
} from './llm-inspector.vm';

function source(name: string): string {
  return readFileSync(
    join(process.cwd(), 'src/app/features/orchestration/flow', name),
    'utf8',
  );
}

function assertFlowKey(key: string): void {
  assert.ok((FLOW_FR as Record<string, string>)[key]?.trim(), `${key} has FR copy`);
  assert.ok((FLOW_EN as Record<string, string>)[key]?.trim(), `${key} has EN copy`);
}

test('completion-shaped is prompt or template, not every LLM category', () => {
  assert.equal(
    isCompletionShaped([{ key: 'prompt', source: 'skill.input_schema' }]),
    true,
  );
  assert.equal(
    isCompletionShaped([{ key: 'query', source: 'skill.input_schema' }], 'llm_rag_answer_v1'),
    false,
  );
  assert.equal(isCompletionShaped([], 'azure_llm_v1'), true);
});

test('a self-overlay prompt is not a bound excerpt', () => {
  assert.equal(
    readBoundPromptSource({
      prompt: { node_id: 'node', path: ['config', 'params', 'prompt'] },
    }),
    'node.params',
  );
  assert.equal(
    readBoundPromptSource({
      prompt: { node_id: 'task.brief_context', path: ['text'] },
    }),
    'task.brief_context.text',
  );
});

test('without a run the azure skill names the env bypass', () => {
  const binding = resolveLlmBinding({
    skillSlug: 'azure_llm_v1',
    portalEnabled: false,
    inputsMap: { prompt: { node_id: 'task.brief_context', path: ['text'] } },
  });
  assert.equal(binding.envBypass, true);
  assert.equal(binding.provider, 'openai');
  assert.equal(binding.credentialSource, 'env');
  assert.equal(binding.promptBound, true);
  assert.equal(binding.boundFrom, 'task.brief_context.text');
});

test('a finished invocation is the chip the inspector repeats', () => {
  const binding = resolveLlmBinding({
    skillSlug: 'azure_llm_v1',
    portalEnabled: true,
    lastRun: {
      effectiveModel: 'gpt-4o-mini',
      provider: 'openai',
      credentialSource: 'env',
    },
  });
  assert.equal(binding.modelSource, 'run');
  assert.equal(binding.provider, 'openai');
  assert.equal(binding.credentialSource, 'env');
});

test('a system default_model is named when the node is silent', () => {
  const binding = resolveLlmBinding({
    skillSlug: 'azure_llm_v1',
    portalEnabled: true,
    systemDefaultModel: 'gpt-4o-mini',
    routingProvider: 'openai',
  });
  assert.equal(binding.modelSource, 'system');
  assert.equal(binding.model, 'gpt-4o-mini');
  assert.equal(binding.provider, 'openai');
});

test('the inspector section and the SFTP link share a routerLink gesture', () => {
  const inspector = source('flow-inspector.component.ts');
  assert.match(inspector, /data-testid="llm-connector"/);
  assert.match(inspector, /routerLink="\/connectors\/models"/);
  assert.match(inspector, /data-testid="node-run-invocation"/);
  assertFlowKey('flow.inspector.section.llm');
  assertFlowKey('flow.inspector.llm.connector');
  assertFlowKey('flow.inspector.llm.bypass');
  assertFlowKey('flow.inspector.section.last_run');
  assertFlowKey('flow.inspector.last_run.loop');
});

test('prompt and template fields become textareas by name', () => {
  const fields = source('manifest-fields.component.ts');
  assert.match(fields, /key === 'prompt' \|\| key === 'template'/);
});
