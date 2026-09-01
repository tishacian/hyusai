import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
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

test('the factory desk starts a cycle through the Experience binding', () => {
  const board = readFileSync(
    join(process.cwd(), 'src/app/features/experience/work/pr-to-po-board.component.ts'),
    'utf8',
  );
  assert.equal(board.includes('triggerRun('), false);
  assert.match(board, /ExperienceRuntimeService/);
  assert.match(board, /FACTORY_BINDING_KEY/);
  assert.match(board, /listPendingValidations/);
  assert.match(board, /factoryRunOrigin/);
  assert.match(board, /app-chat-panel/);
  assert.match(board, /\[compact\]="true"/);
  assert.doesNotMatch(board, /navigateByUrl\(factoryChatHref/);
  assert.doesNotMatch(board, /llm-portal|omnirag-llm-portal/);
  assert.match(board, /justificationReadBody/);
  assert.match(board, /approvedPrItemReadBody/);
  assert.match(board, /budgetReadBody/);
  assert.match(board, /acctAssgmtReadBody/);
  assert.match(board, /recentPosByPlantReadBody/);
  assert.doesNotMatch(board, /poItemReadBody/);
  assert.doesNotMatch(board, /poHeaderReadBody/);
  assert.match(board, /\/mcp\/servers\/\$\{encodeURIComponent\(JUSTIFICATION_SERVER_ID\)\}\/read/);
  assert.match(board, /\/mcp\/servers\/sap\/read/);
  assert.match(board, /\/mcp\/servers\/hikma\/read/);
  assert.match(board, /\/mcp\/servers\/\$\{encodeURIComponent\(serverId\)\}\/preview/);
  assert.match(board, /readJustification\(/);
  assert.doesNotMatch(board, /readJustification[\s\S]{0,400}this\.runtime\.invoke/);
  assert.doesNotMatch(board, /post_A_PurchaseOrder|fi_DiscardFromPurchasing|fi_EnableForPurchasing/);
  assert.doesNotMatch(board, /BAPI_PO_CREATE1|BAPI_TRANSACTION_COMMIT|BAPI_TRANSACTION_ROLLBACK/);
  assert.doesNotMatch(board, /\/mcp\/servers\/sap\/preview/);
  assert.doesNotMatch(board, /\/mcp\/servers\/hikma\/preview/);
  assert.match(board, /ck-thinking-orb/);
  assert.match(board, /terrainLoading\(\)[\s\S]{0,180}ck-thinking-orb/);
  assert.match(board, /starting\(\)[\s\S]{0,180}ck-thinking-orb/);
});

test('the factory portal chat wears the NAWA skin with orbs', () => {
  const board = readFileSync(
    join(process.cwd(), 'src/app/features/experience/work/pr-to-po-board.component.ts'),
    'utf8',
  );
  assert.match(board, /xp-desk-portal-head[\s\S]{0,120}ck-thinking-orb/);
  assert.match(board, /\[freshSession\]="true"/);
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
});

test('the studio owns the app root and the desk keeps its route', () => {
  const routes = readFileSync(
    join(process.cwd(), 'src/app/features/experience/work/work.routes.ts'),
    'utf8',
  );
  assert.match(routes, /path: 'pr-to-po',[\s\S]{0,120}pr-to-po-studio\.component/);
  assert.match(routes, /path: 'pr-to-po\/desk',[\s\S]{0,120}pr-to-po-board\.component/);
});

test('studio writes go through the flag-gated invoke endpoint, never a raw call', () => {
  const studio = readFileSync(
    join(process.cwd(), 'src/app/features/experience/work/pr-to-po-studio.component.ts'),
    'utf8',
  );
  assert.match(studio, /\/mcp\/servers\/\$\{encodeURIComponent\(serverId\)\}\/invoke/);
  assert.match(studio, /\/mcp\/servers\/\$\{encodeURIComponent\(serverId\)\}\/read/);
  assert.doesNotMatch(studio, /tools\/call/);
  assert.match(studio, /guardrailBlocked\(/);
  assert.match(studio, /sapWriteUnsealed/);
  assert.match(studio, /bapiCreateInvokeBody/);
  assert.match(studio, /bapiCommitInvokeBody/);
  assert.match(studio, /discardInvokeBody/);
  assert.match(studio, /app-chat-panel/);
  assert.match(studio, /\[freshSession\]="true"/);
  assert.match(studio, /ck-thinking-orb/);
  assert.match(studio, /routerLink="\/work\/pr-to-po\/desk"/);
});

test('the chat write dialogue confirms inside the thread and rides the same guarded path', () => {
  const studio = readFileSync(
    join(process.cwd(), 'src/app/features/experience/work/pr-to-po-studio.component.ts'),
    'utf8',
  );
  // The fifth chip opens the dialogue instead of prompting the model.
  assert.match(studio, /chip === 'create'[\s\S]{0,80}openChatWrite/);
  // Confirm / cancel live in the conversation, not in a modal.
  assert.match(studio, /xp-studio-dialog-yes[\s\S]{0,120}confirmChatWrite/);
  assert.match(studio, /xp-studio-dialog-no[\s\S]{0,120}cancelChatWrite/);
  // The confirmed write uses the same guardrail + invoke path as the gate.
  assert.match(studio, /chatInvoke[\s\S]{0,400}guardrailBlocked/);
  // The prompt carries live facts, not tool wishes.
  assert.match(studio, /studioFactSheet/);
  assert.match(studio, /facts: this\.chatFacts\(\)/);
});

test('the studio thread shows only the human question — facts ride the system role', () => {
  const studio = readFileSync(
    join(process.cwd(), 'src/app/features/experience/work/pr-to-po-studio.component.ts'),
    'utf8',
  );
  // Facts + instructions go to the panel's system-prompt input, never a bubble.
  assert.match(studio, /\[systemPrompt\]="chatSystemPrompt\(\)"/);
  assert.match(studio, /studio\.chat\.system/);
  // The visible prompt is the bare question (chip text or the default one).
  assert.doesNotMatch(studio, /studio\.chat\.prompt/);
  const panel = readFileSync(
    join(process.cwd(), 'src/app/features/chat/chat-panel.component.ts'),
    'utf8',
  );
  // The panel forwards the embed prompt on the system role of the request.
  assert.match(panel, /system_prompt: this\.systemPrompt\(\) \?\?/);
});
