import { expect, test, type Page, type Route } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.use({ serviceWorkers: 'block', video: 'off', ignoreHTTPSErrors: false });
const workspace = { id: 'impact-product-qa', slug: 'impact-product-qa', name: 'Product QA', role: 'owner', role_template: 'workspace_owner', settings: { features: { hypervisor_v2: true } } };
const initialView = { id: 'direction', label: 'Direction', denominator: 'hours', period: '90d', strata: { comprendre: [], detailler: [], decider: [] }, register_columns: [], sort: 'name' };
const financial = { manual_minutes: 12, assisted_minutes: 3, hourly_cost: 30, unit_budget: 1, currency: 'GBP', unit_label: 'Ticket', note: 'Declared planning assumptions' };

async function setup(page: Page, theme = 'dark', locale = 'fr', configured = false, canEdit = true, unavailable = false, seriesUnavailable = false) {
  let views: any[] = configured ? [
    structuredClone(initialView), { ...initialView, id: 'operations', label: 'Operations', denominator: 'runs', period: '30d' }, { ...initialView, id: 'compliance', label: 'Compliance' },
    { ...initialView, id: 'support', label: 'Customer service — activity and financial forecast', system_id: 'inventory', period: '7d', denominator: 'runs', strata: { comprendre: [{ type: 'activity', title: 'Inventory activity', settings: {} }, { type: 'financial_scenario', settings: financial }], detailler: [], decider: [] } },
  ] : [structuredClone(initialView)];
  let defaultView = configured ? 'support' : views[0].id;
  const writes: string[] = [], requests: string[] = [], saved: unknown[] = [];
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.addInitScript(({ theme, locale, slug }) => {
    localStorage.setItem('agentium_token', 'Bearer isolated-impact-product-qa');
    localStorage.setItem('agentium_theme', theme); localStorage.setItem('agentium_locale', locale); localStorage.setItem('agentium_workspace_slug', slug);
  }, { theme, locale, slug: workspace.slug });
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/v1/**', async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname.replace(/^\/api\/v1/, '');
    requests.push(path);
    if (req.method() !== 'GET') writes.push(path);
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa-user', email: 'qa@example.test', role: 'admin' });
    if (path === '/auth/me') return json(route, { id: 'qa-user', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === '/auth/workspaces/' + workspace.slug) return json(route, workspace);
    if (path === '/hypervisor/views') {
      if (req.method() === 'PUT') { const body = req.postDataJSON(); saved.push(body); views = body.views; defaultView = body.default_view_id ?? defaultView; }
      return json(route, { views, can_edit: canEdit, default_view_id: defaultView });
    }
    if (path === '/hypervisor/activity/systems') return json(route, { systems: [{ id: 'inventory', name: 'Inventory' }, { id: 'support', name: 'Customer support' }] });
    if (path === '/hypervisor/value-bases') return json(route, { items: [
      { capability_id: 'support-capability', name: 'Support', slug: 'support', systems: [{ system_id: 'support', name: 'Customer support' }], value_basis: { status: 'none' } },
      { capability_id: 'other-capability', name: 'Other capability', slug: 'other', systems: [], value_basis: { status: 'none' } },
    ] });
    if (path === '/hypervisor/activity') return json(route, {
      window: url.searchParams.get('window'), from: '2026-10-01T00:00:00', to: '2026-10-07T10:00:00', limited: false, limit: 2000,
      counts: { attempts: 20, completed: 12, failed: 8, cancelled: 0, pending: 0, invocations: 204 },
      buckets: [{ date: '2026-10-06', attempts: 20, completed: 12, failed: 8, cancelled: 0, pending: 0 }],
      costs: { state: 'partial', by_currency: { GBP: '0', USD: '0.294' }, priced_invocations: 160, unpriced_invocations: 44 },
      median_technical_seconds: 46.7, technical_sample_count: 20,
      runs: [{ id: 'qa-execution', system_id: 'inventory', status: 'failed', started_at: '2026-10-06T10:00:00', technical_seconds: 46.7 }],
    }, unavailable ? 503 : 200);
    if (path === '/hypervisor/series') return json(route, { window: url.searchParams.get('window'), from: '2026-10-01', to: '2026-10-07', systems: [
      { system_id: 'inventory', name: 'Inventory', capability_id: null, output_unit: null, value_basis: null, days_since_last_run: { state: 'available', value: 1 }, buckets: [{ date: '2026-10-06', runs: { state: 'available', value: 12 }, outcomes: { state: 'not_measured', value: null }, cost: { state: 'not_measured', value: null }, hours: { state: 'not_configured', value: null }, value_declared: { state: 'not_configured', value: null } }] },
      { system_id: 'support', name: 'Customer support', capability_id: null, output_unit: null, value_basis: null, days_since_last_run: { state: 'available', value: 1 }, buckets: [{ date: '2026-10-06', runs: { state: 'available', value: 99 }, outcomes: { state: 'not_measured', value: null }, cost: { state: 'not_measured', value: null }, hours: { state: 'not_configured', value: null }, value_declared: { state: 'not_configured', value: null } }] },
    ] }, seriesUnavailable ? 503 : 200);
    if (path === '/systems' || path === '/capabilities') return json(route, []);
    if (path === '/hypervisor/decisions') return json(route, { items: [], total: 0, limit: 20, offset: 0 });
    if (path.startsWith('/hypervisor/') || path.startsWith('/mission-room/')) return json(route, {});
    return json(route, {});
  });
  return { writes, requests, saved };
}

test.describe('Configured product Impact blocks — isolated end-user QA', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  });
  test('no global business-app card or assumptions appear without user configuration', async ({ page }) => {
    const { requests } = await setup(page);
    await page.goto('/hypervisor?facet=synthese');
    await expect(page.getByRole('button', { name: /Personnaliser/ })).toBeVisible();
    await expect(page.locator('ck-page-frame header p').filter({ hasText: 'capabilities' })).toContainText('2 capabilities');
    await expect(page.getByTestId('impact-activity')).toHaveCount(0);
    await expect(page.getByTestId('impact-financial-scenario')).toHaveCount(0);
    expect(requests.some(path => path.startsWith('/ecommerce-claims'))).toBe(false);
    expect(requests).not.toContain('/hypervisor/activity');
  });
  test('create, configure, reorder and persist a scoped default view through Customize', async ({ page }) => {
    const { saved, requests, writes } = await setup(page);
    await page.goto('/hypervisor');
    await page.getByRole('button', { name: /Personnaliser/ }).click();
    await page.getByLabel('Nom de la nouvelle vue', { exact: true }).fill('Support desk');
    await page.getByRole('button', { name: 'Créer une vue', exact: true }).click();
    await page.getByTestId('impact-system-scope').selectOption('inventory');
    await page.getByLabel('Ouvrir cette vue par défaut').check();
    const catalog = page.getByTestId('hypervisor-customize-catalog');
    await catalog.getByLabel('Scénario financier', { exact: true }).check();
    await catalog.getByLabel('Monument', { exact: true }).check();
    const settings = page.getByTestId('impact-settings-financial_scenario');
    await expect(settings.getByLabel('Traitement manuel (min / unité)', { exact: true })).toHaveValue('');
    await settings.getByLabel('Devise (code ISO)', { exact: true }).fill('GBP');
    await settings.getByLabel('Traitement manuel (min / unité)', { exact: true }).fill('12');
    await settings.getByLabel('Travail humain assisté (min / unité)', { exact: true }).fill('3');
    await settings.getByLabel('Coût horaire chargé', { exact: true }).fill('30');
    await settings.getByLabel('Budget complet / unité', { exact: true }).fill('1');
    await page.getByTestId('hypervisor-customize-block-financial_scenario').getByRole('button', { name: /Monter/ }).click();
    await page.getByRole('button', { name: /Enregistrer/ }).click();
    await expect(page.getByTestId('impact-save-message')).toContainText('enregistrée');
    expect(saved).toHaveLength(1);
    const payload = saved[0] as any, custom = payload.views.find((v: any) => v.label === 'Support desk');
    expect(custom.system_id).toBe('inventory'); expect(custom.period).toBe('7d');
    expect(custom.strata.comprendre.map((b: any) => b.type)).toEqual(['financial_scenario', 'activity', 'monument']);
    expect(payload.default_view_id).toBe(custom.id);
    await page.reload();
    await expect(page.getByTestId('impact-financial-scenario')).toBeVisible();
    await expect(page.getByTestId('impact-projected-roi')).toContainText('350');
    await expect(page.getByTestId('impact-view-scope')).toContainText('Inventory');
    await expect(page.getByTestId('hypervisor-v2-monument').locator('.hv2-monument')).toHaveText('12');
    await expect(page.locator('ck-page-frame header p').filter({ hasText: 'capabilities' })).toContainText('0 capabilities');
    await expect(page.getByTestId('hypervisor-v2-monument')).toContainText('terminées en 7 jours');
    expect(await page.locator('[data-testid=hypervisor-v2-stratum-comprendre]').evaluate(el => Array.from(el.querySelectorAll('app-impact-financial-scenario,app-impact-activity')).map(x => x.tagName.toLowerCase()))).toEqual(['app-impact-financial-scenario', 'app-impact-activity']);
    expect(requests.some(path => path.startsWith('/ecommerce-claims'))).toBe(false);
    expect(writes.filter(path => path !== '/hypervisor/views' && path !== '/audit' && !path.startsWith('/auth/'))).toEqual([]);
  });
  for (const [theme, locale, width] of [['dark', 'fr', 1440], ['light', 'fr', 390], ['light', 'en', 1440]] as const) {
    test(`${theme}/${locale}/${width}: native evidence, daily graph and declared projection`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 1000 });
      await setup(page, theme, locale, true);
      await page.goto('/hypervisor?facet=synthese');
      const card = page.getByTestId('impact-activity');
      await expect(card).toBeVisible();
      await expect(card.getByTestId('impact-attempts')).toHaveText('20');
      await expect(card.getByTestId('impact-costs')).toContainText('160/204');
      await expect(card.getByTestId('impact-activity-chart')).toBeVisible();
      await expect(page.getByTestId('impact-projected-roi')).toContainText('350');
      expect(await card.getByRole('button').first().evaluate(el => el.getBoundingClientRect().height)).toBeLessThanOrEqual(32);
      await card.locator('summary').click();
      await expect(card.getByRole('link').first()).toHaveAttribute('href', /\/runs\/qa-execution/);
      expect((await new AxeBuilder({ page }).include('app-impact-activity').include('app-impact-financial-scenario').analyze()).violations).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: info.outputPath('impact-product-activity.png'), fullPage: true });
      await page.getByTestId('impact-financial-scenario').scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath('impact-product-scenario.png'), fullPage: true });
    });
  }
  test('mobile customization keeps labels, actions and fields within the chrome', async ({ page }, info) => {
    await page.setViewportSize({ width: 390, height: 900 });
    await setup(page, 'light', 'fr', true);
    await page.goto('/hypervisor');
    const selectedView = page.getByTestId('hypervisor-v2-view-support');
    await expect(selectedView).toHaveAttribute('title', 'Customer service — activity and financial forecast');
    for (const tab of await page.getByRole('tablist').getByRole('tab').all()) {
      expect(await tab.evaluate(el => el.getBoundingClientRect().height)).toBeLessThanOrEqual(32);
    }
    await page.getByTestId('impact-financial-scenario').getByRole('button', { name: 'Configurer', exact: true }).click();
    await expect(page.getByTestId('impact-settings-financial_scenario')).toBeVisible();
    await page.getByTestId('impact-settings-financial_scenario').getByLabel('Coût horaire chargé', { exact: true }).fill('0');
    await page.getByRole('button', { name: /Enregistrer/ }).click();
    await expect(page.getByTestId('impact-save-message')).toContainText('enregistrée');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect((await new AxeBuilder({ page }).include('ck-panel').analyze()).violations).toEqual([]);
    await page.screenshot({ path: info.outputPath('impact-product-customize-mobile.png'), fullPage: true });
  });
  test('configured activity survives a result-series outage and remains in presentation mode', async ({ page }) => {
    await setup(page, 'dark', 'fr', true, true, false, true);
    await page.goto('/hypervisor');
    await expect(page.getByTestId('impact-attempts')).toHaveText('20');
    await page.getByRole('button', { name: 'Présenter', exact: true }).click();
    await expect(page.getByTestId('impact-attempts')).toHaveText('20');
    await expect(page.getByTestId('impact-projected-roi')).toContainText('350');
    await expect(page.getByTestId('impact-activity').getByRole('button', { name: 'Configurer', exact: true })).toHaveCount(0);
  });
  test('a read-only user sees configured evidence, with no write action; a failed source stays unavailable', async ({ page }) => {
    const { writes } = await setup(page, 'dark', 'fr', true, false, true);
    await page.goto('/hypervisor');
    const card = page.getByTestId('impact-activity');
    await expect(card.getByRole('alert')).toContainText('indisponibles');
    await expect(card.getByTestId('impact-attempts')).toHaveCount(0);
    await expect(card.getByRole('button', { name: 'Configurer', exact: true })).toHaveCount(0);
    await expect(page.getByTestId('impact-projected-roi')).toContainText('350');
    expect(writes.filter(path => path === '/hypervisor/views')).toEqual([]);
  });
});
