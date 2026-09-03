import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
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

// The Studio's behaviour — run through the binding, gate, canonical HITL
// decision, chat write dialogue, skin and orbs — is the e2e contract in
// `e2e/tests/18-nawa-agent-studio-canary.spec.ts`, exercised against the
// deployed revision. This file keeps a single source-level check, for the one
// invariant a browser test cannot prove by observation alone: the source has
// no path that could ever talk to SAP.
test('security invariant: the browser has no SAP path — no MCP call, no BAPI body', () => {
  const workDir = join(process.cwd(), 'src/app/features/experience/work');
  const sources = readdirSync(workDir)
    .filter((name) => name.endsWith('.ts') && !name.endsWith('.spec.ts'))
    .map((name) => [name, readFileSync(join(workDir, name), 'utf8')] as const);
  assert.ok(sources.some(([name]) => name === 'pr-to-po-studio.component.ts'));
  for (const [name, source] of sources) {
    assert.doesNotMatch(source, /\/mcp\/servers\/[^'`]*\/(read|invoke|preview)/, name);
    assert.doesNotMatch(source, /tools\/call/, name);
    // Tool *names* stay (the guardrail list shows them); a BAPI *body* never.
    assert.doesNotMatch(source, /TESTRUN/, name);
    assert.doesNotMatch(source, /POHEADER|POITEM|PoHeader|composeSealedPoPost/, name);
  }
});
