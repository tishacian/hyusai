import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  effectiveSystemTier,
  parseProviderModelSpec,
  routableModelOptions,
  routingTiers,
  type RoutingResponse,
} from './model-plane.types';

test('parseProviderModelSpec splits provider:model and provider/model', () => {
  assert.deepEqual(parseProviderModelSpec('openai:gpt-4o-mini'), {
    provider: 'openai',
    model: 'gpt-4o-mini',
  });
  assert.deepEqual(parseProviderModelSpec('ollama/qwen3:8b'), {
    provider: 'ollama',
    model: 'qwen3:8b',
  });
  assert.deepEqual(parseProviderModelSpec('gpt-4o-mini'), {
    provider: '',
    model: 'gpt-4o-mini',
  });
  assert.equal(parseProviderModelSpec('  '), null);
});

test('routingTiers normalises missing keys to empty strings', () => {
  assert.deepEqual(routingTiers({ tiers: { fast: 'ollama:qwen3:8b' } }), {
    fast: 'ollama:qwen3:8b',
    balanced: '',
    strong: '',
  });
  assert.deepEqual(routingTiers(null), { fast: '', balanced: '', strong: '' });
});

test('effectiveSystemTier prefers a pin, then matches it to a configured tier', () => {
  const route: RoutingResponse = {
    tiers: { balanced: 'openai:gpt-4o-mini', strong: 'openai:gpt-4o' },
  };
  assert.equal(effectiveSystemTier({ default_model: 'gpt-4o-mini' }, route), 'balanced');
  assert.equal(effectiveSystemTier({ default_model: 'openai:gpt-4o' }, route), 'strong');
  assert.equal(effectiveSystemTier({ default_model: 'claude-sonnet' }, route), 'pinned');
  assert.equal(effectiveSystemTier({ name: 'Chat' }, route), 'default');
});

test('routableModelOptions unions registered clients, local serving and live models', () => {
  const options = routableModelOptions(
    {
      registered_clients: ['openai', 'ollama'],
      local_serving: ['serving_lab'],
      tiers: { fast: 'ollama:qwen3:8b' },
    },
    [{ key: 'openai', status: 'active', models: ['gpt-4o-mini'] }],
  );
  assert.ok(options.includes('openai'));
  assert.ok(options.includes('openai:gpt-4o-mini'));
  assert.ok(options.includes('serving_lab'));
  assert.ok(options.includes('ollama:qwen3:8b'));
});
