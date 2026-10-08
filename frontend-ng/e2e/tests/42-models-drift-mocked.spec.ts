import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page, type Route } from '@playwright/test';

test.use({ serviceWorkers: 'block', video: 'off', viewport: { width: 1440, height: 1000 } });
const catalog = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/ml-forecast.json'), 'utf8')).catalog;
const workspace = { id: 'drift-qa', slug: 'drift-qa', name: 'Drift QA', role: 'owner', role_template: 'workspace_owner', settings: {}, mode: 'builder' };
const model = { id: 'drift-v2', name: 'Sales amount', slug: 'sales-amount', version: 2,
  task: 'regression', family: 'tabular', algo: 'gradient_boosting', target: 'sales', features: ['amount', 'segment'],
  status: 'ready', is_champion: true, dataset_id: 'reference', dataset_slug: 'reference', row_count: 800,
  test_size: 0.25, cross_validation: 0, primary_metric: { key: 'r2', value: 0.8 },
  metrics: { scores: [{ key: 'r2', value: 0.8 }] }, params: { knobs: {} }, spec: {},
  signature: { inputs: [{ name: 'amount', type: 'double' }, { name: 'segment', type: 'string' }], outputs: [{ name: 'prediction', type: 'double' }] },
};

function monitoring(unavailable: boolean) {
  const distribution = { method: 'ks', status: 'alert', statistic: 0.62, p_value: 1e-12, p_value_adjusted: 2e-12,
    n_reference: 512, n_current: 240, reason: null };
  return { badge: 'alert', window: { predictions: 240, labeled: 20, limit: 1000, model_id: model.id, served_version: 2 },
    data_drift: { status: 'alert', features: unavailable ? [
      { name: 'legacy', kind: 'number', value: 0.05, status: 'ok' },
      { name: 'rare_segment', kind: 'category', value: 0.12, status: 'watch', psi_status: 'watch',
        test: { ...distribution, method: 'chi2', status: 'unknown', statistic: null, p_value: null,
          p_value_adjusted: null, n_reference: 40, n_current: 5, reason: 'sparse_categories' } },
    ] : [
      { name: 'amount', kind: 'number', value: 0.03, status: 'alert', psi_status: 'ok', test: distribution },
      { name: 'segment', kind: 'category', value: 0.3, status: 'alert', psi_status: 'alert',
        test: { ...distribution, method: 'chi2', status: 'ok', statistic: 1.6, p_value: 0.2, p_value_adjusted: 0.4 } },
    ] },
    score_drift: { status: 'ok', value: 0.02, served_mean: 4, reference_mean: 4.1, n: 240 },
    concept_drift: { status: 'unknown', rolling_auc: null, train_auc: null, delta: null, labeled: 20 },
  };
}

async function setup(page: Page, locale: string, unavailable: boolean, delayInitial = false) {
  let releaseInitial!: () => void, initialRequested = false;
  const initialWait = new Promise<void>(resolve => { releaseInitial = resolve; });
  const later = { ...model, id: 'drift-v3', version: 3, is_champion: false };
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.addInitScript(({ slug, locale }) => {
    localStorage.setItem('agentium_token', 'Bearer drift-qa'); localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_theme', locale === 'fr' ? 'dark' : 'light'); localStorage.setItem('agentium_locale', locale);
  }, { slug: workspace.slug, locale });
  const json = (route: Route, body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa', role: 'admin', email: 'qa@example.test' });
    if (path === '/auth/me') return json(route, { id: 'qa', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === `/auth/workspaces/${workspace.slug}`) return json(route, workspace);
    if (path === '/ml-models/catalog') return json(route, { catalog });
    if (path === '/ml-models') return json(route, { models: [model], catalog });
    if (path === `/ml-models/${model.id}` || path === `/ml-models/${later.id}`) return json(route, { model: path.endsWith(later.id) ? later : model, dataset: null, versions: delayInitial ? [model, later] : [model], challenger_id: null, catalog,
      serving: { enabled: true, callable: true, serving_model_id: model.id, serving_version: 2, fields: [], classes: [], keys: [] } });
    if (path === `/ml-models/${model.id}/monitoring`) {
      initialRequested = true;
      if (delayInitial) await initialWait;
      return json(route, { monitoring: monitoring(unavailable) });
    }
    if (path === `/ml-models/${later.id}/monitoring`) {
      const report = monitoring(false); report.window.model_id = later.id; report.window.served_version = later.version;
      report.data_drift.features[0].name = 'later_amount';
      return json(route, { monitoring: report });
    }
    if (path === '/datasets') return json(route, { datasets: [], feature: { enabled: true } });
    return json(route, {});
  });
  return { releaseInitial, initialRequested: () => initialRequested };
}

test.describe('Statistical monitoring evidence', () => {
  test.beforeEach(async ({}, info) => { test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.'); });
  for (const locale of ['fr', 'en']) {
    test(`${locale}: measured KS and chi2 keep corrected significance separate from PSI`, async ({ page }, info) => {
      await setup(page, locale, false);
      await page.goto(`/models/${model.id}?facet=monitor`);
      const panel = page.getByTestId('monitor-panel'), table = page.getByTestId('drift-tests');
      await expect(panel).toContainText(locale === 'fr' ? 'Version observée : v2' : 'Observed version: v2');
      await expect(panel).toContainText(locale === 'fr' ? 'Écart de répartition (PSI)' : 'Distribution difference (PSI)');
      await expect(table).toContainText('Holm');
      const amount = table.locator('[data-feature="amount"]');
      await expect(amount).toHaveAttribute('data-status', 'alert');
      await expect(amount).toContainText('Kolmogorov–Smirnov');
      await expect(amount.locator('[data-adjusted-p]')).toHaveText('2E-12');
      await expect(amount.locator('[data-reference-n]')).toHaveText('512');
      await expect(amount.locator('[data-current-n]')).toHaveText('240');
      const category = table.locator('[data-feature="segment"]');
      await expect(category).toHaveAttribute('data-status', 'ok');
      await expect(category).toContainText('Chi²');
      await expect(category.locator('[data-adjusted-p]')).toHaveText(locale === 'fr' ? '0,4' : '0.4');
      await table.screenshot({ path: info.outputPath(`drift-${locale}.png`) });
    });
    test(`${locale}: old references and sparse categories explain unavailable tests`, async ({ page }) => {
      await setup(page, locale, true);
      await page.goto(`/models/${model.id}?facet=monitor`);
      const table = page.getByTestId('drift-tests');
      const legacy = table.locator('[data-feature="legacy"]');
      await expect(legacy).toHaveAttribute('data-status', 'unknown');
      await expect(legacy).toContainText(locale === 'fr' ? 'Référence absente' : 'No reference is available');
      await expect(legacy.locator('[data-adjusted-p]')).toHaveText('—');
      await expect(legacy.locator('[data-reference-n]')).toHaveText('—');
      const sparse = table.locator('[data-feature="rare_segment"]');
      await expect(sparse).toHaveAttribute('data-status', 'unknown');
      await expect(sparse).toContainText(locale === 'fr' ? 'Effectifs trop faibles' : 'too few values');
      await expect(sparse.locator('[data-current-n]')).toHaveText('5');
      await expect(sparse.locator('[data-adjusted-p]')).toHaveText('—');
    });
  }
  test('a delayed monitoring response cannot overwrite the version opened next', async ({ page }) => {
    const api = await setup(page, 'en', false, true);
    await page.goto(`/models/${model.id}?facet=versions`);
    await expect.poll(() => api.initialRequested()).toBe(true);
    await page.locator('a[href*="/models/drift-v3"]').first().click();
    await expect(page).toHaveURL(/drift-v3/);
    await page.getByRole('tab', { name: 'Monitoring', exact: true }).click();
    const panel = page.getByTestId('monitor-panel');
    await expect(panel).toContainText('Observed version: v3');
    await expect(panel.locator('[data-feature="later_amount"]')).toBeVisible();
    const completed = page.waitForResponse(response => response.url().endsWith(`/ml-models/${model.id}/monitoring`));
    api.releaseInitial(); await completed;
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    await expect(panel).toContainText('Observed version: v3');
    await expect(panel.locator('[data-feature="later_amount"]')).toBeVisible();
  });
});
