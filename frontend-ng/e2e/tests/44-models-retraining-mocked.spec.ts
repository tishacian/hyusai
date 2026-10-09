import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page, type Route } from '@playwright/test';

test.use({ serviceWorkers: 'block', video: 'off', viewport: { width: 1440, height: 1000 } });
const catalog = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/ml-forecast.json'), 'utf8')).catalog;
const workspace = { id: 'retraining-qa', slug: 'retraining-qa', name: 'Retraining QA', role: 'owner', role_template: 'workspace_owner', settings: { features: { experience_v1: true } }, mode: 'builder' };
const systemId = 'monitoring-flow', runId = 'retraining-run', decisionId = 'retraining-decision', hash = '6'.repeat(64);
const model = { id: 'source-model', name: 'Ticket outcome', slug: 'ticket-outcome', version: 1, task: 'classification', family: 'tabular', algo: 'gradient_boosting', target: 'outcome', features: ['visits'], status: 'ready', is_champion: true, dataset_id: 'original', dataset_slug: 'original', row_count: 800, test_size: 0.25, cross_validation: 0, primary_metric: { key: 'accuracy', value: 0.8 }, metrics: { scores: [{ key: 'accuracy', value: 0.8 }] }, params: { knobs: {} }, spec: {}, classes: ['yes', 'no'], signature: { inputs: [{ name: 'visits', type: 'double' }], outputs: [{ name: 'prediction', type: 'string' }] } };
const frozen = { badge: 'alert', window: { predictions: 90, labeled: 40, limit: 1000, model_id: model.id, served_version: 1 }, data_drift: { status: 'alert', features: [{ name: 'visits', kind: 'numeric', value: 0.6, status: 'alert', psi_status: 'alert', test: { method: 'ks', status: 'alert', statistic: 0.4, p_value: 0.001, p_value_adjusted: 0.001, n_reference: 800, n_current: 90, reason: null } }] }, score_drift: { status: 'watch', value: 0.3, served_mean: 0.3, reference_mean: 0.8, n: 90 }, concept_drift: { status: 'alert', rolling_auc: 0.5, train_auc: 0.8, delta: -0.3, labeled: 40 } };
const binding = { proposal_id: 'proposal-1', model_id: model.id, model_version: 1, model_name: model.name, dataset_id: 'feedback-v2', dataset_version: 2, dataset_sha256: hash, labeled_rows: 40, training: { task: 'classification', algo: 'gradient_boosting', target: 'outcome', features: ['visits'], knobs: { trees: 100 }, spec: { text_encoder: 'auto' }, test_size: 0.25, cross_validation: 0 }, evidence: frozen };

async function setup(page: Page, locale: string, options: { forbidden?: boolean; readOnly?: boolean; missingContext?: boolean; cannotDecide?: boolean } = {}) {
  let status = 'hitl_pending', revision = 1;
  let policy = { enabled: false, propose_retraining: false, interval_minutes: 60, system_id: systemId };
  let graph: any = { schema_version: 3, source: 'flow', io_mode: 'strict', nodes: [
    { id: 'source', type: 'source', kind: 'source', label: 'Schedule', position: { x: 0, y: 120 }, config: { ingress: { kind: 'manual' }, input_schema: { type: 'object', properties: {} } } },
    { id: 'monitor', type: 'skill', kind: 'task', label: 'Monitor model', position: { x: 250, y: 120 }, outputs: [{ name: 'proposal_id', schema: 'string' }], config: { skill_slug: 'ml_monitor_model_v1', params: { model_id: model.id } } },
    { id: 'review', type: 'hitl', kind: 'hitl', label: 'Approve retraining', position: { x: 500, y: 120 }, inputs: [{ name: 'proposal_id', schema: 'string' }], outputs: [{ name: 'approved', schema: 'boolean' }], config: { prompt_kind: 'approve_model_retraining', inputs_map: { proposal_id: { node_id: 'monitor', path: ['proposal_id'], required: true } } } },
    { id: 'train', type: 'skill', kind: 'task', label: 'Train challenger', position: { x: 750, y: 120 }, inputs: [{ name: 'proposal_id', schema: 'string' }], outputs: [{ name: 'model_id', schema: 'string' }], config: { skill_slug: 'ml_retrain_model_v1', inputs_map: { proposal_id: { node_id: 'review', path: ['proposal_id'] } } } },
    { id: 'sink', type: 'sink', kind: 'sink', label: 'Challenger output', position: { x: 1000, y: 120 }, config: {} },
  ], edges: ['source', 'monitor', 'review', 'train'].map((from, i) => ({ id: `e${i}`, from, to: ['monitor', 'review', 'train', 'sink'][i], kind: 'data' })) };
  const posts: any[] = [], approvals: any[] = [], drafts: any[] = [];
  const run = () => ({ id: runId, system_id: systemId, status, flow_sha256: hash, input_ref: {}, output_ref: {}, skill_invocations: [], checkpoints: [], hitl: status === 'hitl_pending' ? { node_id: 'review', prompt: 'Approve proposed retraining', prompt_kind: 'approve_model_retraining', can_decide: !options.cannotDecide, decision_id: decisionId, decision_status: 'proposed', model_retraining: options.missingContext ? null : binding, upstream: { proposal_id: binding.proposal_id } } : undefined });
  const system = () => ({ id: systemId, name: 'Monitoring', status: 'active', workspace_id: workspace.id, flow_definition: graph, flow_sha256: hash });
  const state = () => ({ system_id: systemId, status: 'active', draft: { revision, base_published_version_id: 'published-v1', flow_sha256: hash, flow_definition: graph }, published: { version_id: 'published-v1', version_number: 1, flow_sha256: hash, flow_definition: graph, execution_contract_ready: true } });
  const monitoring = () => ({ ...frozen, badge: null, window: { predictions: 0, labeled: 0, limit: 1000, model_id: model.id, served_version: 1 }, scheduled: {
    supported: true, can_configure: !options.readOnly, policy,
    history: [{ id: 'snapshot-1', created_at: '2026-10-08T10:00:00', badge: 'alert', window: frozen.window, reason: 'ML_RETRAIN_FEEDBACK_INSUFFICIENT' }],
    proposals: [{ id: binding.proposal_id, status: 'queued', stage: 'awaiting_approval', error: null, created_at: '2026-10-08T10:00:00', run_id: runId, decision_id: decisionId, model_id: 'new-challenger', source_model_id: model.id, source_version: 1, source_model_name: model.name, dataset_id: binding.dataset_id, dataset_version: 2, dataset_sha256: hash, labeled_rows: 40, training: binding.training, evidence: frozen }],
  } });
  const json = (route: Route, body: unknown, code = 200) => route.fulfill({ status: code, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.addInitScript(({ slug, locale }) => { localStorage.setItem('agentium_token', 'Bearer retraining-qa'); localStorage.setItem('agentium_workspace_slug', slug); localStorage.setItem('agentium_theme', locale === 'fr' ? 'dark' : 'light'); localStorage.setItem('agentium_locale', locale); }, { slug: workspace.slug, locale });
  await page.route('**/api/v1/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa', role: 'admin' });
    if (path === '/auth/me') return json(route, { id: 'qa', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === `/auth/workspaces/${workspace.slug}`) return json(route, workspace);
    if (path === '/ml-models/catalog') return json(route, { catalog });
    if (path === '/ml-models') return json(route, { models: [model], catalog });
    if (path === `/ml-models/${model.id}`) return json(route, { model, dataset: null, versions: [model], challenger_id: null, catalog, serving: { enabled: true, callable: true, serving_model_id: model.id, serving_version: 1, fields: [], classes: model.classes, keys: [] } });
    if (path === `/ml-models/${model.id}/monitoring`) return json(route, { monitoring: monitoring() });
    if (path === `/ml-models/${model.id}/monitoring/policy`) { posts.push(req.postDataJSON()); if (options.forbidden) return json(route, { detail: { code: 'ML_MONITORING_FORBIDDEN' } }, 403); policy = { ...policy, ...req.postDataJSON() }; return json(route, { monitoring: monitoring() }); }
    if (path === '/work/retraining') return json(route, { experience: { id: 'review-app', slug: 'retraining', name: 'Retraining', pattern: 'approval', languages: ['fr', 'en'] }, channel: 'live', release: { id: 'release', release_number: 1, renderer_version: 'certified-components-0.2.0', bindings_snapshot: [{ system_id: systemId }], pages: { pages: [{ id: 'home', title: 'Retraining', components: [] }] }, languages: ['fr', 'en'] } });
    if (path === '/work/retraining/validations') return json(route, { runs: status === 'hitl_pending' ? [run()] : [] });
    if (path === '/systems') return json(route, { systems: [system()] });
    if (path === `/systems/${systemId}`) return json(route, system());
    if (path === `/systems/${systemId}/flow-state`) return json(route, state());
    if (path === `/systems/${systemId}/flow-manifest`) return json(route, { system_id: systemId, flow_sha256: hash, runtime_mode: 'dag_strict', unit_catalog: [] });
    if (path === `/systems/${systemId}/validate-flow`) return json(route, { valid: true, issues: [], runtime_mode: 'dag_strict', flow_sha256: hash });
    if (path === `/systems/${systemId}/flow-draft` && req.method() === 'PUT') { graph = req.postDataJSON().flow_definition; drafts.push(graph); revision++; return json(route, { ...state().draft, no_op: false }); }
    if (path === `/systems/${systemId}/flow-draft/test-runs` || path === `/systems/${systemId}/trigger`) return json(route, run());
    if (path === `/runs/${runId}`) return json(route, run());
    if (path === `/runs/${runId}/stream`) return route.fulfill({ contentType: 'text/event-stream', body: `event: ${status === 'hitl_pending' ? 'hitl_pause' : 'run_end'}\ndata: ${JSON.stringify({ node_id: 'review', status })}\n\n` });
    if (path === `/runs/${runId}/hitl`) { approvals.push(req.postDataJSON()); status = req.postDataJSON().action === 'accept' ? 'completed' : 'cancelled'; return json(route, {id:runId,status,decision:{id:decisionId,status:req.postDataJSON().action === 'accept' ? 'accepted' : 'rejected'},resume_task_id:'resume-1'}); }
    if (path === '/datasets') return json(route, { datasets: [], feature: { enabled: true } });
    if (path === '/skills') return json(route, { skills: [] });
    if (path === '/connectors') return json(route, { connectors: [] });
    if (path === '/capabilities') return json(route, { capabilities: [] });
    return json(route, {});
  });
  return { posts, approvals, draft: () => drafts.at(-1) };
}
async function openGate(page: Page, locale: string) {
  await page.goto(`/systems/${systemId}/flow?lens=build`);
  await page.getByRole('button', { name: locale === 'fr' ? 'Exploiter' : 'Operate', exact: true }).click();
  await page.getByRole('button', { name: locale === 'fr' ? 'Exécuter sur le serveur' : 'Execute on backend', exact: true }).click();
  await page.getByRole('dialog').locator('button.is-primary').click();
  await expect(page.getByTestId('retraining-context')).toBeVisible();
}

test.describe('Scheduled monitoring and human retraining approval', () => {
  test.beforeEach(async ({}, info) => { test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.'); });
  for (const locale of ['fr', 'en']) {
    test(`${locale}: configure with empty live window and inspect frozen proposal`, async ({ page }, info) => {
      const api = await setup(page, locale); await page.goto(`/models/${model.id}?facet=monitor`);
      const panel = page.getByTestId('scheduled-monitoring'); await expect(panel).toBeVisible();
      await panel.getByTestId('monitoring-enabled').check(); await panel.getByTestId('monitoring-propose').check(); await panel.getByTestId('monitoring-interval').selectOption('360'); await panel.getByTestId('monitoring-save').click();
      await expect.poll(() => api.posts).toEqual([{ enabled: true, propose_retraining: true, interval_minutes: 360 }]);
      await expect(panel.getByTestId('monitoring-state')).toContainText(locale === 'fr' ? 'activé pour cette version' : 'enabled for this version');
      await expect(panel.getByTestId('monitoring-history')).toContainText(locale === 'fr' ? 'davantage d’appels' : 'More calls');
      await expect(panel.getByTestId('monitoring-flow')).toHaveAttribute('href', /systems\/monitoring-flow\/flow/);
      await expect(panel.getByTestId('proposal-run')).toHaveAttribute('href', /runs\/retraining-run/);
      await expect(panel.getByTestId('proposal-model')).toHaveAttribute('href', /models\/new-challenger/);
      await panel.locator('summary').click(); const context = panel.getByTestId('retraining-context');
      await expect(context).toContainText(hash); await expect(context).toContainText('feedback-v2 · v2'); await expect(context.getByTestId('drift-tests')).toContainText('800');
      await expect(context).toContainText('Ticket outcome · v1'); await expect(context).toContainText('90'); await panel.screenshot({ path: info.outputPath(`monitoring-${locale}.png`) });
    });
    test(`${locale}: a scheduled proposal opens its existing Run and can be approved`, async ({ page }) => {
      const api = await setup(page, locale); await page.goto(`/models/${model.id}?facet=monitor`);
      await page.getByTestId('proposal-run').click();
      const gate = page.getByTestId('run-retraining-approval'); await expect(gate.getByTestId('retraining-context')).toContainText(hash);
      await gate.getByRole('button', {name:locale === 'fr' ? 'Approuver' : 'Approve',exact:true}).click();
      await expect.poll(() => api.approvals).toEqual([{action:'accept',expected_decision_id:decisionId}]);
      await expect(gate).toHaveCount(0);
    });
    test(`${locale}: Flow shows frozen context and sends one existing human approval`, async ({ page }) => {
      const api = await setup(page, locale); await openGate(page, locale);
      const context = page.getByTestId('retraining-context'); await expect(context).toContainText('Ticket outcome · v1'); await expect(context).toContainText(hash);
      await expect(context.getByRole('checkbox')).toHaveCount(0);
      await page.locator('app-flow-terminal').getByRole('button', { name: locale === 'fr' ? 'Approuver' : 'Approve', exact: true }).click();
      await expect.poll(() => api.approvals).toEqual([{ action: 'accept', expected_decision_id: decisionId }]);
    });
  }
  test('a Run projection without decision authority exposes context only', async ({ page }) => {
    const api = await setup(page, 'en', {cannotDecide:true}); await page.goto(`/runs/${runId}`);
    const gate = page.getByTestId('run-retraining-approval'); await expect(gate.getByTestId('retraining-context')).toContainText(hash);
    await expect(gate.getByRole('button', {name:'Approve',exact:true})).toHaveCount(0);
    await expect(gate.getByRole('button', {name:'Reject',exact:true})).toHaveCount(0);
    expect(api.approvals).toHaveLength(0);
  });
  test('server refusal keeps canonical policy disabled', async ({ page }) => {
    const api = await setup(page, 'en', { forbidden: true }); await page.goto(`/models/${model.id}?facet=monitor`);
    await page.getByTestId('monitoring-enabled').check(); await page.getByTestId('monitoring-save').click();
    await expect(page.getByTestId('scheduled-monitoring').getByRole('alert')).toContainText('You cannot change this schedule');
    await expect(page.getByTestId('monitoring-state')).toContainText('disabled'); await expect(page.getByTestId('monitoring-enabled')).toBeDisabled(); expect(api.posts).toHaveLength(1);
  });
  test('read-only authority prevents policy submission', async ({ page }) => {
    const api = await setup(page, 'en', { readOnly: true }); await page.goto(`/models/${model.id}?facet=monitor`);
    await expect(page.getByTestId('monitoring-enabled')).toBeDisabled(); await expect(page.getByTestId('monitoring-save')).toHaveCount(0); expect(api.posts).toHaveLength(0);
  });
  test('operator inbox shares proposal context and canonical approval', async ({ page }) => {
    const api = await setup(page, 'en'); await page.goto('/work/retraining/validations'); await page.getByRole('button', { name: 'Review request', exact: true }).click();
    await expect(page.getByTestId('retraining-context')).toContainText(hash); await page.locator('.xp-work-hitl-actions button').first().click();
    await expect.poll(() => api.approvals).toEqual([{ action: 'accept', note: '', expected_decision_id: decisionId }]);
  });
  test('missing proposal context disables acceptance but permits rejection', async ({ page }) => {
    const api = await setup(page, 'en', { missingContext: true }); await openGate(page, 'en');
    const terminal = page.locator('app-flow-terminal'); await expect(terminal.getByRole('button', { name: 'Approve', exact: true })).toBeDisabled();
    await terminal.getByRole('button', { name: 'Reject', exact: true }).click(); await expect.poll(() => api.approvals).toEqual([{ action: 'reject', expected_decision_id: decisionId }]);
  });
  test('strict imported Flow retains proposal mapping and offers the derived HITL output', async ({ page }) => {
    const api = await setup(page, 'en'); await page.goto(`/systems/${systemId}/flow?lens=build`);
    await page.locator('app-flow-node').filter({ hasText: 'Train challenger' }).click();
    const field = page.locator('app-manifest-fields #mf-proposal_id'); await expect(field).toHaveValue('review\u0001proposal_id');
    await field.selectOption({ label: 'Monitor model · proposal_id · string' }); await field.selectOption({ label: 'Approve retraining · proposal_id · string' });
    await expect.poll(() => api.draft()?.nodes.find((n: any) => n.id === 'train')?.config.inputs_map).toEqual({ proposal_id: { node_id: 'review', path: ['proposal_id'] } });
    expect(api.draft().nodes.find((n: any) => n.id === 'review').outputs).toContainEqual({ name: 'proposal_id', schema: 'string' });
    await page.reload(); await page.locator('app-flow-node').filter({ hasText: 'Train challenger' }).click(); await expect(field).toHaveValue('review\u0001proposal_id');
  });
});
