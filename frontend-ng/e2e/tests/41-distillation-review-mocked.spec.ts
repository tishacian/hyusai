import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page, type Route } from '@playwright/test';

test.use({ serviceWorkers: 'block', video: 'off', viewport: { width: 1440, height: 1000 } });
const workspace = { id: 'distillation-qa', slug: 'distillation-qa', name: 'Distillation QA', role: 'owner', role_template: 'workspace_owner', settings: { features: { experience_v1: true } }, mode: 'builder' };
const systemId = 'distillation-system', runId = 'label-run', decisionId = 'label-decision', hash = '5'.repeat(64);
const catalog = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/ml-forecast.json'), 'utf8')).catalog;
catalog.families.find((family: any) => family.key === 'tabular').spec_fields = [{ key: 'distillation_inference_cost_per_1000', kind: 'float', required: false, min: 0, max: 1000, when: { task: ['classification'] } }];
const columns = [{ name: 'message', kind: 'string', dtype: 'String' }, { name: 'label', kind: 'string', dtype: 'String' }];
const source = { id: 'llm-labels', name: 'LLM labels', slug: 'llm-labels', version: 1, source: 'generated', status: 'ready', row_count: 51, column_count: 2, schema: columns, parent_ids: [], run_id: runId, system_id: systemId, lineage: { labeling: { review_status: 'unreviewed', label_column: 'label', labels: ['billing', 'technical'], text_columns: ['message'] } }, preview: [{ message: 'Ticket 0', label: 'billing' }] };
const reviewed = { ...source, id: 'reviewed-labels', name: 'Reviewed labels', slug: 'reviewed-labels', produced_by: 'llm_label_review_v1', parent_ids: [source.id], lineage: { labeling: { ...source.lineage.labeling, review_status: 'reviewed' }, label_review: { decision_id: decisionId, source_dataset_id: source.id, source_version: 1, source_sha256: hash, rows_reviewed: 51, corrected_rows: 2, reviewed_by: 'qa', reviewed_at: '2026-10-08T10:00:00Z', label_column: 'label', labels: ['billing', 'technical'] } }, preview: [{ message: 'Ticket 0', label: 'technical' }] };
const evidence = { version: 1, evaluation: 'held_out', test_rows: 13, rows_reviewed: 51, corrected_rows: 2, agreement: 0.84, reviewed_accuracy: 0.92, teacher_accuracy_on_reviewed: 0.85, source_dataset_id: source.id, source_version: 1, reviewed_dataset_id: reviewed.id, decision_id: decisionId, teacher_model: { provider: 'openai', model: 'workspace-model' }, llm_estimated_cost_per_1000: 0.42, llm_cost_basis: 'declared_tariff', llm_labeled_rows: 51, unknown_attempts: 0, inference_cost_per_1000: null, inference_cost_basis: 'unavailable' };
const model = { id: 'distilled-model', name: 'Ticket classifier', slug: 'ticket-classifier', version: 1, task: 'classification', family: 'tabular', algo: 'gradient_boosting', target: 'label', features: ['message'], status: 'ready', is_champion: true, dataset_id: reviewed.id, dataset_slug: reviewed.slug, row_count: 51, test_size: 0.25, cross_validation: 0, primary_metric: { key: 'accuracy', value: 0.92 }, metrics: { primary: { key: 'accuracy', value: 0.92 }, scores: [{ key: 'accuracy', value: 0.92 }], distillation: evidence }, signature: { inputs: [{ name: 'message', type: 'string' }], outputs: [{ name: 'prediction', type: 'string' }] }, classes: ['billing', 'technical'], input_example: [], params: { knobs: {} }, spec: {} };

async function setup(page: Page, locale: string, failReview = false, strict = false) {
  let graph: any = {
    schema_version: 3, source: 'flow', io_mode: 'overlay', nodes: [
      { id: 'source', type: 'source', kind: 'source', label: 'Tickets', position: { x: 0, y: 120 }, config: { ingress: { kind: 'manual' }, input_schema: { type: 'object', properties: {} } } },
      { id: 'label', type: 'skill', kind: 'task', label: 'Label tickets', position: { x: 260, y: 120 }, config: { skill_slug: 'llm_label_dataset_v1', runtime_ref: 'skill:llm_label_dataset_v1', params: { text_columns: ['message'], labels: ['billing', 'technical'], instruction: 'Classify by topic', input_cost_per_million: 0.5, output_cost_per_million: 1 } } },
      { id: 'review', type: 'hitl', kind: 'hitl', label: 'Review labels', position: { x: 520, y: 120 }, config: { prompt: 'Review ticket labels', prompt_kind: 'review_dataset_labels' } },
      { id: 'train', type: 'skill', kind: 'task', label: 'Train classifier', position: { x: 780, y: 120 }, config: { skill_slug: 'ml_train_sklearn_v1', runtime_ref: 'skill:ml_train_sklearn_v1', params: { task: 'classification', target: 'label', features: ['message'], algo: 'gradient_boosting', spec: {} } } },
      { id: 'sink', type: 'sink', kind: 'sink', label: 'Model output', position: { x: 1040, y: 120 }, config: {} },
    ], edges: ['source', 'label', 'review', 'train'].map((from, i) => ({ id: `edge-${i}`, from, to: ['label', 'review', 'train', 'sink'][i], kind: 'data' })),
  };
  if (strict) {
    graph.io_mode = 'strict';
    for (const id of ['source', 'label']) graph.nodes.find((node: any) => node.id === id).outputs = [{ name: 'dataset_id', schema: 'string' }];
    for (const id of ['label', 'train']) graph.nodes.find((node: any) => node.id === id).inputs = [{ name: 'dataset_id', schema: 'string' }];
    graph.nodes[1].config.inputs_map = { dataset_id: { node_id: 'source', path: ['dataset_id'] } };
    // Existing saved approval-only declarations must be upgraded on load.
    graph.nodes[2].outputs = [{ name: 'approved', schema: 'boolean' }, { name: 'decision_id', schema: 'string' }];
    graph.nodes[3].outputs = [{ name: 'model_id', schema: 'string' }];
    graph.nodes[4].inputs = [{ name: 'model_id', schema: 'string' }];
    graph.nodes[4].config.inputs_map = { model_id: { node_id: 'train', path: ['model_id'] } };
  }
  let status = 'hitl_pending', revision = 1;
  const approvals: any[] = [], drafts: any[] = [], plans: any[] = [], trains: any[] = [];
  const run = () => ({ id: runId, system_id: systemId, status, flow_sha256: hash, input_ref: {}, output_ref: status === 'completed' ? { dataset_id: reviewed.id, model_id: model.id } : {}, skill_invocations: [], checkpoints: [], hitl: status === 'hitl_pending' ? { node_id: 'review', prompt: 'Review ticket labels', prompt_kind: 'review_dataset_labels', decision_id: decisionId, decision_status: 'proposed', label_review: { dataset_id: source.id, sha256: hash }, upstream: { dataset_id: source.id } } : undefined });
  const system = () => ({ id: systemId, name: 'Distillation', status: 'active', workspace_id: workspace.id, flow_definition: graph, flow_sha256: hash });
  const state = () => ({ system_id: systemId, status: 'active', draft: { revision, base_published_version_id: 'published-v1', flow_sha256: hash, flow_definition: graph }, published: { version_id: 'published-v1', version_number: 1, flow_sha256: hash, flow_definition: graph, execution_contract_ready: true } });
  const json = (route: Route, body: unknown, code = 200) => route.fulfill({ status: code, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.addInitScript(({ slug, locale }) => {
    localStorage.setItem('agentium_token', 'Bearer label-qa'); localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_theme', locale === 'fr' ? 'dark' : 'light'); localStorage.setItem('agentium_locale', locale);
  }, { slug: workspace.slug, locale });
  await page.route('**/api/v1/**', async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa', role: 'admin', email: 'qa@example.test' });
    if (path === '/auth/me') return json(route, { id: 'qa', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === `/auth/workspaces/${workspace.slug}`) return json(route, workspace);
    if (path === '/work/label-review') return json(route, {
      experience: { id: 'label-app', slug: 'label-review', name: 'Review labels', pattern: 'approval', languages: ['fr', 'en'] }, channel: 'live',
      release: { id: 'release-label', release_number: 1, renderer_version: 'certified-components-0.2.0', bindings_snapshot: [{ system_id: systemId }], pages: { pages: [{ id: 'home', title: 'Labels', components: [] }] }, languages: ['fr', 'en'] },
    });
    if (path === '/work/label-review/validations') return json(route, { runs: status === 'hitl_pending' ? [run()] : [] });
    if (path === '/systems') return json(route, { systems: [system()] });
    if (path === `/systems/${systemId}`) return json(route, system());
    if (path === `/systems/${systemId}/flow-state`) return json(route, state());
    if (path === `/systems/${systemId}/flow-manifest`) return json(route, { system_id: systemId, flow_sha256: hash, runtime_mode: strict ? 'dag_strict' : 'dag_overlay', unit_catalog: [] });
    if (path === `/systems/${systemId}/validate-flow`) return json(route, { valid: true, issues: [], runtime_mode: strict ? 'dag_strict' : 'dag_overlay', flow_sha256: hash });
    if (path === `/systems/${systemId}/flow-draft` && req.method() === 'PUT') { graph = req.postDataJSON().flow_definition; drafts.push(graph); revision++; return json(route, { ...state().draft, no_op: false }); }
    if (path === `/systems/${systemId}/flow-draft/test-runs` || path === `/systems/${systemId}/trigger`) return json(route, run());
    if (path === `/runs/${runId}`) return json(route, run());
    if (path === `/runs/${runId}/stream`) return route.fulfill({ contentType: 'text/event-stream', body: `event: ${status === 'hitl_pending' ? 'hitl_pause' : 'run_end'}\ndata: ${JSON.stringify({ node_id: 'review', status })}\n\n` });
    if (path === `/runs/${runId}/label-review`) {
      expect(url.searchParams.get('expected_decision_id')).toBe(decisionId);
      if (failReview) return json(route, { detail: { code: 'LABEL_REVIEW_STALE' } }, 409);
      const offset = Number(url.searchParams.get('offset') || 0), count = Math.min(50, 51 - offset);
      return json(route, { decision_id: decisionId, dataset_id: source.id, dataset_name: source.name, source_version: 1, sha256: hash, label_column: 'label', labels: ['billing', 'technical'], text_columns: ['message'], total: 51, offset, rows: Array.from({ length: count }, (_, index) => ({ row_id: index + offset, values: { message: `Ticket ${index + offset}` }, label: 'billing' })) });
    }
    if (path === `/runs/${runId}/hitl`) { approvals.push(req.postDataJSON()); status = req.postDataJSON().action === 'accept' ? 'completed' : 'cancelled'; return json(route, run()); }
    if (path === '/datasets') return json(route, { datasets: [reviewed], feature: { enabled: true } });
    if (path === `/datasets/${reviewed.id}`) return json(route, { dataset: reviewed, lineage: { parents: [source], children: [] }, versions: [reviewed], feature: { enabled: true } });
    if (path === `/datasets/${reviewed.id}/preview`) return json(route, { dataset_id: reviewed.id, schema: columns, rows: reviewed.preview, total: 51, offset: 0, limit: 50 });
    if (path === '/ml-models/catalog') return json(route, { catalog });
    if (path === `/ml-models/${model.id}`) return json(route, { model, dataset: reviewed, versions: [model], provenance: null, challenger_id: null, catalog, serving: { enabled: true, callable: true, serving_model_id: model.id, serving_version: 1, fields: [], classes: model.classes, keys: [] } });
    if (path === '/ml-models/plan') { const body = req.postDataJSON(); plans.push(body); return json(route, { dataset: reviewed, columns: columns.map(column => ({ ...column, distinct: column.name === 'label' ? 2 : 51, nulls: 0, role: column.name === 'message' ? 'text' : undefined, suggested_task: 'classification' })), catalog, refusal: null, plan: { task: 'classification', family: 'tabular', target: 'label', features: ['message'], algo: 'gradient_boosting', knobs: {}, spec: body.spec || {}, test_size: 0.25, cross_validation: 0, rows: 51, warnings: [] } }); }
    if (path === '/ml-models' && req.method() === 'POST') { trains.push(req.postDataJSON()); return json(route, { model }); }
    if (path === '/ml-models') return json(route, { models: [model], catalog });
    if (path === '/skills') return json(route, { skills: [] });
    if (path === '/connectors') return json(route, { connectors: [] });
    if (path === '/documents/collections') return json(route, { collections: [] });
    if (path === '/capabilities') return json(route, { capabilities: [] });
    return json(route, {});
  });
  return { approvals, plans, trains, draft: () => drafts.at(-1), params: () => drafts.at(-1)?.nodes.find((node: any) => node.id === 'train')?.config.params };
}

async function openGate(page: Page, locale: string) {
  await page.goto(`/systems/${systemId}/flow?lens=build`);
  await page.getByRole('button', { name: locale === 'fr' ? 'Exploiter' : 'Operate', exact: true }).click();
  await page.getByRole('button', { name: locale === 'fr' ? 'Exécuter sur le serveur' : 'Execute on backend', exact: true }).click();
  await page.getByRole('dialog').locator('button.is-primary').click();
  await expect(page.getByTestId('dataset-label-review')).toBeVisible();
}

test.describe('Distillation · one human gate', () => {
  test.beforeEach(async ({}, info) => { test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.'); });
  for (const locale of ['fr', 'en']) {
    test(`${locale}: Flow review preserves corrections across pages and exposes honest model evidence`, async ({ page }, info) => {
      const api = await setup(page, locale);
      await openGate(page, locale);
      const review = page.getByTestId('dataset-label-review');
      const accept = page.locator('app-flow-terminal').getByRole('button', { name: locale === 'fr' ? 'Approuver' : 'Approve', exact: true });
      await expect(accept).toBeDisabled();
      await review.locator('[data-row-id="0"] select').selectOption('technical');
      await review.getByTestId('label-review-next').click();
      await review.locator('[data-row-id="50"] select').selectOption('technical');
      await review.getByTestId('label-review-prev').click();
      await expect(review.locator('[data-row-id="0"] select')).toHaveValue('technical');
      await review.getByTestId('label-review-ack').check();
      await expect(accept).toBeEnabled();
      await page.screenshot({ path: info.outputPath(`review-${locale}.png`) });
      await accept.click();
      await expect.poll(() => api.approvals.length).toBe(1);
      expect(api.approvals[0]).toEqual({ action: 'accept', expected_decision_id: decisionId, label_review: { dataset_id: source.id, sha256: hash, acknowledged: true, corrections: [{ row_id: 0, label: 'technical' }, { row_id: 50, label: 'technical' }] } });
      await expect(review).toHaveCount(0);
      await page.goto(`/data/${reviewed.id}`);
      await expect(page.getByTestId('dataset-labeling-provenance')).toContainText(locale === 'fr' ? '51 lignes confirmées, 2 classes corrigées' : '51 rows confirmed, 2 classes corrected');
      await page.goto(`/models/${model.id}`);
      const card = page.getByTestId('distillation-evidence');
      await expect(card).toContainText(locale === 'fr' ? '13 lignes de test' : '13 test rows');
      await expect(card.getByTestId('distillation-model-cost')).toHaveText(locale === 'fr' ? 'Indisponible' : 'Unavailable');
      await expect(card.getByTestId('distillation-agreement')).toContainText('84');
      await card.screenshot({ path: info.outputPath(`distillation-${locale}.png`) });
      await page.getByRole('button', { name: locale === 'fr' ? 'Réentraîner' : 'Retrain', exact: true }).click();
      const workshop = page.getByRole('dialog');
      await workshop.getByTestId('tabular-options').locator('summary').click();
      const price = workshop.locator('#tabular-distillation_inference_cost_per_1000');
      await expect(price).toHaveValue(''); await price.fill('0'); await price.press('Tab');
      await workshop.locator('.ck-submit').click();
      await expect.poll(() => api.trains.at(-1)?.spec).toEqual({ distillation_inference_cost_per_1000: 0 });
    });
  }
  test('a stale review disables approval while rejection uses the existing gate without corrections', async ({ page }) => {
    const api = await setup(page, 'en', true); await openGate(page, 'en');
    await expect(page.getByTestId('dataset-label-review')).toContainText('This review is unavailable or has changed');
    const terminal = page.locator('app-flow-terminal');
    await expect(terminal.getByRole('button', { name: 'Approve', exact: true })).toBeDisabled();
    await terminal.getByRole('button', { name: 'Reject', exact: true }).click();
    await expect.poll(() => api.approvals.length).toBe(1);
    expect(api.approvals[0]).toEqual({ action: 'reject', expected_decision_id: decisionId });
  });
  test('operator inbox reuses the same review and sends one canonical approval', async ({ page }) => {
    const api = await setup(page, 'en');
    await page.goto('/work/label-review/validations');
    await page.getByRole('button', { name: 'Review request', exact: true }).click();
    const review = page.getByTestId('dataset-label-review');
    await expect(review).toBeVisible();
    const accept = page.locator('.xp-work-hitl-actions button').first();
    await expect(accept).toBeDisabled();
    await review.locator('[data-row-id="0"] select').selectOption('technical');
    await review.getByTestId('label-review-ack').check();
    await accept.click();
    await expect.poll(() => api.approvals.length).toBe(1);
    expect(api.approvals[0]).toEqual({ action: 'accept', note: '', expected_decision_id: decisionId, label_review: { dataset_id: source.id, sha256: hash, acknowledged: true, corrections: [{ row_id: 0, label: 'technical' }] } });
  });

  test('strict Flow exposes, saves and reloads reviewed dataset bindings from legacy HITL ports', async ({ page }) => {
    const api = await setup(page, 'en', false, true);
    await page.goto(`/systems/${systemId}/flow?lens=build`);
    await page.locator('app-flow-node').filter({ hasText: 'Review labels' }).click();
    const fields = page.locator('app-manifest-fields');
    await fields.locator('#mf-dataset_id').selectOption({ label: 'Label tickets · dataset_id · string' });
    const kind = page.locator('app-flow-inspector select').filter({ has: page.locator('option[value="review_dataset_labels"]') });
    await kind.selectOption('approve_write');
    // Changing the verdict kind must preserve the context already wired in.
    await expect(fields.locator('#mf-dataset_id')).toHaveValue('label\u0001dataset_id');
    await kind.selectOption('review_dataset_labels');
    await expect(fields.locator('#mf-dataset_id')).toHaveValue('label\u0001dataset_id');
    await page.locator('app-flow-node').filter({ hasText: 'Train classifier' }).click();
    await fields.locator('#mf-dataset_id').selectOption({ label: 'Review labels · dataset_id · string' });
    await expect.poll(() => api.draft()?.nodes.find((node: any) => node.id === 'train')?.config.inputs_map)
      .toEqual({ dataset_id: { node_id: 'review', path: ['dataset_id'] } });
    expect(api.draft().io_mode).toBe('strict');
    expect(api.draft().nodes.find((node: any) => node.id === 'review').outputs).toContainEqual({ name: 'dataset_id', schema: 'string' });
    await page.reload();
    await page.locator('app-flow-node').filter({ hasText: 'Train classifier' }).click();
    await expect(fields.locator('#mf-dataset_id')).toHaveValue('review\u0001dataset_id');
    await openGate(page, 'en');
    await page.getByTestId('label-review-ack').check();
    await page.locator('app-flow-terminal').getByRole('button', { name: 'Approve', exact: true }).click();
    await expect.poll(() => api.approvals.length).toBe(1);
    expect(api.approvals[0].label_review.acknowledged).toBe(true);
  });
});
