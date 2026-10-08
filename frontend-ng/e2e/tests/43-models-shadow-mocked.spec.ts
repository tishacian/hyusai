import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page, type Route } from '@playwright/test';

test.use({ serviceWorkers: 'block', video: 'off', viewport: { width: 1440, height: 1000 } });
const catalog = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/ml-forecast.json'), 'utf8')).catalog;
const workspace = { id: 'shadow-qa', slug: 'shadow-qa', name: 'Shadow QA', role: 'owner', role_template: 'workspace_owner', settings: {}, mode: 'builder' };
const baseModel = { id: 'served-v1', name: 'Ticket outcome', slug: 'ticket-outcome', version: 1,
  task: 'classification', family: 'tabular', algo: 'gradient_boosting', target: 'outcome', features: ['visits'],
  status: 'ready', is_champion: true, dataset_id: 'reference', dataset_slug: 'reference', row_count: 800,
  test_size: 0.25, cross_validation: 0, primary_metric: { key: 'accuracy', value: 0.8 },
  metrics: { scores: [{ key: 'accuracy', value: 0.8 }] }, params: { knobs: {} }, spec: {}, classes: ['yes', 'no'],
  signature: { inputs: [{ name: 'visits', type: 'double' }], outputs: [{ name: 'prediction', type: 'string' }] },
};

async function setup(page: Page, locale: string, options: { forbidden?: boolean; readOnly?: boolean; unsupported?: boolean; regression?: boolean } = {}) {
  const model = { ...baseModel, ...(options.unsupported ? { family: 'timeseries', task: 'forecasting' } : options.regression ? { task: 'regression' } : {}) };
  let config = { enabled: false, sample_percent: 10, timeout_s: 15 }, completed = false;
  const posts: any[] = [];
  const shadow = () => ({ supported: !options.unsupported, can_configure: !options.readOnly, config,
    challenger: { id: 'challenger-v2', version: 2 }, limits: { max_rows: 64, max_pending: 100, max_attempts: 2, window: 400 }, comparison_scope: 'current_pair',
    window: { jobs: completed ? 2 : 0, completed: completed ? 1 : 0, pending: 0, failed: completed ? 1 : 0, skipped: 0, compared_rows: completed ? 64 : 0, labeled_pairs: completed ? 1 : 0 },
    comparison: { agreement: completed ? 0 : null, mean_absolute_difference: completed ? 0 : null,
      champion_accuracy: completed ? 0 : null, challenger_accuracy: completed ? 1 : null, champion_mae: completed ? 0 : null, challenger_mae: null },
    latencies: { primary_ms: completed ? 0 : null, shadow_ms: completed ? 2 : null, shadow_load_ms: completed ? 15 : null, shadow_total_ms: completed ? 20 : null },
    recent: completed ? [{ prediction_id: 'primary-answer-kept', challenger_id: 'challenger-v2', version: 2, status: 'failed', error: 'ML_SHADOW_TIMEOUT', rows: 64, total_duration_ms: 30000, created_at: '2026-10-08T10:00:00Z' }] : [],
  });
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.addInitScript(({ slug, locale }) => {
    localStorage.setItem('agentium_token', 'Bearer shadow-qa'); localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_theme', locale === 'fr' ? 'dark' : 'light'); localStorage.setItem('agentium_locale', locale);
  }, { slug: workspace.slug, locale });
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa', role: 'admin', email: 'qa@example.test' });
    if (path === '/auth/me') return json(route, { id: 'qa', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === `/auth/workspaces/${workspace.slug}`) return json(route, workspace);
    if (path === '/ml-models/catalog') return json(route, { catalog });
    if (path === '/ml-models') return json(route, { models: [model], catalog });
    if (path === `/ml-models/${model.id}`) return json(route, { model, dataset: null, versions: [model], challenger_id: 'challenger-v2', catalog,
      serving: { enabled: true, callable: true, serving_model_id: model.id, serving_version: 1, fields: [], classes: model.classes, keys: [] } });
    if (path === `/ml-models/${model.id}/shadow`) {
      posts.push(route.request().postDataJSON());
      if (options.forbidden) return json(route, { detail: { code: 'ML_SHADOW_FORBIDDEN' } }, 403);
      config = posts.at(-1); return json(route, { shadow: shadow() });
    }
    if (path === `/ml-models/${model.id}/monitoring`) return json(route, { monitoring: {
      badge: null, window: { predictions: 0, labeled: 0, limit: 1000, model_id: model.id, served_version: 1 },
      data_drift: { status: 'unknown', features: [] }, score_drift: { status: 'unknown', value: null, served_mean: null, reference_mean: null, n: 0 },
      concept_drift: { status: 'unknown', rolling_auc: null, train_auc: null, delta: null, labeled: 0 }, shadow: shadow(),
    } });
    if (path === '/datasets') return json(route, { datasets: [], feature: { enabled: true } });
    return json(route, {});
  });
  return { posts, complete: () => { completed = true; } };
}

test.describe('Challenger shadow scoring', () => {
  test.beforeEach(async ({}, info) => { test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.'); });
  for (const locale of ['fr', 'en']) {
    test(`${locale}: enable on an empty window, then read paired evidence and worker failures`, async ({ page }, info) => {
      const api = await setup(page, locale); await page.goto('/models/served-v1?facet=monitor');
      const panel = page.getByTestId('shadow-panel');
      await expect(panel).toBeVisible(); await expect(panel).toContainText('64');
      await expect(panel.getByTestId('shadow-comparison')).toContainText(locale === 'fr' ? 'Indisponible' : 'Unavailable');
      await page.getByTestId('shadow-enabled').check();
      await page.getByTestId('shadow-sample').fill('25'); await page.getByTestId('shadow-timeout').fill('30');
      await page.getByTestId('shadow-save').click();
      await expect.poll(() => api.posts).toEqual([{ enabled: true, sample_percent: 25, timeout_s: 30 }]);
      await expect(panel.getByTestId('shadow-state')).toContainText(locale === 'fr' ? 'activé pour cette version' : 'enabled for this version');
      api.complete(); await page.getByTestId('shadow-refresh').click();
      await expect(panel.locator('[data-count="failed"]')).toHaveText('1');
      await expect(panel.locator('[data-metric="agreement"]')).toHaveText(/^0\s?%$/);
      await expect(panel.locator('[data-metric="primary-accuracy"]')).toHaveText(/^0\s?%$/);
      await expect(panel.locator('[data-metric="challenger-accuracy"]')).toHaveText(/^100\s?%$/);
      await expect(panel).toContainText(locale === 'fr' ? '1 paires ayant une même issue réelle' : '1 pairs that share a ground truth');
      await expect(panel).toContainText(locale === 'fr' ? 'dépassé le délai autorisé' : 'exceeded its time limit');
      await panel.screenshot({ path: info.outputPath(`shadow-${locale}.png`) });
    });
    test(`${locale}: a forbidden write keeps canonical scoring disabled`, async ({ page }) => {
      const api = await setup(page, locale, { forbidden: true }); await page.goto('/models/served-v1?facet=monitor');
      await page.getByTestId('shadow-enabled').check(); await page.getByTestId('shadow-save').click();
      await expect(page.getByTestId('shadow-panel').getByRole('alert')).toContainText(locale === 'fr' ? 'Vous ne pouvez pas modifier' : 'You cannot change');
      await expect(page.getByTestId('shadow-state')).toContainText(locale === 'fr' ? 'désactivé' : 'disabled');
      await expect(page.getByTestId('shadow-enabled')).toBeDisabled();
      expect(api.posts).toHaveLength(1);
    });
  }
  test('server read-only authority hides save even for an administrator-shaped client', async ({ page }) => {
    const api = await setup(page, 'en', { readOnly: true }); await page.goto('/models/served-v1?facet=monitor');
    await expect(page.getByTestId('shadow-enabled')).toBeDisabled(); await expect(page.getByTestId('shadow-save')).toHaveCount(0);
    expect(api.posts).toHaveLength(0);
  });
  test('time-series models explain unsupported scoring without an enable control', async ({ page }) => {
    await setup(page, 'en', { unsupported: true }); await page.goto('/models/served-v1?facet=monitor');
    await expect(page.getByTestId('shadow-unsupported')).toContainText('ready tabular classification or regression');
    await expect(page.getByTestId('shadow-enabled')).toHaveCount(0);
  });
  test('regression keeps a zero prediction difference distinct from unavailable challenger error', async ({ page }) => {
    const api = await setup(page, 'en', { regression: true }); api.complete(); await page.goto('/models/served-v1?facet=monitor');
    await expect(page.locator('[data-metric="difference"]')).toHaveText('0');
    await expect(page.locator('[data-metric="primary-mae"]')).toHaveText('0');
    await expect(page.locator('[data-metric="challenger-mae"]')).toHaveText('Unavailable');
  });
});
