import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';

/** Product-only fixtures: no demo endpoint, remote request or live execution. */
test.use({ serviceWorkers: 'block', video: 'off', reducedMotion: 'reduce' });
const workspace = { id: 'impact-polish-qa', slug: 'impact-polish-qa', name: 'Service operations', role: 'owner', role_template: 'workspace_owner', settings: { features: { hypervisor_v2: true } } };
const scenario = { manual_minutes: 8, assisted_minutes: 2, hourly_cost: 40, unit_budget: 0.5, monthly_volume: 1000, currency: 'EUR', unit_label: 'Dossier', note: 'Convention du responsable SAV, à valider par une mesure humaine.' };
const block = (type: string, settings: Record<string, unknown> = {}) => ({ type, settings });
const strata = (types: string[]) => ({ comprendre: types.map(type => block(type)), detailler: [block('registre')], decider: [] });
const savedViews = [
  { id: 'direction', label: 'Direction', denominator: 'hours', period: '90d', strata: strata(['monument', 'provenance', 'cadran', 'rivers', 'hors_denominateur']), register_columns: ['unit', 'cost', 'basis', 'value'], sort: 'value' },
  { id: 'operations', label: 'Opérations', denominator: 'runs', period: '30d', strata: strata(['activity', 'monument', 'cadran', 'rivers']), register_columns: ['unit', 'spark'], sort: 'days_since_last_run' },
  { id: 'conformite', label: 'Conformité', denominator: 'runs', period: '90d', strata: strata(['unites', 'couverture', 'decisions']), register_columns: ['unit', 'basis'], sort: 'name' },
  { id: 'sav', label: 'SAV · activité et capacité', denominator: 'runs', period: '7d', system_id: 'service-desk', schema_version: 2,
    strata: { comprendre: [block('financial_scenario', scenario), block('activity', { metrics: ['statuses', 'calls', 'costs', 'duration'] })], detailler: [block('registre')], decider: [] }, register_columns: ['unit', 'spark'], sort: 'name' },
];
const dates = Array.from({ length: 7 }, (_, index) => `2026-10-${String(16 + index).padStart(2, '0')}`);
const available = (value: number, unit?: string) => ({ state: 'available', value, ...(unit ? { unit } : {}) });
const unknown = { state: 'not_measured', value: null };
const absent = { state: 'not_configured', value: null };
const valueBasis = { status: 'declared', unit: 'dossier', hours_per_unit: 0.1, value_per_unit: 4, currency: 'EUR', declared_by: 'owner@example.test', declared_at: '2026-10-15T00:00:00Z', note: 'Declared capacity, not measured savings' };

type FixtureOptions = { locale?: 'fr' | 'en'; theme?: 'dark' | 'light'; defaultView?: string; canEdit?: boolean; ml?: 'alerts' | 'empty' | 'unavailable' | 'disabled' };
async function fixture(page: Page, options: FixtureOptions = {}) {
  let views = structuredClone(savedViews), defaultView = options.defaultView ?? 'direction';
  const writes: string[] = [], requests: URL[] = [], saved: any[] = [], foreignRequests: string[] = [], errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    if (['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname)) return route.fallback();
    foreignRequests.push(route.request().url());
    return route.abort();
  });
  await page.addInitScript(({ locale, theme, slug }) => {
    localStorage.setItem('agentium_token', 'Bearer isolated-impact-polish-qa');
    localStorage.setItem('agentium_locale', locale); localStorage.setItem('agentium_theme', theme); localStorage.setItem('agentium_workspace_slug', slug);
  }, { locale: options.locale ?? 'fr', theme: options.theme ?? 'dark', slug: workspace.slug });
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname.replace(/^\/api\/v1/, '');
    requests.push(url);
    if (request.method() !== 'GET') writes.push(path);
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa', email: 'owner@example.test', role: 'admin' });
    if (path === '/auth/me') return json(route, { id: 'qa', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === '/auth/workspaces/' + workspace.slug) return json(route, workspace);
    if (path === '/hypervisor/views') {
      if (request.method() === 'PUT') {
        if (options.canEdit === false) return json(route, { detail: 'Read only' }, 403);
        const body = request.postDataJSON(); saved.push(body); views = body.views; defaultView = body.default_view_id;
      }
      return json(route, { views, can_edit: options.canEdit !== false, default_view_id: defaultView });
    }
    if (path === '/hypervisor/activity/systems') return json(route, { systems: [{ id: 'service-desk', name: 'Service desk' }, { id: 'review', name: 'Document review' }] });
    if (path === '/hypervisor/value-bases') return json(route, { items: [
      { capability_id: 'support', slug: 'support', name: 'Customer service', output_unit: 'dossier', value_basis: valueBasis, systems: [{ system_id: 'service-desk', name: 'Service desk' }] },
      { capability_id: 'review', slug: 'review', name: 'Document review', output_unit: 'avis', value_basis: { status: 'none' }, systems: [{ system_id: 'review', name: 'Document review' }] },
    ] });
    if (path === '/hypervisor/series') return json(route, { window: url.searchParams.get('window'), from: dates[0], to: dates[6], systems: [
      { system_id: 'service-desk', name: 'Service desk', capability_id: 'support', output_unit: 'dossier', value_basis: valueBasis, days_since_last_run: available(0), buckets: dates.map((date, i) => ({ date, runs: available(i + 1), outcomes: available(i + 1, 'dossier'), hours: available((i + 1) / 10), cost: unknown, value_declared: available((i + 1) * 4) })) },
      { system_id: 'review', name: 'Document review', capability_id: 'review', output_unit: 'avis', value_basis: { status: 'none' }, days_since_last_run: available(0), buckets: dates.map(date => ({ date, runs: available(2), outcomes: available(2, 'avis'), hours: absent, cost: unknown, value_declared: absent })) },
    ] });
    if (path === '/hypervisor/activity') return json(route, {
      window: url.searchParams.get('window'), from: dates[0] + 'T00:00:00Z', to: dates[6] + 'T23:59:00Z', limited: false, limit: 2000,
      counts: { attempts: 35, completed: 28, failed: 6, cancelled: 0, pending: 1, invocations: 231 },
      buckets: dates.map((date, i) => ({ date, attempts: i + 2, completed: i + 1, failed: i === 6 ? 0 : 1, cancelled: 0, pending: i === 6 ? 1 : 0 })),
      costs: { state: 'partial', by_currency: { EUR: '0', USD: '0.33' }, priced_invocations: 181, unpriced_invocations: 50 },
      median_technical_seconds: 48.3, technical_sample_count: 34,
      runs: [{ id: 'service-proof', system_id: 'service-desk', status: 'completed', started_at: '2026-10-22T10:00:00Z', technical_seconds: 48.3 }, { id: 'service-failure', system_id: 'service-desk', status: 'failed', started_at: '2026-10-21T10:00:00Z', technical_seconds: 12 }],
    });
    if (path === '/ml-operations/features') return json(route, { enabled: options.ml !== 'disabled', alerts_enabled: false, can_manage_channels: false, scopes: ['workspace', 'system'] });
    if (path === '/ml-operations/alerts') {
      if (options.ml === 'unavailable') return json(route, { detail: 'Unavailable' }, 503);
      if (options.ml === 'empty') return json(route, { items: [], total: 0 });
      return json(route, { total: 53, items: [
        { id: 'historical', model_id: 'model-old', workspace_id: workspace.id, event: 'monitor_transition', state: 'alert', created_at: '2026-10-20T09:00:00Z', acknowledged_at: '2026-10-20T10:00:00Z' },
        { id: 'watch', model_id: 'model-watch', workspace_id: workspace.id, event: 'monitor_transition', state: 'watch', created_at: '2026-10-22T10:00:00Z', acknowledged_at: null },
        { id: 'critical', model_id: 'model-critical', workspace_id: workspace.id, event: 'monitor_failed', state: 'failed', created_at: '2026-10-21T10:00:00Z', acknowledged_at: null },
      ] });
    }
    if (path === '/systems' || path === '/capabilities') return json(route, []);
    if (path === '/hypervisor/decisions') return json(route, { items: [], total: 0, limit: 20, offset: 0 });
    if (path === '/hypervisor/recommendations') return json(route, { items: [] });
    if (path === '/hypervisor/balance-sheet') return json(route, { portfolio: {}, capabilities: [], signals: [] });
    return json(route, {});
  });
  return { writes, requests, saved, foreignRequests, errors };
}

test.describe('Impact polish — scoped product evidence and audience views', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Isolated loopback only.');
  });

  test('FR dark desktop: four views keep their scope and a compact, actionable ML summary', async ({ page }, info) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    const state = await fixture(page);
    await page.goto('/hypervisor?facet=synthese');
    const inbox = page.getByTestId('ml-alert-inbox');
    await expect(inbox).toBeVisible();
    await expect(inbox.getByTestId('ml-alert-inbox-details')).toHaveCount(0);
    await expect(inbox).toHaveAttribute('data-tone', 'alert');
    expect(await inbox.evaluate(el => el.getBoundingClientRect().height)).toBeLessThanOrEqual(110);
    await inbox.getByTestId('ml-alert-inbox-toggle').click();
    const detail = inbox.getByTestId('ml-alert-inbox-details');
    await expect(detail.locator('li')).toHaveCount(2);
    await expect(detail.locator('li').first()).toHaveAttribute('data-state', 'failed');
    await expect(detail.locator('li').first().getByRole('link')).toHaveAttribute('href', /model-critical/);
    await expect(detail).toContainText('53');
    await inbox.getByTestId('ml-alert-inbox-toggle').click();
    for (const id of ['direction', 'operations', 'conformite', 'sav']) {
      await page.getByTestId('hypervisor-v2-view-' + id).click();
      await expect(page.getByTestId('hypervisor-v2-view-' + id)).toHaveAttribute('aria-selected', 'true');
      if (id === 'sav') {
        await expect(page.getByTestId('impact-projected-roi')).toContainText('700');
        await expect(page.getByTestId('impact-attempts')).toHaveText('35');
        await expect(page.getByTestId('impact-view-scope')).toContainText('Service desk');
        await expect(page.getByTestId('impact-reading-scope')).toHaveValue('service-desk');
        // Monitoring models may belong to another training system and be bound
        // into this Flow: the inbox deliberately retains a labelled workspace scope.
        expect(state.requests.filter(url => url.pathname.endsWith('/ml-operations/alerts')).every(url => url.searchParams.get('scope') === 'workspace' && !url.searchParams.has('system_id'))).toBe(true);
      }
      await page.screenshot({ path: info.outputPath(`impact-${id}-fr-dark-desktop.png`), fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.getByTestId('hypervisor-v2-view-operations').click();
    await expect(page.getByTestId('impact-attempts')).toHaveText('35');
    await page.screenshot({ path: info.outputPath('impact-operations-fr-dark-1280.png'), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(state.requests.some(url => url.pathname.includes('/ecommerce-claims'))).toBe(false);
    expect(state.writes.filter(path => !path.startsWith('/auth/') && path !== '/audit')).toEqual([]);
    // The font stylesheet is explicitly aborted by the fixture, just like any
    // remote request. API traffic must stay entirely on loopback.
    expect(state.foreignRequests.every(url => new URL(url).hostname === 'fonts.googleapis.com')).toBe(true);
    expect(state.errors).toEqual([]);
  });

  test('EN light mobile: projected value, observed costs and drill-down retain distinct meanings', async ({ page }, info) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await fixture(page, { locale: 'en', theme: 'light', defaultView: 'sav' });
    await page.goto('/hypervisor');
    const financial = page.getByTestId('impact-financial-scenario');
    await expect(financial).toBeVisible();
    await expect(financial.getByTestId('impact-projected-roi')).toContainText('700');
    await expect(page.getByTestId('impact-reading-scope')).toHaveValue('service-desk');
    const inbox = page.getByTestId('ml-alert-inbox');
    await expect(inbox).toHaveAttribute('data-tone', 'alert');
    await expect(inbox.getByTestId('ml-alert-inbox-toggle')).toBeVisible();
    expect(await inbox.evaluate(el => el.getBoundingClientRect().height)).toBeLessThanOrEqual(115);
    await page.screenshot({ path: info.outputPath('impact-sav-en-light-mobile-overview.png'), fullPage: true });
    await expect(financial.getByTestId('impact-scenario-assumptions')).not.toHaveAttribute('open');
    await financial.locator('summary').click();
    await expect(financial.locator('details')).toHaveAttribute('open', '');
    await expect(financial).toContainText(scenario.note);
    await financial.locator('summary').click();
    await page.screenshot({ path: info.outputPath('impact-sav-en-light-mobile-value.png'), fullPage: true });
    const activity = page.getByTestId('impact-activity');
    await expect(activity.getByTestId('impact-costs')).toContainText('181/231');
    await expect(activity.getByTestId('impact-costs')).toContainText('€0.00 / $0.33');
    await expect(activity.getByTestId('impact-costs')).toContainText('Partial cost');
    await activity.getByTestId('impact-activity-chart').locator('[data-day="6"]').click();
    const proof = activity.getByTestId('impact-evidence');
    await expect(proof).toHaveAttribute('open', '');
    await expect(proof.getByRole('link')).toHaveAttribute('href', /\/runs\/service-proof/);
    await expect(proof.getByTestId('impact-evidence-partial')).toBeVisible();
    await expect(proof.getByTestId('impact-evidence-coverage')).toContainText('1 / 8');
    await proof.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect((await new AxeBuilder({ page }).include('app-hypervisor-v2').analyze()).violations).toEqual([]);
    await page.screenshot({ path: info.outputPath('impact-sav-en-light-mobile-proof.png'), fullPage: true });
  });

  test('saving a user view preserves the other audience views, scope, order and assumptions', async ({ page }) => {
    const state = await fixture(page, { defaultView: 'sav' });
    await page.goto('/hypervisor');
    await page.getByTestId('impact-financial-scenario').getByRole('button', { name: 'Configurer', exact: true }).click();
    await page.getByTestId('impact-settings-financial_scenario').getByLabel('Coût horaire chargé', { exact: true }).fill('45');
    await page.getByRole('button', { name: /Enregistrer/ }).click();
    await expect(page.getByTestId('impact-save-message')).toContainText('enregistrée');
    expect(state.saved).toHaveLength(1);
    const payload = state.saved[0], custom = payload.views.find((view: any) => view.id === 'sav');
    expect(payload.default_view_id).toBe('sav');
    expect(payload.views.map((view: any) => view.id)).toEqual(savedViews.map(view => view.id));
    expect(custom.system_id).toBe('service-desk'); expect(custom.period).toBe('7d');
    expect(custom.strata.comprendre.map((item: any) => item.type)).toEqual(['financial_scenario', 'activity']);
    expect(custom.strata.comprendre[0].settings).toEqual({ ...scenario, hourly_cost: 45 });
    for (const id of ['direction', 'operations', 'conformite']) {
      const original = savedViews.find(view => view.id === id)!;
      const persisted = payload.views.find((view: any) => view.id === id);
      expect(persisted.period).toBe(original.period); expect(persisted.strata).toEqual(original.strata);
    }
    await page.reload();
    await expect(page.getByTestId('hypervisor-v2-view-sav')).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByTestId('impact-projected-roi')).toContainText('800');
  });

  test('reading controls refresh the selected scope without saving or discarding a draft', async ({ page }) => {
    const state = await fixture(page, { defaultView: 'sav' });
    await page.goto('/hypervisor');
    await page.getByTestId('impact-financial-scenario').getByRole('button', { name: 'Configurer', exact: true }).click();
    await page.getByTestId('impact-settings-financial_scenario').getByLabel('Coût horaire chargé', { exact: true }).fill('45');
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('impact-settings-financial_scenario')).not.toBeVisible();
    await page.getByTestId('impact-reading-period-30d').click();
    await expect(page.getByTestId('impact-reading-period-30d')).toHaveAttribute('aria-pressed', 'true');
    await page.getByTestId('impact-reading-scope').selectOption('review');
    await expect(page.getByTestId('impact-view-scope')).toContainText('Document review');
    const previousRequests = state.requests.length;
    await page.getByTestId('impact-refresh').click();
    await expect(page.getByTestId('impact-projected-roi')).toContainText('800');
    await expect(page.getByTestId('impact-reading-scope')).toHaveValue('review');
    await expect(page.getByTestId('impact-reading-period-30d')).toHaveAttribute('aria-pressed', 'true');
    await expect.poll(() => state.requests.slice(previousRequests).some(url => url.pathname.endsWith('/hypervisor/activity') && url.searchParams.get('window') === '30d' && url.searchParams.get('system_id') === 'review')).toBe(true);
    expect(state.requests.slice(previousRequests).some(url => url.pathname.endsWith('/hypervisor/views'))).toBe(false);
    expect(state.saved).toEqual([]);
    await page.getByTestId('impact-financial-scenario').getByRole('button', { name: 'Configurer', exact: true }).click();
    await expect(page.getByTestId('impact-settings-financial_scenario').getByLabel('Coût horaire chargé', { exact: true })).toHaveValue('45');
  });

  test('presentation keeps Operations, Compliance and the saved SAV composition', async ({ page }, info) => {
    const state = await fixture(page);
    await page.goto('/hypervisor');
    for (const id of ['operations', 'conformite', 'sav']) {
      await page.getByTestId('hypervisor-v2-view-' + id).click();
      await expect(page.getByTestId('hypervisor-v2-view-' + id)).toHaveAttribute('aria-selected', 'true');
      await page.getByTestId('hypervisor-enter-presentation').click();
      await expect(page.locator('app-hypervisor-v2.hv2-theme-presentation')).toBeVisible();
      await expect(page.getByTestId('hypervisor-presentation')).toHaveCount(0);
      await expect(page.getByTestId('impact-reading-scope')).toHaveCount(0);
      await expect(page.getByTestId('ml-alert-inbox')).toHaveCount(0);
      if (id === 'conformite') {
        await expect(page.getByTestId('hypervisor-v2-couverture')).toBeVisible();
        await expect(page.getByTestId('hypervisor-v2-unites')).toBeVisible();
      } else {
        await expect(page.getByTestId('impact-attempts')).toHaveText('35');
        await expect(page.getByTestId('impact-activity').getByRole('button', { name: 'Configurer', exact: true })).toHaveCount(0);
      }
      if (id === 'sav') await expect(page.getByTestId('impact-projected-roi')).toContainText('700');
      await page.screenshot({ path: info.outputPath(`impact-${id}-presentation.png`), fullPage: true });
      await page.getByTestId('hypervisor-quit-presentation').click();
    }
    expect(state.saved).toEqual([]);
  });

  for (const state of ['empty', 'unavailable'] as const) {
    test(`read-only with ML ${state}: no health claim or edit affordance`, async ({ page }) => {
      const fixtureState = await fixture(page, { locale: 'en', defaultView: 'sav', canEdit: false, ml: state });
      await page.goto('/hypervisor');
      const inbox = page.getByTestId('ml-alert-inbox');
      await expect(inbox).toBeVisible();
      await expect(inbox).toHaveAttribute('data-tone', state === 'unavailable' ? 'unknown' : 'neutral');
      await expect(inbox).not.toContainText(/healthy|all clear|operating normally/i);
      await expect(inbox.getByTestId('ml-alert-inbox-toggle')).toHaveCount(0);
      await expect(page.getByTestId('impact-financial-scenario').getByRole('button', { name: 'Configure', exact: true })).toHaveCount(0);
      await expect(page.getByTestId('impact-activity').getByRole('button', { name: 'Configure', exact: true })).toHaveCount(0);
      await expect(page.getByTestId('impact-projected-roi')).toContainText('700');
      expect(fixtureState.writes.filter(path => path === '/hypervisor/views' || path.startsWith('/ml-operations/'))).toEqual([]);
    });
  }

  test('disabled ML monitoring consumes no alert feed or space', async ({ page }) => {
    const state = await fixture(page, { defaultView: 'sav', ml: 'disabled' });
    await page.goto('/hypervisor');
    await expect(page.getByTestId('impact-attempts')).toHaveText('35');
    await expect(page.getByTestId('ml-alert-inbox')).toHaveCount(0);
    expect(state.requests.some(url => url.pathname.endsWith('/ml-operations/alerts'))).toBe(false);
  });
});
