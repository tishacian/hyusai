import { readFileSync } from 'node:fs';
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

test.use({ serviceWorkers: 'block', video: 'off', ignoreHTTPSErrors: false });

// Every API call is answered locally and non-loopback traffic is aborted, so
// the catalogue is exercised against the production bundle without a backend
// or a connector credential. The fixtures are generated from the backend
// catalogue service (`public_catalog`) and the profiles route.
const catalog = JSON.parse(readFileSync('e2e/fixtures/connector-catalog.json', 'utf8'));
const profiles = JSON.parse(readFileSync('e2e/fixtures/connections-profiles.json', 'utf8'));
const workspace = {
  id: 'catalog-qa', slug: 'catalog-qa', name: 'Catalogue QA', role: 'admin', role_template: 'workspace_admin',
  is_active: true, mode: 'builder', app_entitlements: [],
  settings: { features: {} }, effective_features: {},
};

async function setup(page: Page, locale: 'fr' | 'en') {
  const unexpected: string[] = [];
  await page.route('**/*', (route) =>
    ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort('blockedbyclient'));
  await page.addInitScript(({ slug, locale }) => {
    localStorage.setItem('agentium_token', 'Bearer isolated-catalog-qa');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_locale', locale);
    localStorage.setItem('agentium_theme', locale === 'fr' ? 'dark' : 'light');
  }, { slug: workspace.slug, locale });
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    const method = request.method();
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/auth/validate' && method === 'POST') return json({ valid: true, user_id: 'catalog-admin', role: 'admin' });
    if (path === '/auth/workspaces') return json([workspace]);
    if (path === `/auth/workspaces/${workspace.slug}`) return json(workspace);
    if (path === '/auth/me') return json({ id: 'catalog-admin', username: 'admin', email: 'admin@example.test', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === `/auth/workspaces/${workspace.slug}/me/experience`) {
      return json({ version: 1, persona: 'builder', journey: 'client_sources', completed_steps: [], dismissed: true, available: false, sources: [], rail_labels: 'shown', first_seen_at: '2026-10-15T09:00:00Z' });
    }
    if (path === '/settings') return json({});
    if (path === '/iam/matrix') return json({ workspace, subject_user_id: 'catalog-admin', role_template: 'workspace_admin', custom_labels: [], role_flags: {}, enforcement: false, permissions: [] });
    if (path === '/skills/runtime-health') return json({ skills: {}, summary: { bound: 0, stub: 0, unbound: 0, catalog_only: 0 } });
    if (path === '/reasoning/templates') return json({ templates: [] });
    if (path === '/voice/runtimes') return json({ runtimes: [] });
    if (path === '/actions/effective') return json({ actions: [] });
    if (['/systems', '/capabilities', '/skills', '/runs', '/sessions'].includes(path)) return json({ [path.slice(1)]: [] });
    if (path === '/models') return json({ models: [] });
    if (path === '/help-content') return json({ version: 'local', items: [], personas: [], languages: [] });
    if (path === '/telemetry/live') return json({ throughput_rpm: null, latency_ms: null, runs_count: 0 });
    if (path === '/audit' && method === 'POST') return json({ id: 'local-navigation-audit' }, 201);
    if (path === '/connectors') return json({ can_configure: true, connectors: [] });
    if (path === '/connector-catalog') return json(catalog);
    if (path === '/connections/profiles') return json(profiles.profiles);
    if (path === '/connections/tool-catalog') return json(profiles.tool_catalog);
    if (path === '/connections' && method === 'GET') return json({ connections: [], can_configure: true, can_import: true });
    if (path === '/secrets') return json({ secrets: [], can_manage_platform: false });
    unexpected.push(`${method} ${path}`);
    return json({ detail: `Unhandled local mock endpoint: ${method} ${path}` }, 501);
  });
  return unexpected;
}

const card = (page: Page, key: string) => page.getByTestId(`catalog-card-${key}`);

test.describe('Connector catalogue — isolated mocked QA', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(
      process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname),
      'Local mocked QA only.',
    );
  });

  for (const locale of ['fr', 'en'] as const) {
    test(`${locale}: the catalogue shows its depth with logos and opens prefilled connections`, async ({ page }, info) => {
      test.setTimeout(120000);
      await page.setViewportSize({ width: 1440, height: 1000 });
      const unexpected = await setup(page, locale);
      const fr = locale === 'fr';
      await page.goto('/connectors');

      await expect(page.getByTestId('catalog-count-data')).toHaveText('25');
      await expect(page.getByTestId('catalog-count-tools')).toHaveText('5');
      await expect(page.getByTestId('catalog-disabled-banner')).toHaveCount(0);
      for (const [key, brand] of [['postgresql', 'postgresql'], ['snowflake', 'snowflake'], ['s3', 'amazons3'], ['mongodb', 'mongodb'], ['github', 'github'], ['huggingface', 'huggingface']]) {
        await expect(card(page, key).locator(`svg[data-brand="${brand}"]`)).toBeVisible();
      }
      // No logo exists for Iceberg: a neutral glyph, never an empty slot.
      await expect(card(page, 'iceberg_rest').locator('svg[data-brand]')).toHaveCount(0);
      await expect(card(page, 'iceberg_rest').locator('app-brand-icon lucide-angular')).toHaveCount(1);
      await expect(card(page, 'cassandra').getByRole('listitem')).toHaveText([fr ? 'Lecture' : 'Read']);
      await expect(card(page, 'github')).toContainText(fr ? 'Officiel' : 'Official');
      await expect(card(page, 'snowflake').locator('.ck-pill')).toHaveText(fr ? 'Non certifié' : 'Not certified');
      await expect(card(page, 'github').locator('.ck-pill')).toHaveText(fr ? 'Tiers' : 'Third party');

      const violations = await new AxeBuilder({ page }).include('app-connector-catalog').analyze();
      expect(violations.violations).toEqual([]);
      await page.screenshot({ path: info.outputPath(`connector-catalog-${locale}.png`), fullPage: true });

      await page.getByTestId('catalog-search').fill(fr ? 'entrepot' : 'warehouse');
      await expect(page.locator('[data-testid^="catalog-card-"]')).toHaveCount(5);
      await page.getByTestId('catalog-search').fill('SNOW');
      await expect(page.locator('[data-testid^="catalog-card-"]')).toHaveCount(1);
      await page.getByTestId('catalog-search').fill('');
      await page.getByTestId('catalog-family-object_files').click();
      await expect(page.getByTestId('catalog-family-object_files')).toHaveAttribute('aria-pressed', 'true');
      await expect(page.locator('[data-testid^="catalog-card-"]')).toHaveCount(7);
      await page.getByTestId('catalog-family-all').click();

      await page.getByTestId('catalog-connect-snowflake').click();
      await expect(page).toHaveURL(/\/connectors\/connections\?.*profile=snowflake/);
      await expect(page.locator('select[name="connection-profile"]')).toHaveValue('snowflake');
      await expect(page.locator('select[name="connection-profile"] option:checked')).toHaveText('Snowflake');

      await page.goto('/connectors');
      await page.getByTestId('catalog-connect-github').click();
      await expect(page).toHaveURL(/profile=mcp/);
      await expect(page).toHaveURL(/server=github/);
      await expect(page.locator('input[name="connection-name"]')).toHaveValue('GitHub');
      await expect(page.locator('#connection-base_url')).toHaveValue('https://api.githubcopilot.com/mcp/');
      await expect(page.locator('select[name="connection-profile"] option:checked')).toHaveText(fr ? 'Serveur MCP' : 'MCP server');

      expect(unexpected).toEqual([]);
    });
  }
});
