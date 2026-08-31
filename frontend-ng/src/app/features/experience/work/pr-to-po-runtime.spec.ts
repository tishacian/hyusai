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
  assert.match(board, /\/mcp\/servers\/\$\{encodeURIComponent\(JUSTIFICATION_SERVER_ID\)\}\/read/);
  assert.match(board, /readJustification\(/);
  assert.doesNotMatch(board, /readJustification[\s\S]{0,400}this\.runtime\.invoke/);
});
