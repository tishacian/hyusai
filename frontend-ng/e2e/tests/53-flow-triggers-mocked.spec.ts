import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';

test.use({ serviceWorkers: 'block', video: 'off', ignoreHTTPSErrors: false });
const workspace = { id: 'trigger-qa', slug: 'trigger-qa', name: 'Trigger setup QA', role: 'owner', role_template: 'workspace_owner', settings: {}, mode: 'builder' };
const systemId = 'trigger-system';
const hash = '1'.repeat(64);
const executionIdentity = {
  kind: 'delegated_user', user_id: 'qa', display_name: 'Camille', granted_at: '2026-10-19T12:00:00Z',
};
const flow = {
  schema_version: 3,
  nodes: [
    { id: 'source.schedule', type: 'source.schedule', kind: 'source', label: 'Queue schedule', config: { input_schema: { type: 'object' } }, position: { x: 40, y: 40 } },
    { id: 'source.webhook', type: 'source.webhook', kind: 'source', label: 'Claim arrival', config: { input_schema: { type: 'object' } }, position: { x: 40, y: 210 } },
    { id: 'sink', type: 'output', kind: 'sink', label: 'Result', position: { x: 420, y: 125 } },
  ],
  edges: [{ from: 'source.schedule', to: 'sink' }, { from: 'source.webhook', to: 'sink' }],
};

async function setup(page: Page, locale: string, theme: string) {
  // Keep one UI build for the scenario while other local work recompiles Vite.
  await page.routeWebSocket('**', socket => socket.close());
  const writes: Array<{ path: string; body: any }> = [];
  const schedules: any[] = [{ id: 'existing-schedule', name: 'Morning refresh', cron_expr: '0 9 * * 1-5', timezone: 'Europe/Paris', enabled: true, next_fire_at: '2026-10-19T07:00:00', last_run_id: 'schedule-run', input_payload: {} }];
  const hooks: any[] = [];
  const applyIdentity = (row: any, body: any) => ({
    ...row, ...body,
    execution_identity: body.execution_identity === 'current_user' ? executionIdentity
      : body.execution_identity === 'none' ? null : row.execution_identity ?? null,
  });
  const system = { id: systemId, workspace_id: workspace.id, name: 'Unified operations', status: 'active', flow_definition: flow, flow_sha256: hash };
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.addInitScript(({ slug, locale, theme }) => {
    localStorage.setItem('agentium_token', 'Bearer isolated-trigger-qa');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_locale', locale);
    localStorage.setItem('agentium_theme', theme);
  }, { slug: workspace.slug, locale, theme });
  await page.route('**/api/v1/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa', role: 'admin', email: 'qa@example.test' });
    if (path === '/auth/me') return json(route, { id: 'qa', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === '/auth/workspaces/' + workspace.slug) return json(route, workspace);
    if (req.method() !== 'GET') writes.push({ path, body: req.postDataJSON() });
    if (path === '/systems') return json(route, { systems: [system] });
    if (path === `/systems/${systemId}`) return json(route, system);
    if (path === `/systems/${systemId}/flow-state`) return json(route, { system_id: systemId, status: 'active', draft: { revision: 1, flow_sha256: hash, flow_definition: flow }, published: { version_id: 'v1', version_number: 1, flow_sha256: hash, flow_definition: flow, execution_contract_ready: true } });
    if (path === `/systems/${systemId}/validate-flow`) return json(route, { valid: true, issues: [], runtime_mode: 'dag_overlay', flow_sha256: hash });
    if (path === `/systems/${systemId}/trigger-deliveries`) return json(route, { coverage: 'accepted_only', mode: 'dry_run', enabled: true, deliveries: [
      { id: 'accepted-event', run_id: 'accepted-event', source: 'webhook', accepted_at: '2026-10-19T12:00:00Z', acceptance: 'accepted', execution_status: 'failed' },
    ] });
    if (path === `/systems/${systemId}/event-trigger`) return json(route, { system_id: systemId, master_enabled: true, mode: 'dry_run', disabled: false });
    if (path === `/systems/${systemId}/schedules`) {
      if (req.method() === 'POST') { const row = applyIdentity({ id: 'new-schedule' }, req.postDataJSON()); schedules.push(row); return json(route, row, 201); }
      return json(route, { schedules });
    }
    if (path === `/systems/${systemId}/schedules/new-schedule` && req.method() === 'PATCH') {
      const row = applyIdentity(schedules.at(-1), req.postDataJSON());
      row.next_fire_at = row.enabled ? '2026-10-19T07:00:00' : null;
      schedules[schedules.length - 1] = row;
      return json(route, row);
    }
    if (path === `/systems/${systemId}/hooks`) {
      if (req.method() === 'POST') { const row = applyIdentity({ id: 'new-hook', path: '/api/v1/hooks/new-hook', secret: 'fixture-signing-secret' }, req.postDataJSON()); hooks.push(row); return json(route, row, 201); }
      return json(route, { hooks });
    }
    if (path === `/systems/${systemId}/hooks/new-hook` && req.method() === 'PATCH') {
      const row = applyIdentity(hooks.at(-1), req.postDataJSON());
      hooks[hooks.length - 1] = row;
      return json(route, row);
    }
    if (path === '/skills') return json(route, { skills: [] });
    if (path === '/connectors') return json(route, { connectors: [] });
    if (path === '/documents/collections') return json(route, { collections: [] });
    return json(route, {});
  });
  return writes;
}

test.describe('Flow trigger setup — local fixtures only', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  });
  for (const [locale, theme, width] of [['fr', 'dark', 1440], ['en', 'light', 390]] as const) {
    test(`${locale}/${theme}/${width}: published reading never writes and identifies accepted delivery separately from failure`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 });
      const writes = await setup(page, locale, theme);
      await page.goto(`/systems/${systemId}/flow?tab=triggers`);
      await expect(page).toHaveURL(/\/flow\?facet=triggers(?:&|$)/);
      await expect(page.getByTestId('flow-published-reading')).toBeVisible();
      await expect(page.locator('app-flow-node')).toHaveCount(3);
      const deliveries = page.getByTestId('trigger-deliveries');
      await expect(deliveries).toContainText(locale === 'fr' ? 'Livraison acceptée' : 'Delivery accepted');
      await expect(deliveries).toContainText(locale === 'fr' ? 'Traitement en échec' : 'Processing failed');
      await expect(deliveries).toContainText(locale === 'fr' ? 'simulation' : 'simulation');
      await expect(deliveries.getByRole('link')).toHaveAttribute('href', /\/runs\/accepted-event/);
      await page.locator('app-flow-node').filter({ hasText: 'Queue schedule' }).click();
      await page.locator('app-flow-inspector').getByRole('button', { name: locale === 'fr' ? 'Fermer l’inspecteur' : 'Close inspector', exact: true }).click();
      await page.locator('app-flow-builder').click({ position: { x: 8, y: 8 } });
      await page.keyboard.press('Delete');
      await page.keyboard.press('Control+s');
      await page.keyboard.press('Control+z');
      // Give the 1200 ms autosave debounce a chance to fire if a read path regresses.
      await page.waitForTimeout(1500);
      await expect(page.locator('app-flow-node')).toHaveCount(3);
      // Resolving the legacy deep link records navigation telemetry. It must
      // not validate, edit or publish the Flow while reading the published one.
      expect(writes).toEqual([{
        path: '/audit',
        body: {
          event_type: 'navigation.resolved', severity: 'info',
          details: {
            schema_version: 1, requested_route: '/systems/:systemId/flow',
            resolved_route: '/systems/:systemId/flow', effective_surface: 'systems',
            effective_workspace: workspace.slug, redirected: true,
            redirect_reason: 'legacy_tab_query', redirect_owner: 'navigation_resolver',
          },
        },
      }]);
      await page.getByRole('button', { name: /Modifier le brouillon|Edit draft/ }).click();
      await expect(page.getByTestId('flow-published-reading')).toHaveCount(0);
      await expect.poll(() => writes.some(write => write.path.endsWith('/validate-flow'))).toBe(true);
    });

    test(`${locale}/${theme}/${width}: configure a paused schedule and inspect its next execution`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 1000 });
      const writes = await setup(page, locale, theme);
      await page.goto(`/systems/${systemId}/flow?lens=build`);await page.getByRole('button', { name: /Modifier le brouillon|Edit draft/ }).click();
      await expect(page.locator('app-flow-node')).toHaveCount(3);
      await page.locator('app-flow-node').filter({ hasText: 'Queue schedule' }).click();
      const panel = page.locator('app-flow-triggers-panel');
      await expect(panel).toBeVisible();
      await expect(page.locator('app-flow-trigger-controls')).toHaveCount(0);
      await expect(panel).not.toContainText('Webhooks');
      await expect(panel).toContainText('Europe/Paris');
      await expect(panel).toContainText(locale === 'fr' ? '09:00' : '9:00 AM');
      await expect(panel.getByRole('link')).toHaveAttribute('href', /\/runs\/schedule-run/);
      await panel.locator('.ck-trig__setup > summary').click();
      await expect(panel.getByRole('checkbox')).not.toBeChecked();
      await panel.getByLabel(locale === 'fr' ? 'Nom' : 'Name', { exact: true }).fill('Queue refresh');
      await panel.getByLabel(locale === 'fr' ? 'Fuseau horaire' : 'Time zone').fill('Europe/Paris');
      const input = panel.getByLabel(locale === 'fr' ? 'Données d’entrée (objet JSON)' : 'Input data (JSON object)');
      await input.fill('[]');
      const save = panel.getByRole('button', { name: locale === 'fr' ? 'Enregistrer en pause' : 'Save paused' });
      await save.click();
      await expect(panel.getByRole('alert')).toBeVisible();
      expect(writes.filter(w => w.path.endsWith('/schedules'))).toHaveLength(0);
      await input.fill('{"queue":"priority"}');
      await save.click();
      await expect.poll(() => writes.filter(w => w.path.endsWith('/schedules')).length).toBe(1);
      expect(writes.find(w => w.path.endsWith('/schedules'))!.body).toMatchObject({ enabled: false, timezone: 'Europe/Paris', input_payload: { queue: 'priority' } });
      expect(writes.find(w => w.path.endsWith('/schedules'))!.body).not.toHaveProperty('execution_identity');
      const row = panel.locator('li').filter({ hasText: 'Queue refresh' });
      await expect(row).toContainText(locale === 'fr' ? 'En pause' : 'Paused');
      await expect(panel.locator('.ck-trig__setup')).toHaveJSProperty('open', false);
      await expect(row.getByRole('button', { name: locale === 'fr' ? 'Activer' : 'Enable', exact: true })).toBeVisible();
      const buttonSize = await row.getByRole('button').boundingBox();
      expect(buttonSize!.height).toBeLessThanOrEqual(36);
      await row.locator('.ck-trig__identity > summary').click();
      await row.getByRole('button', { name: locale === 'fr' ? 'Utiliser mes accès' : 'Use my access' }).click();
      await expect(row.locator('.ck-trig__identity > summary')).toContainText('Camille');
      expect(writes.find(w => w.body.execution_identity === 'current_user')!.body).toEqual({ execution_identity: 'current_user' });
      const remove = row.getByRole('button', { name: locale === 'fr' ? 'Retirer la délégation' : 'Remove delegation' });
      expect((await remove.boundingBox())!.height).toBeLessThanOrEqual(36);
      await expect(row).toContainText(locale === 'fr' ? 'exécutions en attente' : 'pending executions');
      expect(await panel.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      expect(await page.locator('#main-content').evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      expect((await new AxeBuilder({ page }).include('app-flow-triggers-panel').analyze()).violations).toEqual([]);
      await page.screenshot({ path: info.outputPath('schedule-setup.png'), fullPage: true });
      await remove.click();
      await expect(row.locator('.ck-trig__identity > summary')).toContainText(locale === 'fr' ? 'Aucune délégation' : 'No delegation');
      expect(writes.find(w => w.body.execution_identity === 'none')!.body).toEqual({ execution_identity: 'none' });
      await row.getByRole('button', { name: locale === 'fr' ? 'Activer' : 'Enable', exact: true }).click();
      await expect.poll(() => writes.some(w => w.path.endsWith('/schedules/new-schedule') && w.body.enabled === true)).toBe(true);
      expect(writes.find(w => w.body.enabled === true)!.body).toEqual({ enabled: true });
    });

    test(`${locale}/${theme}/${width}: webhook setup is scoped and explains signed delivery`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 1000 });
      const writes = await setup(page, locale, theme);
      await page.goto(`/systems/${systemId}/flow?lens=build`);await page.getByRole('button', { name: /Modifier le brouillon|Edit draft/ }).click();
      await expect(page.locator('app-flow-node')).toHaveCount(3);
      await page.locator('app-flow-node').filter({ hasText: 'Claim arrival' }).click();
      const panel = page.locator('app-flow-triggers-panel');
      await expect(panel).toBeVisible();
      await expect(page.locator('app-flow-trigger-controls')).toBeVisible();
      await expect(panel).not.toContainText('(cron)');
      await expect(panel).toContainText('HTTP 200');
      await panel.locator('.ck-trig__setup > summary').click();
      await expect(panel.getByRole('checkbox')).not.toBeChecked();
      await panel.getByRole('checkbox').check();
      await expect(panel).toContainText('X-Agentium-Signature');
      await panel.getByRole('textbox').fill('Claim arrival');
      await panel.getByRole('button', { name: locale === 'fr' ? 'Enregistrer en pause' : 'Save paused' }).click();
      await expect(panel.getByRole('status')).toContainText('fixture-signing-secret');
      await expect(panel.locator('.ck-trig__setup')).toHaveJSProperty('open', false);
      expect(writes.find(w => w.path.endsWith('/hooks'))!.body).toEqual({ name: 'Claim arrival', event_type: 'webhook.received', enabled: false, execution_identity: 'current_user' });
      const row = panel.locator('li').filter({ hasText: 'Claim arrival' });
      await expect(row.locator('.ck-trig__identity > summary')).toContainText('Camille');
      await row.locator('.ck-trig__identity > summary').click();
      expect(await panel.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      expect(await page.locator('#main-content').evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      expect((await new AxeBuilder({ page }).include('app-flow-triggers-panel').analyze()).violations).toEqual([]);
      await page.screenshot({ path: info.outputPath('webhook-setup.png'), fullPage: true });
      await row.getByRole('button', { name: locale === 'fr' ? 'Retirer la délégation' : 'Remove delegation' }).click();
      await expect(row.locator('.ck-trig__identity > summary')).toContainText(locale === 'fr' ? 'Aucune délégation' : 'No delegation');
      expect(writes.find(w => w.body.execution_identity === 'none')!.body).toEqual({ execution_identity: 'none' });
    });
  }
});
