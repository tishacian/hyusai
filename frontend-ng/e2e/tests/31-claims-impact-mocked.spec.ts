import { expect, test, type Page, type Route } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.use({ serviceWorkers: 'block', video: 'off', ignoreHTTPSErrors: false });
const workspace = { id: 'claims-impact-qa', slug: 'claims-impact-qa', name: 'Showcase QA', role: 'owner', role_template: 'workspace_owner', settings: { features: { hypervisor_v2: true, experience_v1: true, ecommerce_claims_v1: true } } };
const fixture = {
  system_id: 'qa-system', assumptions: { manual_minutes: 8, assisted_minutes: 2, hourly_eur: '40.00', incremental_eur_per_case: '0.50' },
  counts: { attempts: 20, completed: 12, failed: 8, duplicate_blocked: 8, pending: 0, unique_cases: 10, rule_matched_cases: 10, simulated_receipts: 8, waiting_information_cases: 2, invocations: 204 },
  catalog_costs: { state: 'partial', by_currency: { EUR: '0', USD: '0.294' }, priced_invocations: 160, unpriced_invocations: 44 },
  median_technical_seconds: 46.7, period: { limited: false },
  runs: [
    { run_id: 'qa-inquiry', claim_id: 'RC-5002', status: 'completed', reason: null, action: 'carrier_investigation', automatic_rule_match: true, technical_seconds: 41 },
    { run_id: 'qa-duplicate', claim_id: 'RC-5002', status: 'failed', reason: 'duplicate_action', action: 'carrier_investigation', automatic_rule_match: true, technical_seconds: 41 },
    { run_id: 'qa-missing', claim_id: 'RC-5008', status: 'completed', reason: 'missing_information', action: 'request_information', automatic_rule_match: true, technical_seconds: 80 },
  ],
};

async function setup(page: Page, theme = 'dark', locale = 'fr', unavailable = false) {
  let requests = 0;
  const writes: string[] = [];
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.addInitScript(({ theme, locale, slug }) => {
    localStorage.setItem('agentium_token', 'Bearer isolated-financial-qa');
    localStorage.setItem('agentium_theme', theme); localStorage.setItem('agentium_locale', locale); localStorage.setItem('agentium_workspace_slug', slug);
  }, { theme, locale, slug: workspace.slug });
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/v1/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa-viewer', email: 'qa@example.test', role: 'admin' });
    if (path === '/auth/me') return json(route, { id: 'qa-viewer', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === '/auth/workspaces/' + workspace.slug) return json(route, workspace);
    if (req.method() !== 'GET') writes.push(path);
    if (path === '/ecommerce-claims/activity') { requests++; return json(route, fixture, unavailable ? 404 : 200); }
    if (path === '/ecommerce-claims/benchmark') return json(route, {
      state: 'experiment_not_complete', hourly_eur: '40.00', planned_pairs: 10, completed_quality_pairs: 0,
      capacity_value_eur: null, incremental_cost_eur: null, net_benefit_eur: null, roi: null,
      trials: [], protocol_sha256: 'qa-protocol', protocol: { version: 'human-benchmark', pairs: [] },
    });
    if (path === '/systems' || path === '/capabilities') return json(route, []);
    if (path === '/hypervisor/views') return json(route, { views: [], can_edit: false });
    if (path === '/hypervisor/decisions') return json(route, { items: [], total: 0, limit: 20, offset: 0 });
    if (path.startsWith('/hypervisor/') || path.startsWith('/mission-room/')) return json(route, {});
    return json(route, {});
  });
  return { writes, requests: () => requests };
}

test.describe('Luma activity and projected finance — isolated end-user QA', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  });
  for (const [theme, locale, width] of [['dark', 'fr', 1440], ['light', 'fr', 390], ['light', 'en', 1440]] as const) {
    test(`${theme}/${locale}/${width}: declared projection, observed ledger and human benchmark`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 1000 });
      const { writes } = await setup(page, theme, locale);
      await page.goto('/hypervisor?facet=synthese');
      const card = page.getByTestId('claims-activity');
      await expect(card).toBeVisible();
      await expect(card.getByTestId('claims-projected-net')).toContainText('3');
      await expect(card.getByTestId('claims-projected-roi')).toContainText('700');
      await expect(page.getByTestId('claims-benchmark')).toContainText('0/10');
      await expect(card).toContainText(locale === 'en' ? 'Human work still needs measurement' : 'Le temps humain reste à mesurer');
      await expect(card).toContainText('160/204');
      await expect(card).toContainText(locale === 'en' ? '8 distinct simulated receipts' : '8 reçus simulés distincts');
      expect(await card.getByRole('button').evaluate(e => e.getBoundingClientRect().height)).toBeLessThanOrEqual(32);
      await card.locator('summary').click();
      await expect(card.getByRole('link', { name: locale === 'en' ? 'View investigation' : 'Voir l’enquête' }).first()).toHaveAttribute('href', /\/runs\/qa-inquiry/);
      await expect(card.getByRole('row').filter({ hasText: 'RC-5008' })).toContainText(locale === 'en' ? 'Missing evidence' : 'Pièce manquante');
      expect((await new AxeBuilder({ page }).include('app-claims-activity').analyze()).violations).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(writes.filter(p => p.includes('/ecommerce-claims') || p.includes('/runs'))).toEqual([]);
      await card.getByRole('heading').first().scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath('luma-financial-scenario.png'), fullPage: true });
      if (width === 390) {
        await card.locator('h3').scrollIntoViewIfNeeded();
        await page.screenshot({ path: info.outputPath('luma-financial-mobile-projection.png'), fullPage: true });
      }
    });
  }
  test('changing assumptions is local, preserves negative values and unknown zero-cost ROI', async ({ page }) => {
    const { writes, requests } = await setup(page);
    await page.goto('/hypervisor');
    const card = page.getByTestId('claims-activity');
    await expect(card).toBeVisible();
    await card.getByLabel('Travail humain assisté (min)').fill('11');
    await expect(card.getByTestId('claims-projected-roi')).toContainText('-500');
    await card.getByLabel('Budget complet (€/dossier)').fill('0');
    await expect(card.getByTestId('claims-projected-roi')).toHaveText('—');
    await card.getByRole('button', { name: 'Actualiser' }).click();
    await expect.poll(requests).toBeGreaterThan(1);
    await expect(card.getByLabel('Travail humain assisté (min)')).toHaveValue('11');
    expect(writes.filter(p => p.includes('/ecommerce-claims'))).toEqual([]);
  });
  test('an unavailable demo does not show a synthetic finance card', async ({ page }) => {
    const { requests } = await setup(page, 'dark', 'fr', true);
    await page.goto('/hypervisor');
    await expect.poll(requests).toBeGreaterThan(0);
    await expect(page.getByTestId('claims-activity')).toHaveCount(0);
  });
});
