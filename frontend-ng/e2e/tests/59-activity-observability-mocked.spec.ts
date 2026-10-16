import { expect, test, type Page, type Route } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/** Browser contract fixture only: no broker, worker, durable DB or real cancellation is exercised. */
test.use({ serviceWorkers: 'block', video: 'off', ignoreHTTPSErrors: false });
const workspace = { id: 'activity-qa', slug: 'activity-qa', name: 'Activity QA', role: 'owner', role_template: 'workspace_owner', settings: {} };
const activity = { id: 'activity-1', kind: 'compute_run', native_id: 'native-compute-1', workspace_id: workspace.id, system_id: 'system-1', run_id: 'run-1', parent_activity_id: null,
  status: 'running', native_status: 'running', version: 17, created_at: '2026-10-15T08:00:00Z', started_at: '2026-10-15T08:00:01Z', finished_at: null, updated_at: '2026-10-15T08:01:00Z', progress: null,
  measurements: { duration_ms: 59000, provider_cost_usd: null, cost_known: false, cpu_cores: 1, memory_mb: 512, core_hours: 0.016, reserved_core_hours: 1, resource_basis: 'requested_resources_x_wall_time', cost_basis: null },
  coverage: { events: 'observed', resources: 'allocated', cost: 'unknown' }, capabilities: { cancel: true }, links: [{ rel: 'native', href: '/runs/run-1' }] };

async function fixture(page: Page, locale = 'fr', enabled = true, platform = false) {
  const commands: Record<string, unknown>[] = []; const listQueries: URLSearchParams[] = [];
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.continue() : route.fulfill({ status: 204, body: '' }));
  await page.addInitScript(({ slug, locale }) => {
    localStorage.setItem('agentium_token', 'Bearer isolated-observability-fixture');
    localStorage.setItem('agentium_workspace_slug', slug); localStorage.setItem('agentium_locale', locale); localStorage.setItem('agentium_theme', locale === 'fr' ? 'dark' : 'light');
    const original = window.fetch.bind(window);
    // Keep an authenticated fetch stream open and controllable. This fixture does not pretend to qualify a real SSE server.
    (window as any).__activityStreams = [];
    window.fetch = async (url, init) => {
      if (!String(url).includes('/observability/activity-events/stream')) return original(url, init);
      const encoder = new TextEncoder(); let timer: ReturnType<typeof setInterval>;
      const stream = new ReadableStream({ start(controller) {
        const send = (event: string, value: unknown, id = 'cursor-17') => controller.enqueue(encoder.encode(`id: ${id}\nevent: ${event}\ndata: ${JSON.stringify(value)}\n\n`));
        (window as any).__activityStreams.push({ headers: Object.fromEntries(new Headers(init?.headers)), send, close: () => { clearInterval(timer); controller.close(); } });
        send('snapshot', { cursor: 'cursor-17' }); timer = setInterval(() => send('heartbeat', { cursor: 'cursor-17' }), 1000);
        init?.signal?.addEventListener('abort', () => { clearInterval(timer); try { controller.close(); } catch { /* closed */ } });
      }, cancel() { clearInterval(timer); } });
      return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } });
    };
  }, { slug: workspace.slug, locale });
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/v1/**', async route => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa', role: 'member', email: 'qa@example.test' });
    if (path === '/auth/me') return json(route, { id: 'qa', role: 'member', email: 'qa@example.test', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === '/auth/workspaces/' + workspace.slug) return json(route, workspace);
    if (path === '/observability/activities/features') return json(route, { enabled, scopes: ['workspace', 'system', ...(platform ? ['platform'] : [])], kinds: ['run', 'compute_run'], statuses: ['pending', 'running', 'succeeded', 'failed'] });
    if (path === '/observability/activities') {
      listQueries.push(url.searchParams); const offset = Number(url.searchParams.get('offset') || '0');
      return json(route, { items: [{ ...activity, native_id: offset ? 'native-compute-26' : activity.native_id }], total: 317, offset, limit: 25, has_more: offset < 300, snapshot_cursor: 'cursor-17', aggregates: { total: 317, by_kind: { compute_run: 317 }, by_status: { running: 317 } } });
    }
    if (path === '/observability/activities/activity-1') return json(route, { ...activity, capabilities: { cancel: !commands.length }, attempts: [], events: [], evidence: [], commands: commands.length ? [{ id: 'cmd-1', activity_id: activity.id, action: 'cancel', status: 'applied', created_at: activity.created_at, error_code: null }] : [] });
    if (path === '/observability/activities/activity-1/commands') {
      commands.push(request.postDataJSON()); return json(route, { id: 'cmd-1', activity_id: activity.id, action: 'cancel', status: 'requested', created_at: activity.created_at, error_code: null }, 202);
    }
    if (path === '/observability/activity-events') return json(route, { items: [], next_cursor: 'cursor-17', has_more: false });
    if (path === '/observability/platform-overview') return json(route, { generated_at: activity.created_at, resources: { active: 2, reserved_cpu: 3, reserved_memory_mb: 4096, unreconciled: 1, limits: { slots: 4, cpu: 4, memory_mb: 8192 } }, aggregates: { total: 900, by_status: { running: 900 }, by_kind: { compute_run: 900 } }, workspaces: [{ workspace_id: 'other-workspace', aggregates: { total: 583, by_status: { running: 583 }, by_kind: { compute_run: 583 } } }] });
    if (path === '/observability/workspace-overview') return json(route, null);
    return json(route, request.method() === 'GET' && path.endsWith('s') ? [] : {});
  });
  return { commands, listQueries };
}

test.describe('Activity observability — isolated browser fixture', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_ACTIVITY_OBSERVABILITY_FIXTURE'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local fixture only; no production API or broker.');
  });
  for (const [locale, width] of [['fr', 1440], ['en', 390]] as const) {
    test(`${locale}/${width}: exact totals, scoped filters, native evidence and cancellation request`, async ({ page }, info) => {
      const { commands, listQueries } = await fixture(page, locale); const en = locale === 'en';
      await page.setViewportSize({ width, height: 1000 }); await page.goto('/observability?facet=activities&systemId=system-1&since=30d');
      const monitor = page.getByTestId('activity-monitor'); await expect(monitor).toBeVisible();
      await expect(monitor.getByText('317', { exact: true }).first()).toBeVisible();
      expect(listQueries.at(-1)?.get('system_id')).toBe('system-1');
      await expect(monitor.getByRole('button', { name: en ? 'Platform' : 'Plateforme', exact: true })).toHaveCount(0);
      await monitor.getByRole('button', { name: /native-compute-1/ }).click();
      const detail = page.getByTestId('activity-detail'); await expect(detail).toBeVisible();
      await expect(detail.getByRole('link', { name: en ? 'Open native detail' : 'Ouvrir le détail natif' }).first()).toHaveAttribute('href', '/runs/run-1');
      await expect(detail).toContainText(en ? 'Not measured' : 'Non mesuré');
      await detail.getByRole('button', { name: en ? 'Request cancellation' : 'Demander l’annulation', exact: true }).click();
      await detail.getByRole('button', { name: en ? 'Confirm request' : 'Confirmer la demande', exact: true }).click();
      await expect(page.getByTestId('activity-command')).toContainText(en ? 'Sent to engine' : 'Transmise au moteur');
      await expect(detail.locator('.badge').first()).toHaveText(en ? 'Running' : 'En cours');
      expect(commands).toHaveLength(1); expect(commands[0]['expected_version']).toBe(17); expect(commands[0]['idempotency_key']).toBeTruthy();
      expect((await new AxeBuilder({ page }).include('[data-testid="activity-monitor"]').analyze()).violations).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: info.outputPath(`activities-${locale}-${width}.png`), fullPage: true });
      await detail.getByRole('button', { name: en ? 'Close' : 'Fermer', exact: true }).click();
      await monitor.getByRole('button', { name: en ? 'Next' : 'Suivant', exact: true }).click();
      await expect(monitor).toContainText('native-compute-26'); expect(listQueries.at(-1)?.get('offset')).toBe('25');
    });
  }
  test('revocation clears an open activity and a disconnected stream resumes its cursor', async ({ page }) => {
    await fixture(page); await page.goto('/observability?activityId=activity-1');
    await expect(page.getByTestId('activity-detail')).toBeVisible();
    await page.evaluate(() => { const stream = (window as any).__activityStreams.at(-1); stream.send('heartbeat', {}, 'resume-18'); stream.close(); });
    await expect.poll(() => page.evaluate(() => (window as any).__activityStreams.at(-1)?.headers['last-event-id'])).toBe('resume-18');
    await page.evaluate(() => (window as any).__activityStreams.at(-1).send('error', { code: 'ACTIVITY_ACCESS_REVOKED' }));
    await expect(page.getByTestId('activity-detail')).toHaveCount(0); await expect(page.getByTestId('activity-monitor')).toContainText('Votre accès a changé');
  });
  test('feature disabled exposes only the existing operations view', async ({ page }) => {
    await fixture(page, 'fr', false); await page.goto('/observability');
    await expect(page.locator('app-workspace-monitor')).toBeVisible(); await expect(page.getByTestId('activity-monitor')).toHaveCount(0);
  });
  test('platform aggregates require the server capability and do not expose cross-workspace activities', async ({ page }) => {
    await fixture(page, 'fr', true, true); await page.goto('/observability?scope=platform');
    await expect(page.getByTestId('activity-monitor')).toContainText('other-workspace');
    await expect(page.getByTestId('activity-monitor')).toContainText('Arrêts à confirmer');
    await expect(page.getByTestId('activity-detail')).toHaveCount(0); await expect(page.getByRole('button', { name: /native-compute/ })).toHaveCount(0);
  });
});
