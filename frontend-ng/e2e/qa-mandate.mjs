/** Visual and navigation checks of real components using synthetic API fixtures only. */
import assert from 'node:assert/strict';
import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';

const base = process.env.BASE ?? 'http://localhost:4200';
const out = process.env.OUT ?? '../docs/reports/mandate-experience/visual-qa';
mkdirSync(out, {recursive: true});
const workspace = {id: 'ws-qa', slug: 'showcase', name: 'Showcase', role: 'admin', role_template: 'workspace_admin', mode: 'builder', is_active: true, settings: {features: {adoption_experience_v1: true}}};
const user = {id: 'qa-user', username: 'qa', email: 'qa@example.test', role: 'admin', roles: ['admin', 'owner'], is_active: true, first_name: 'QA', last_name: 'Local', workspaces: [workspace]};
const system = {id: 'northforge', workspace_id: workspace.id, name: 'NorthForge · NF-04', description: 'Préparation d’intervention', status: 'active', flow_sha256: 'qa-flow', settings: {}, flow_definition: {nodes: [], edges: []}};
const spec = {version: 2, enforcement_mode: 'enforce', inbound: {collection_allowlist: ['NorthForge manuals', 'Intervention history'], reject_cross_project_sources: true}, outbound: {expert_review_required: true}, capabilities: {allowed_skills: ['document_retrieval', 'intervention_analysis'], allowed_models: ['gpt-4.1'], allowed_actions: [], allowed_delegations: [{system_id: 'read-only-analysis', branches: ['success', 'refused']}]}, provenance: {require_citations: true}, valves: {max_cost_per_decision: 0.2, max_latency_ms: 60000, token_budget: 12000, hard_abort: true}};
const facets = ['inbound', 'outbound', 'capabilities', 'provenance', 'valves'];
const event = (id, kind, facet, status, rule, minute = 41, details = {}) => ({id, kind, facet, status, rule, at: `2026-09-17T09:${minute}:00Z`, node_id: facet === 'inbound' ? 'retrieve' : 'prepare', invocation_id: null, decision_id: id.startsWith('decision:') ? id.slice(9) : null, details});
const events = [
  event('invocation:retrieve:inbound', 'membrane_inbound', 'inbound', 'recorded', null, 41, {mode: 'enforce', allowed_collections: ['NorthForge manuals']}),
  event('checkpoint:egress', 'membrane_egress_evaluated', 'outbound', 'recorded', 'expert_review_required', 42, {mode: 'enforce', disposition: 'hold'}),
  event('decision:review', 'hitl_approval', 'outbound', 'approved', 'expert_review_required', 43, {decision_status: 'accepted', human_confirmed: true}),
  {...event('delegation:child-run', 'subflow_run', 'delegation', 'recorded', null, 41, {child_status:'completed'}), child_run_id:'child-run'},
];
const blockedEvent = event('decision:source-block', 'policy_block', 'inbound', 'blocked', 'collection_not_allowed', 41, {facet: 'inbound', reasons: ['collection_not_allowed'], human_confirmed: false});
const runEvents = id => id === 'run-1841' ? [] : id === 'run-1840' ? [blockedEvent] : events;
const runStatus = id => id === 'run-1840' ? 'failed' : 'completed';
const evidence = id => ({run_id: id, system_id: system.id, status: runStatus(id), applied: id === 'run-1841' ? {state: 'not_recorded', policy_id: null, revision: null, snapshot_at: null, mode: null, version: null, spec: null} : {state: 'recorded', policy_id: 'policy-nf', revision: 'qa-v3', snapshot_at: '2026-09-17T09:40:00Z', mode: 'enforce', version: 2, spec}, events: runEvents(id), counts: {recorded_events: runEvents(id).length, blocked: id === 'run-1840' ? 1 : 0, awaiting_human: 0}, limitations: []});
const runIds = ['run-1842', 'run-1841', 'run-1840', 'run-1839'];
const summaries = runIds.map((id, index) => ({run_id: id, status: runStatus(id), started_at: '2026-09-17T09:40:00Z', evidence_state: index === 1 ? 'not_recorded' : 'recorded', event_count: runEvents(id).length, recorded_mode: index === 1 ? null : 'enforce', recorded_version: index === 1 ? null : 2, facets: Object.fromEntries(facets.map(facet => {
  const matching = evidence(id).events.filter(e => e.facet === facet || (facet === 'capabilities' && e.facet === 'delegation')); const breached = matching.filter(e => e.status === 'blocked').length;
  return [facet, {event_count: matching.length, breach_count: breached, state: matching.length ? breached ? 'breached' : 'recorded' : 'not_recorded'}];
}))}));
const mandate = {system_id: system.id, system_name: system.name, configuration: {state: 'explicit', policy_id: 'policy-nf', policy_revision: 'qa-v3', version: 2, mode: 'enforce', spec, configured_facets: facets}, permissions: {can_edit: false}, editing_supported: false, recent_runs_limit: 4, limitations: [], recent_runs: summaries};
mandate.reference_labels = {skills:{document_retrieval:'Document retrieval',intervention_analysis:'Intervention analysis'},delegations:{'read-only-analysis':'Read-only investigation'}};
const run = id => ({id, system_id: system.id, workspace_id: workspace.id, status: runStatus(id), started_at: '2026-09-17T09:40:00Z', completed_at: '2026-09-17T09:44:00Z', input_ref: {question: 'Préparer le dossier NF-04'}, output_ref: {answer: '55 minutes observées pour 30 prévues. La cause reste à confirmer.'}, skill_invocations: [], checkpoints: [], trace: {}, metrics: {}, outcome: {decision: 'completed', reason: null, value_estimated: null, cost: null, confidence: null}});
function response(path) {
  if (/\/auth\/me|\/users\/me|\/me$/.test(path)) return user;
  if (/\/workspaces\/?$/.test(path)) return [workspace];
  if (/\/workspaces\/[^/]+\/?$/.test(path)) return workspace;
  if (path.endsWith('/systems/northforge/mandate')) return mandate;
  const proofId = path.match(/\/runs\/([^/]+)\/mandate$/)?.[1]; if (proofId) return evidence(proofId);
  const runId = path.match(/\/runs\/([^/]+)$/)?.[1]; if (runId) return run(runId);
  if (path.endsWith('/systems/northforge')) return system;
  if (path.endsWith('/systems')) return [system];
  if (path.endsWith('/runs')) return runIds.map(run);
  if (path.endsWith('/systems/northforge/flow-state')) return {system_id: system.id, status: 'active', draft: {revision: 1, flow_sha256: 'qa', flow_definition: system.flow_definition}, published: {version_id: null, version_number: null, flow_definition: {}}};
  if (path.includes('/evaluation/latest')) return {evaluation: null};
  if (path.includes('/evaluation/by-run/')) return null;
  if (path.endsWith('/documents/collections')) return {collections: []};
  if (/\/(skills|capabilities|collections|sessions|presets|help|apps|templates|models|contexts|connectors)\/?$/.test(path)) return [];
  return {items: [], results: [], total: 0, count: 0};
}

const browser = await chromium.launch(process.env.E2E_CHROMIUM_EXECUTABLE ? {executablePath: process.env.E2E_CHROMIUM_EXECUTABLE} : {});
const report = [];
try {
  for (const theme of ['light', 'dark']) for (const locale of ['fr', 'en']) {
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
    await context.addInitScript(({theme, locale}) => {
      localStorage.setItem('agentium_token', 'Bearer qa-local-token'); localStorage.setItem('agentium_workspace_slug', 'showcase'); localStorage.setItem('agentium_theme', theme); localStorage.setItem('agentium_locale', locale);
    }, {theme, locale});
    const page = await context.newPage(); const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', message => {if (message.type() === 'error' && /ERROR|NG[0-9]/.test(message.text())) errors.push(message.text());});
    await page.route('**/api/**', route => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(response(new URL(route.request().url()).pathname))}));
    const capture = async (name, selector) => {
      const target = page.locator(selector); await target.waitFor({timeout: 25000}); await page.waitForTimeout(150);
      const text = await target.innerText(); assert.ok(!/mandate(?:_system)?\.[a-z_]+/.test(text), `Untranslated key in ${name}`);
      const viewport = page.viewportSize();
      const overflow = await target.evaluate(el => ({left: el.getBoundingClientRect().left, right: el.getBoundingClientRect().right, viewport: innerWidth}));
      assert.ok(overflow.left >= 0 && overflow.right <= overflow.viewport + 2, `${name} overflows viewport: ${JSON.stringify(overflow)}`);
      // Keep the tested width, but fit the full component for the artifact: a
      // locator capture taller than the shell scrollport includes sticky overlays.
      const height = await target.evaluate(el => Math.ceil(el.getBoundingClientRect().height));
      await page.setViewportSize({width: viewport.width, height: Math.max(viewport.height, height + 900)});
      await page.locator('main').evaluateAll(elements => elements.forEach(el => el.scrollTo(0, 0)));
      await target.screenshot({path: `${out}/${name}-${theme}-${locale}.png`});
      await page.setViewportSize(viewport);
      report.push({name, theme, locale, url: page.url(), fixture: true, errors: [...errors], viewport, overflow});
    };
    await page.goto(`${base}/systems/northforge?lens=govern&facet=overview`, {waitUntil: 'domcontentloaded'});
    await page.locator('app-system-mandate-coverage .coverage-cell').first().waitFor({timeout: 25000});
    await capture('system-mandate', 'app-system-mandate');
    await capture('coverage', 'app-system-mandate-coverage');
    await page.locator('app-system-mandate-coverage .coverage-cell').nth(2).click();
    assert.equal(new URL(page.url()).searchParams.get('mandateFacet'), 'inbound');
    const evidenceLink = page.locator('.proof-event-link').first(); await evidenceLink.waitFor();
    await page.waitForFunction(() => new URL(document.querySelector('.proof-event-link')?.getAttribute('href') || '', location.origin).searchParams.get('mandateEvent') === 'decision:source-block');
    const proofHref = await evidenceLink.getAttribute('href'); assert.equal(new URL(proofHref, base).searchParams.get('mandateEvent'), 'decision:source-block');
    await evidenceLink.click();
    await capture('run-mandate', 'app-run-mandate');
    assert.ok(await page.locator('app-run-mandate .evidence').innerText().then(t => locale === 'fr' ? t.includes('collection demandée') : t.includes('requested collection')));
    await page.setViewportSize({width: 390, height: 844});
    await capture('run-mandate-narrow', 'app-run-mandate');
    await page.goto(`${base}/runs/run-1842?mandateEvent=delegation:child-run`, {waitUntil:'domcontentloaded'});
    const childLink = page.locator('app-run-mandate .evidence a').filter({hasText:locale === 'fr' ? 'Inspecter le Run délégué' : 'Inspect delegated Run'});
    await childLink.waitFor(); assert.match(await childLink.getAttribute('href'), /\/runs\/child-run/);
    await page.goto(`${base}/systems/northforge?lens=govern&facet=overview&mandateRun=run-1841&mandateFacet=inbound`, {waitUntil: 'domcontentloaded'});
    await page.locator('.proof-panel .coverage-versions').waitFor();
    assert.ok(await page.locator('.proof-panel').innerText().then(t => locale === 'fr' ? t.includes('Aucun mandat enregistré') : t.includes('No mandate recorded')));
    await capture('coverage-narrow-missing', 'app-system-mandate-coverage');
    await context.close();
  }
} finally {
  await browser.close(); writeFileSync(`${out}/visual-report.json`, JSON.stringify(report, null, 2));
}
if (report.some(r => r.errors.length)) throw Error(JSON.stringify(report.filter(r => r.errors.length)));
console.log(`${report.length} rendered states passed: real components, synthetic API fixtures. Screenshots: ${out}`);
