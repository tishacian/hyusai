import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page, type Route } from '@playwright/test';

// M5: TreeSHAP on Play, the counterfactual panel, "In production" on Evidence
// and the fairness watch on Monitor. The production report reuses the
// training pack's error tree and group table from the shared fixture, because
// the server writes the production report in that same shape.
test.use({ serviceWorkers: 'block', video: 'off' });
const fixture = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/ml-tabular-extensions.json'), 'utf8'));
const catalog = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/ml-forecast.json'), 'utf8')).catalog;
const pack = fixture.explanation_metrics.explain;
const workspace = { id: 'm5-qa', slug: 'm5-qa', name: 'M5', role: 'owner', role_template: 'workspace_owner', settings: {}, mode: 'builder' };
const model = {
  id: 'm5-1', name: 'Churn', slug: 'churn', version: 1, family: 'tabular', task: 'classification', algo: 'random_forest',
  target: 'churn', features: ['visits', 'segment'], status: 'ready', is_champion: true, row_count: 800, test_size: 0.25,
  cross_validation: 0, primary_metric: { key: 'roc_auc', value: 0.8 }, metrics: { primary: { key: 'roc_auc', value: 0.8 }, scores: [{ key: 'roc_auc', value: 0.8 }] },
  input_example: [{ visits: 10, segment: 'Retail' }], classes: ['0', '1'], params: { knobs: {} }, spec: { fairness_columns: ['segment'] },
};
const fields = [
  { name: 'visits', type: 'double', kind: 'number', required: true, default: 10, min: 0, max: 40 },
  { name: 'segment', type: 'string', kind: 'category', required: true, default: 'Retail', choices: ['Retail', 'Business'] },
];
const limits = { min_rows: 50, max_rows: 5000, interval_minutes: 1440, watch_gap: 0.05, alert_gap: 0.1, min_group_rows: 30 };
const completed = {
  id: 'report-1', model_id: model.id, version: 1, trigger: 'scheduled', status: 'completed',
  window: { from: null, until: null }, counts: { labeled: 240, used: 180, excluded: { inputs_not_retained: 60 } },
  metrics: { accuracy: 0.81, rows: 180 },
  report: {
    error_measure: 'served_answer_vs_label', rows: 180, error_tree: pack.error_tree,
    fairness: { columns: pack.fairness, gaps: [{ column: 'segment', groups: 3, small_groups: 1, metric: 'equalized_odds_difference', gap: 0.4, badge: 'alert' }], badge: 'alert' },
  },
  fairness_badge: 'alert', error_code: null, created_at: '2026-10-17T08:00:00', completed_at: '2026-10-17T08:00:04',
};
const series = [
  { report_id: 'r0', at: '2026-10-15T08:00:00', badge: 'ok', gaps: [{ column: 'segment', metric: 'equalized_odds_difference', gap: 0.03 }] },
  { report_id: 'r1', at: '2026-10-16T08:00:00', badge: 'watch', gaps: [{ column: 'segment', metric: 'equalized_odds_difference', gap: 0.07 }] },
  { report_id: 'report-1', at: '2026-10-17T08:00:04', badge: 'alert', gaps: [{ column: 'segment', metric: 'equalized_odds_difference', gap: 0.4 }] },
];
const shap = {
  method: 'tree_shap', output_space: 'probability', estimator: 'RandomForestClassifier', class: '1', base: 0.3, output: 0.72,
  contributions: [{ field: 'visits', value: 3, contribution: 0.5 }, { field: 'segment', value: 'Retail', contribution: -0.12 }],
  other: { fields: 1, contribution: 0.04 }, additivity_gap: 0,
};

async function setup(page: Page, locale: string, theme: string) {
  const calls = { predict: [] as any[], counterfactual: [] as any[], runs: 0 };
  let latest: any = completed;
  await page.route('**/*', (route) => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.addInitScript(({ locale, theme }) => {
    localStorage.setItem('agentium_token', 'Bearer qa'); localStorage.setItem('agentium_workspace_slug', 'm5-qa');
    localStorage.setItem('agentium_locale', locale); localStorage.setItem('agentium_theme', theme);
  }, { locale, theme });
  await page.route('**/api/v1/**', (route: Route) => {
    const request = route.request(), path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    const json = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/auth/validate') return json({ valid: true, user_id: 'qa', role: 'admin', email: 'qa@example.test' });
    if (path === '/auth/me') return json({ id: 'qa', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json([workspace]);
    if (path.startsWith('/auth/workspaces/')) return json(workspace);
    if (path === '/ml-models/catalog') return json({ catalog });
    if (path === '/ml-models') return json({ models: [model], catalog });
    if (path === `/ml-models/${model.id}`) {
      return json({
        model, dataset: null, catalog, versions: [model], provenance: null, challenger_id: null,
        serving: {
          enabled: true, callable: true, serving_version: 1, serving_model_id: model.id, is_serving: true, max_rows: 100,
          fields, classes: ['0', '1'], positive_label: '1', predict_count: 4, last_predict_at: null, published_skill: null,
          keys: [], endpoint: `/api/v1/ml-models/${model.id}/predict`, key_header: 'X-API-Key',
          permissions: { read: true, predict: true, score: true, feedback: true, keys: false },
        },
      });
    }
    if (path === `/ml-models/${model.id}/monitoring`) {
      return json({ monitoring: { badge: null, window: { predictions: 4, labeled: 2, limit: 1000 }, data_drift: { status: 'insufficient', features: [] },
        score_drift: { status: 'insufficient', value: null, n: 4 }, concept_drift: { status: 'insufficient', labeled: 2 } } });
    }
    if (path === `/ml-models/${model.id}/production-debug` && request.method() === 'POST') {
      calls.runs++;
      latest = { ...completed, id: 'report-2', trigger: 'manual', status: 'queued', report: {}, counts: { labeled: 0, used: 0, excluded: {} }, metrics: {}, fairness_badge: null, completed_at: null };
      return json({ report: latest, supported: true, latest, series, fairness_columns: ['segment'], limits });
    }
    if (path === `/ml-models/${model.id}/production-debug`) {
      return json({ supported: true, latest, series, fairness_columns: ['segment'], limits });
    }
    if (path === `/ml-models/${model.id}/predict`) {
      calls.predict.push(request.postDataJSON());
      return json({ served: { model_id: model.id, version: 1 }, task: 'classification', target: 'churn', classes: ['0', '1'], positive_label: '1',
        rows: 1, duration_ms: 3, prediction_id: 'p-1',
        predictions: [{ prediction: '1', confidence: 0.72, score: 0.72, probabilities: [{ label: '0', value: 0.28 }, { label: '1', value: 0.72 }], explanation: shap }] });
    }
    if (path === `/ml-models/${model.id}/counterfactuals`) {
      calls.counterfactual.push(request.postDataJSON());
      return json({ status: 'found', task: 'classification', current: { prediction: '1', probability: 0.72 }, target: { class: '0' },
        results: [{ changes: [{ field: 'visits', from: 3, to: 18 }], changed_fields: 1, distance: 0.375, prediction: '0', probability: 0.66 }],
        refused: [], fields: [{ field: 'visits', candidates: 12 }], evaluated: 12, budget: 2000, exhausted: false });
    }
    return json({});
  });
  return calls;
}

for (const [locale, theme] of [['fr', 'dark'], ['en', 'light']] as const) {
  test.describe(`${theme}/${locale}: M5 explanations`, () => {
    test.beforeEach(() => {
      test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1', 'Mocked QA only');
    });

    test('Evidence shows where production goes wrong and starts an analysis', async ({ page }, info) => {
      await page.setViewportSize({ width: 1440, height: 1000 });
      const calls = await setup(page, locale, theme);
      await page.goto(`/models/${model.id}`);
      const section = page.getByTestId('production-debug');
      await expect(section.getByTestId('production-counts')).toContainText('180');
      await expect(section.getByTestId('production-counts')).toContainText('240');
      await expect(section.getByTestId('production-excluded')).toContainText('60');
      await expect(section.getByTestId('production-gap')).toContainText(locale === 'fr' ? 'alerte' : 'alert');
      await expect(section.getByTestId('error-tree-evidence').getByTestId('decision-tree-node')).toHaveCount(5);
      // The reused tree says where its rows come from: production, not the test split.
      await expect(section.getByTestId('error-tree-evidence')).toContainText(locale === 'fr' ? 'échantillons de production' : 'labelled production samples');
      await expect(section.getByTestId('fairness-evidence')).toContainText('Retail');
      await section.screenshot({ path: info.outputPath(`production-${theme}-${locale}.png`) });
      await section.getByTestId('production-debug-run').click();
      await expect.poll(() => calls.runs).toBe(1);
      await expect(section.getByTestId('production-status')).toContainText(locale === 'fr' ? 'file d’attente' : 'queued');
      await expect(section.getByTestId('production-debug-run')).toBeDisabled();
    });

    test('Monitor shows the fairness badge and its gap series', async ({ page }) => {
      await setup(page, locale, theme);
      await page.goto(`/models/${model.id}?facet=monitor`);
      const watch = page.getByTestId('fairness-monitor');
      await expect(watch).toContainText(locale === 'fr' ? 'alerte' : 'alert');
      await expect(watch.locator('canvas, svg').first()).toBeVisible();
    });

    test('Play explains with TreeSHAP and searches what would change the answer', async ({ page }, info) => {
      await page.setViewportSize({ width: 1440, height: 1100 });
      const calls = await setup(page, locale, theme);
      await page.goto(`/models/${model.id}`);
      await page.getByRole('tab', { name: locale === 'fr' ? 'Prédire' : 'Predict', exact: true }).click();
      await page.getByRole('button', { name: locale === 'fr' ? 'Prédire' : 'Predict', exact: true }).click();
      await expect.poll(() => calls.predict.at(-1)?.explain_method).toBe('auto');
      const explained = page.getByTestId('shap-explanation');
      await expect(explained.getByTestId('shap-bar')).toHaveCount(2);
      await expect(explained.getByTestId('shap-other')).toContainText(locale === 'fr' ? 'Autres champs (1)' : 'Other fields (1)');
      await expect(explained.getByTestId('shap-method')).toContainText(locale === 'fr' ? 'TreeSHAP exact' : 'Exact TreeSHAP');
      await explained.screenshot({ path: info.outputPath(`shap-${theme}-${locale}.png`) });
      const panel = page.getByTestId('counterfactual-panel');
      await panel.getByLabel('visits', { exact: true }).check();
      await panel.getByTestId('counterfactual-search').click();
      await expect.poll(() => calls.counterfactual.at(-1)?.fields).toEqual(['visits']);
      await expect(panel.getByTestId('counterfactual-results').locator('tbody tr')).toHaveCount(1);
      await expect(panel.getByTestId('counterfactual-results')).toContainText('18');
    });
  });
}
