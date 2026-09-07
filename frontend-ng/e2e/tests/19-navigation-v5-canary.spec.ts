import { expect, test, type Page, type TestInfo } from '@playwright/test';

/**
 * Lot 6 — navigation v5 canary (one scale per axis).
 *
 * Opt-in, same credentials posture as `10-cockpit-axes-canary`.
 * Keeps Lot 3 green while `cockpit_nav_v5` is explicitly off; this file
 * exercises the graduated grammar (`?facet=`, no `?scope=`).
 *
 *   E2E_LOT6_CANARY=1 E2E_USERNAME=... E2E_PASSWORD=...
 */

const canaryEnabled = process.env['E2E_LOT6_CANARY'] === '1' || process.env['E2E_LOT3_CANARY'] === '1';
const username = process.env['E2E_USERNAME'];
const password = process.env['E2E_PASSWORD'];
const showcaseSlug = process.env['E2E_LOT3_SHOWCASE_SLUG'] ?? 'agentium-showcase';

test.use({ trace: 'off', video: 'off', screenshot: 'off' });

interface WorkspaceSummary {
  slug: string;
  settings?: Record<string, unknown>;
}

interface CapabilityRow {
  id: string;
  slug: string;
  name: string;
}

interface SystemRow {
  id: string;
  name: string;
  capability_id?: string | null;
}

interface RunRow {
  id: string;
  system_id?: string | null;
  capability_id?: string | null;
}

interface ApiResult<T> {
  ok: boolean;
  status: number;
  body: T;
}

async function login(page: Page, workspaceSlug: string): Promise<void> {
  expect(username, 'E2E_USERNAME is required for the Lot 6 canary').toBeTruthy();
  expect(password, 'E2E_PASSWORD is required for the Lot 6 canary').toBeTruthy();
  await page.goto('/auth/signin');
  const result = await page.evaluate(
    async ({ email, secret, slug }) => {
      const response = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password: secret, remember_me: false }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || !body.token) {
        return { ok: false, status: response.status };
      }
      localStorage.setItem('agentium_token', `Bearer ${body.token}`);
      if (body.refresh_token) localStorage.setItem('agentium_refresh_token', body.refresh_token);
      localStorage.setItem('agentium_workspace_slug', slug);
      return { ok: true, status: response.status };
    },
    { email: username as string, secret: password as string, slug: workspaceSlug },
  );
  expect(result.ok, `login failed (${result.status})`).toBe(true);
}

async function api<T>(
  page: Page,
  workspaceSlug: string,
  path: string,
): Promise<ApiResult<T>> {
  return page.evaluate(
    async ({ slug, apiPath }) => {
      const authorization = localStorage.getItem('agentium_token') || '';
      const response = await fetch(`/api/v1${apiPath}`, {
        headers: {
          Authorization: authorization,
          'X-Workspace-Slug': slug,
        },
      });
      const text = await response.text();
      let body: unknown = null;
      if (text) {
        try {
          body = JSON.parse(text);
        } catch {
          body = text;
        }
      }
      return { ok: response.ok, status: response.status, body };
    },
    { slug: workspaceSlug, apiPath: path },
  ) as Promise<ApiResult<T>>;
}

function unwrap<T>(body: T[] | Record<string, T[]>, key: string): T[] {
  if (Array.isArray(body)) return body;
  return Array.isArray(body?.[key]) ? body[key] : [];
}

async function discoverShowcaseGraph(page: Page): Promise<{
  capability: CapabilityRow;
  system: SystemRow;
  run: RunRow;
}> {
  const systemsResult = await api<SystemRow[] | { systems: SystemRow[] }>(page, showcaseSlug, '/systems');
  expect(systemsResult.ok, 'Showcase Systems must be readable').toBe(true);
  const systems = unwrap(systemsResult.body, 'systems');
  for (const system of systems) {
    if (!system.capability_id) continue;
    const cap = await api<CapabilityRow>(page, showcaseSlug, `/capabilities/${system.capability_id}`);
    const runs = await api<RunRow[] | { runs: RunRow[] }>(
      page,
      showcaseSlug,
      `/runs?system_id=${encodeURIComponent(system.id)}`,
    );
    const run = unwrap(runs.body, 'runs')[0];
    if (cap.ok && run) {
      return { capability: cap.body, system, run };
    }
  }
  throw new Error('Showcase needs a System linked to a Capability and Run');
}

test.describe.serial('Lot 6 — navigation v5 canary', () => {
  test.skip(!canaryEnabled, 'Set E2E_LOT6_CANARY=1 to exercise the deployed Lot 6 canary');

  test('identity is conserved across four lenses, facets restore, drill-down keeps zone', async ({ page }, testInfo: TestInfo) => {
    await login(page, showcaseSlug);
    const workspace = await api<WorkspaceSummary>(page, showcaseSlug, `/auth/workspaces/${showcaseSlug}`);
    expect(workspace.ok).toBe(true);
    const { capability, system, run } = await discoverShowcaseGraph(page);

    await page.goto(
      `/systems/${encodeURIComponent(system.id)}?lens=operate&facet=runs&capabilityId=${encodeURIComponent(capability.id)}`,
    );
    await expect(page.locator('app-system-view')).toBeVisible();
    const breadcrumb = page.locator('app-semantic-zoom-breadcrumb');
    await expect(breadcrumb).toContainText(capability.name);
    await expect(breadcrumb).toContainText(system.name);

    const mainBox = await page.locator('main').boundingBox();
    expect(mainBox, 'canvas must have a stable box').toBeTruthy();

    for (const lens of ['build', 'operate', 'steer', 'govern'] as const) {
      await page.goto(
        `/systems/${encodeURIComponent(system.id)}?lens=${lens}&facet=runs&capabilityId=${encodeURIComponent(capability.id)}`,
      );
      await expect(page.locator('app-system-view')).toBeVisible();
      expect(new URL(page.url()).searchParams.get('lens')).toBe(lens === 'build' ? null : lens);
      expect(new URL(page.url()).pathname).toBe(`/systems/${system.id}`);
      expect(new URL(page.url()).searchParams.get('facet')).toBe('runs');
    }

    await page.goto(`/runs/${encodeURIComponent(run.id)}?lens=operate`);
    await expect(page.locator('app-run-view')).toBeVisible();
    await expect(breadcrumb).toContainText(system.name);
    const afterRun = await page.locator('main').boundingBox();
    if (mainBox && afterRun) {
      expect(Math.abs(afterRun.x - mainBox.x)).toBeLessThan(8);
    }

    await page.goBack();
    await expect(page.locator('app-system-view')).toBeVisible();
    expect(new URL(page.url()).searchParams.get('facet')).toBe('runs');
    await page.goForward();
    await expect(page.locator('app-run-view')).toBeVisible();

    await page.reload();
    await expect(page.locator('app-run-view')).toBeVisible();
    expect(new URL(page.url()).searchParams.get('lens')).toBe('operate');

    const screenshot = testInfo.outputPath('lot6-navigation-v5-canary.png');
    await page.screenshot({ path: screenshot, animations: 'disabled' });
    await testInfo.attach('lot6-navigation-v5-canary', { path: screenshot, contentType: 'image/png' });
  });
});
