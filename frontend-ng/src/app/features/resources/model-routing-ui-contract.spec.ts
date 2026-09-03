/**
 * UI contract for native model routing: the Model portal tier editor, the
 * workspace Chat execution card, and the chat "Model routing" step.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { CHROME_EN, CHROME_FR } from '@app/core/i18n/chrome.dict';
import { CHAT_EN, CHAT_FR } from '@app/core/i18n/chat.dict';
import { RESOURCES_EN, RESOURCES_FR } from '@app/core/i18n/resources.dict';
import { lexiconEntry, lexiconTerm } from '@app/core/i18n.lexicon';

function source(...parts: string[]): string {
  return readFileSync(join(process.cwd(), 'src/app', ...parts), 'utf8');
}

const PORTAL = source('features/resources/resources-page.component.ts');
const GENERAL = source('features/workspace/general.component.ts');
const CHAT = source('features/chat/chat-panel.component.ts');

test('the Model portal edits the three tiers and stays visible outside beta', () => {
  assert.match(PORTAL, /routingTiersDraft/);
  assert.match(PORTAL, /modelTiers/);
  assert.match(PORTAL, /this\.loadRouting\(\)/);
  assert.match(PORTAL, /concept\.model-routing/);
  assert.match(PORTAL, /concept\.model-tier/);
  assert.match(PORTAL, /effectiveTierLabel/);
  assert.match(PORTAL, /resources\.providers\.routing\.systems\.column\.tier/);
  assert.match(PORTAL, /if \(this\.showPortalTabs\(\)\) \{\s*this\.loadPortalData/);
});

test('workspace settings expose the Chat execution card', () => {
  assert.match(GENERAL, /workspace\.general\.chat_execution\.title/);
  assert.match(GENERAL, /concept\.chat-execution/);
  assert.match(GENERAL, /selectChatExecutionMode/);
  assert.match(GENERAL, /saveChatExecution/);
  assert.match(GENERAL, /chat-execution-percentage/);
  assert.match(GENERAL, /setChatExecution/);
});

test('chat localises the model routing decision step', () => {
  assert.match(CHAT, /decisionStepTitle/);
  assert.match(CHAT, /isRoutingStep/);
  assert.match(CHAT, /chat\.trail\.routing\.title/);
  assert.match(CHAT, /chat\.progress\.routing/);
  assert.match(CHAT, /type === 'routing'/);
});

test('tier is a lexicon term and routeur is refused', () => {
  const tier = lexiconEntry('model-tier');
  assert.ok(tier);
  assert.equal(lexiconTerm('model-tier', 'fr'), 'Tier');
  assert.equal(lexiconTerm('model-tier', 'en'), 'Tier');
  const routing = lexiconEntry('model-routing');
  assert.ok(routing);
  assert.ok(routing?.banned.includes('routeur'));
  assert.equal(lexiconTerm('model-routing', 'fr'), 'Routage modèle');
  assert.equal(lexiconTerm('chat-execution', 'fr'), 'Exécution du chat');
});

test('every new routing / chat-execution key has FR and EN copy', () => {
  const resourceKeys = [
    'resources.providers.routing.tiers.title',
    'resources.providers.routing.systems.column.tier',
    'resources.providers.routing.systems.tier.pinned',
  ];
  for (const key of resourceKeys) {
    assert.ok((RESOURCES_FR as Record<string, string>)[key]?.trim(), key);
    assert.ok((RESOURCES_EN as Record<string, string>)[key]?.trim(), key);
  }
  const chromeKeys = [
    'workspace.general.chat_execution.title',
    'workspace.general.chat_execution.mode.hybrid',
    'workspace.general.toast.chat_execution_saved',
  ];
  for (const key of chromeKeys) {
    assert.ok((CHROME_FR as Record<string, string>)[key]?.trim(), key);
    assert.ok((CHROME_EN as Record<string, string>)[key]?.trim(), key);
  }
  const chatKeys = ['chat.trail.routing.title', 'chat.progress.routing'];
  for (const key of chatKeys) {
    assert.ok((CHAT_FR as Record<string, string>)[key]?.trim(), key);
    assert.ok((CHAT_EN as Record<string, string>)[key]?.trim(), key);
  }
});
