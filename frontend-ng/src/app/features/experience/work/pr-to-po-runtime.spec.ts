import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import {
  FACTORY_BINDING_KEY,
  FACTORY_COMPONENT_ID,
  FACTORY_EXPERIENCE_SLUG,
  FACTORY_PAGE_ID,
  canStartFactoryCycle,
  factoryChatHref,
  factoryFlowHref,
  factoryRunHref,
  factoryRunOrigin,
  factoryRuntimeContext,
  factorySystemHref,
  isFactoryOriginRun,
  runAdapterOrigin,
} from './pr-to-po-runtime';

test('the factory cycle is the live Experience binding, not a System API shortcut', () => {
  assert.equal(FACTORY_EXPERIENCE_SLUG, 'pr-to-po');
  assert.equal(FACTORY_BINDING_KEY, 'procurement.pr_to_po.run');
  assert.equal(FACTORY_PAGE_ID, 'home');
  assert.equal(FACTORY_COMPONENT_ID, 'factory-cycle');
  assert.equal(factoryRunOrigin(), 'experience:pr-to-po');
  assert.deepEqual(factoryRuntimeContext(), {
    experienceSlug: 'pr-to-po',
    pageId: 'home',
    componentId: 'factory-cycle',
    stateKey: 'procurement.pr_to_po.run',
    sourceStateKey: 'procurement.pr_to_po.run',
    mode: 'live',
  });
});

test('a cycle may start only when the work binding resolve is ok', () => {
  assert.equal(canStartFactoryCycle({ status: 'ok' }), true);
  assert.equal(canStartFactoryCycle({ status: 'unavailable' }), false);
  assert.equal(canStartFactoryCycle({ status: 'drift' }), false);
  assert.equal(canStartFactoryCycle(null), false);
  assert.equal(canStartFactoryCycle(undefined), false);
});

test('lineage hrefs stay on the System and the Run', () => {
  assert.equal(factorySystemHref('ae0f9257-f1f6-46b5-a6d5-29ea41789e63'), '/systems/ae0f9257-f1f6-46b5-a6d5-29ea41789e63');
  assert.equal(
    factoryFlowHref('ae0f9257-f1f6-46b5-a6d5-29ea41789e63'),
    '/systems/ae0f9257-f1f6-46b5-a6d5-29ea41789e63/flow',
  );
  assert.equal(factoryRunHref('run/1'), '/runs/run%2F1');
});

test('the factory portal bridge opens workspace chat on the System', () => {
  const href = factoryChatHref(
    'nawa',
    '28345b5a-0824-4f2b-a420-ebe0aa7cd34f',
    'PR to PO factory. The SAP write stays sealed.',
  );
  const url = new URL(href, 'http://agentium.local');
  assert.equal(url.pathname, '/workspace/nawa/chat');
  assert.equal(url.searchParams.get('mode'), 'system');
  assert.equal(url.searchParams.get('systemId'), '28345b5a-0824-4f2b-a420-ebe0aa7cd34f');
  assert.match(url.searchParams.get('initialPrompt') || '', /write stays sealed/);
});

test('factory provenance is the Experience origin on the Run ingress', () => {
  assert.equal(
    runAdapterOrigin({
      _ingress: { adapter: { origin: 'experience:pr-to-po', binding_key: FACTORY_BINDING_KEY } },
    }),
    'experience:pr-to-po',
  );
  assert.equal(isFactoryOriginRun({ _ingress: { adapter: { origin: 'experience:pr-to-po' } } }), true);
  assert.equal(isFactoryOriginRun({ _ingress: { adapter: { origin: 'systems_run_api' } } }), false);
  assert.equal(isFactoryOriginRun({}), false);
});

test('the studio is a client of the server run — it never reads or writes SAP itself', () => {
  const studio = readFileSync(
    join(process.cwd(), 'src/app/features/experience/work/pr-to-po-studio.component.ts'),
    'utf8',
  );
  // One run through the Experience binding, one canonical HITL decision.
  assert.match(studio, /ExperienceRuntimeService/);
  assert.match(studio, /FACTORY_BINDING_KEY/);
  assert.match(studio, /studioRunPayload\(/);
  assert.match(studio, /this\.workApi\s*\.decide\(/);
  assert.match(studio, /listPendingValidations/);
  assert.match(studio, /this\.canonical\.getRun\(/);
  // No MCP read/invoke from the browser, no SAP tool name in a request body.
  assert.doesNotMatch(studio, /\/mcp\/servers\/[^'`]*\/(read|invoke|preview)/);
  assert.doesNotMatch(studio, /tools\/call/);
  assert.doesNotMatch(studio, /composeSealedPoPost|bapiCreateInvokeBody|bapiCommitInvokeBody|discardInvokeBody/);
  assert.doesNotMatch(studio, /approvedPrItemReadBody|budgetReadBody|recentPosByPlantReadBody|justificationReadBody/);
  // Guardrails ride the run input; the server blocks before the network.
  assert.match(studio, /disabledTools\(\)/);
  assert.match(studio, /sapWriteUnsealed/);
  // The gate and the chat dialogue share the one decision path.
  assert.match(studio, /approve\(\): void \{[\s\S]{0,60}this\.decide\('accept'\)/);
  assert.match(studio, /confirmChatWrite\(\): void \{[\s\S]{0,400}this\.decide\('accept'\)/);
  assert.match(studio, /chip === 'create'[\s\S]{0,80}openChatWrite/);
  assert.match(studio, /xp-studio-dialog-yes[\s\S]{0,120}confirmChatWrite/);
  assert.match(studio, /xp-studio-dialog-no[\s\S]{0,120}cancelChatWrite/);
  // Facts ride the system role; the thread shows only the human question.
  assert.match(studio, /\[systemPrompt\]="chatSystemPrompt\(\)"/);
  assert.match(studio, /studioFactSheet\(this\.run\(\)\)/);
  assert.doesNotMatch(studio, /studio\.chat\.prompt/);
  assert.match(studio, /app-chat-panel/);
  assert.match(studio, /\[freshSession\]="true"/);
  assert.match(studio, /ck-thinking-orb/);
  assert.match(studio, /xp-desk-portal-head[\s\S]{0,120}ck-thinking-orb/);
  // Lineage stays visible: the run is one click away.
  assert.match(studio, /factoryRunHref/);
});

test('the studio owns the app root and the former desk route lands on it', () => {
  const routes = readFileSync(
    join(process.cwd(), 'src/app/features/experience/work/work.routes.ts'),
    'utf8',
  );
  assert.match(routes, /path: 'pr-to-po',[\s\S]{0,160}pr-to-po-studio\.component/);
  assert.match(routes, /path: 'pr-to-po\/desk', redirectTo: 'pr-to-po'/);
  assert.doesNotMatch(routes, /pr-to-po-board/);
  assert.equal(existsSync(join(process.cwd(), 'src/app/features/experience/work/pr-to-po-desk.ts')), false);
  assert.equal(existsSync(join(process.cwd(), 'src/app/features/experience/work/pr-to-po-board.component.ts')), false);
});

test('the chat panel wears the NAWA skin with orbs and forwards the system prompt', () => {
  const panel = readFileSync(
    join(process.cwd(), 'src/app/features/chat/chat-panel.component.ts'),
    'utf8',
  );
  assert.match(panel, /:host-context\(\.xp-desk-portal\) \.ck-chat-user-bubble/);
  assert.match(panel, /:host-context\(\.xp-desk-portal\) \.ck-chat-assistant-bubble/);
  assert.match(panel, /:host-context\(\.xp-desk-portal\) \.ck-chat-send/);
  assert.match(panel, /:host-context\(\.xp-desk-portal\) \.ck-chat-input\b/);
  assert.match(panel, /--nawa-accent/);
  assert.match(panel, /ck-chat-empty-mark[\s\S]{0,200}ck-thinking-orb/);
  assert.match(panel, /ck-chat-progress[\s\S]{0,400}ck-thinking-orb/);
  assert.match(panel, /system_prompt: this\.systemPrompt\(\) \?\?/);
});
