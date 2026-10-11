import { expect, test, type Page, type TestInfo } from '@playwright/test';

/**
 * Lot 3 — ordered live canary for routed cockpit axes.
 *
 * The suite is opt-in and serial by design: the visible Showcase must pass
 * before the internal standard workspace is allowed to run. The second step
 * temporarily enables the feature and creates one System + Run, then restores
 * settings and deletes the System in `finally`.
 *
 * Required:
 *   E2E_LOT3_CANARY=1 E2E_USERNAME=... E2E_PASSWORD=...
 * Full two-stage gate:
 *   E2E_LOT3_INTERNAL_CANARY=1 E2E_LOT3_INTERNAL_WORKSPACE_SLUG=acme
 *
 * Traces and videos are disabled because the login request contains live
 * credentials. Credentials and tokens never leave process/browser memory.
 */

const canaryEnabled = process.env['E2E_LOT3_CANARY'] === '1';
const internalCanaryEnabled = process.env['E2E_LOT3_INTERNAL_CANARY'] === '1';
const username = process.env['E2E_USERNAME'];
const password = process.env['E2E_PASSWORD'];
const showcaseSlug = process.env['E2E_LOT3_SHOWCASE_SLUG'] ?? 'agentium-showcase';
const internalSlug = process.env['E2E_LOT3_INTERNAL_WORKSPACE_SLUG'] ?? 'acme';

test.use({ trace: 'off', video: 'off', screenshot: 'off' });

interface WorkspaceSummary {
  slug: string;
  role?: string;
  role_template?: string | null;
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
  status?: string;
}

interface ApiResult<T> {
  ok: boolean;
  status: number;
  body: T;
}

async function login(page: Page, workspaceSlug: string): Promise<WorkspaceSummary[]> {
  expect(username, 'E2E_USERNAME is required for the Lot 3 canary').toBeTruthy();
  expect(password, 'E2E_PASSWORD is required for the Lot 3 canary').toBeTruthy();
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
        return { ok: false, status: response.status, workspaces: [] };
      }
      localStorage.setItem('agentium_token', `Bearer ${body.token}`);
      if (body.refresh_token) localStorage.setItem('agentium_refresh_token', body.refresh_token);
      localStorage.setItem('agentium_workspace_slug', slug);
      const memberships = await fetch('/api/v1/auth/workspaces', {
        headers: {
          Authorization: `Bearer ${body.token}`,
          'X-Workspace-Slug': slug,
        },
      });
      return {
        ok: memberships.ok,
        status: memberships.status,
        workspaces: memberships.ok ? await memberships.json().catch(() => []) : [],
      };
    },
    { email: username as string, secret: password as string, slug: workspaceSlug },
  );
  expect(result.ok, `login or workspace discovery failed (${result.status})`).toBe(true);
  const workspaces = (Array.isArray(result.workspaces) ? result.workspaces : []) as WorkspaceSummary[];
  expect(workspaces.some((workspace) => workspace.slug === workspaceSlug)).toBe(true);
  return workspaces;
}

async function api<T>(
  page: Page,
  workspaceSlug: string,
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<ApiResult<T>> {
  return page.evaluate(
    async ({ slug, apiPath, method, payload }) => {
      const authorization = localStorage.getItem('agentium_token') || '';
      const response = await fetch(`/api/v1${apiPath}`, {
        method,
        headers: {
          Authorization: authorization,
          'X-Workspace-Slug': slug,
          ...(payload === undefined ? {} : { 'Content-Type': 'application/json' }),
        },
        ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
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
    {
      slug: workspaceSlug,
      apiPath: path,
      method: options.method ?? 'GET',
      payload: options.body,
    },
  ) as Promise<ApiResult<T>>;
}

function unwrap<T>(body: T[] | Record<string, T[]>, key: string): T[] {
  if (Array.isArray(body)) return body;
  return Array.isArray(body?.[key]) ? body[key] : [];
}

function features(settings: Record<string, unknown> | undefined): Record<string, unknown> {
  const value = settings?.['features'];
  return value && typeof value === 'object' && !Array.isArray(value)
    ? { ...(value as Record<string, unknown>) }
    : {};
}

async function discoverShowcaseGraph(page: Page): Promise<{
  capability: CapabilityRow;
  system: SystemRow;
  run: RunRow;
}> {
  const systemsResult = await api<SystemRow[] | { systems: SystemRow[] }>(
    page,
    showcaseSlug,
    '/systems',
  );
  expect(systemsResult.ok, 'Showcase Systems must be readable').toBe(true);
  const systems = unwrap(systemsResult.body, 'systems').filter(
    (row): row is SystemRow & { capability_id: string } => Boolean(row.capability_id),
  );
  expect(systems.length, 'Showcase needs a System linked to a Capability').toBeGreaterThan(0);

  const capabilityResult = await api<CapabilityRow[] | { capabilities: CapabilityRow[] }>(
    page,
    showcaseSlug,
    '/capabilities',
  );
  expect(capabilityResult.ok, 'Showcase capabilities must be readable').toBe(true);
  const capabilitiesById = new Map(
    unwrap(capabilityResult.body, 'capabilities').map((capability) => [capability.id, capability]),
  );

  for (const system of systems) {
    const capability = capabilitiesById.get(system.capability_id);
    if (!capability) continue;

    const runsResult = await api<RunRow[] | { runs: RunRow[] }>(
      page,
      showcaseSlug,
      `/runs?system_id=${encodeURIComponent(system.id)}&capability_id=${encodeURIComponent(capability.id)}&limit=1`,
    );
    expect(runsResult.ok, 'System-scoped Showcase Runs must be readable').toBe(true);
    const run = unwrap(runsResult.body, 'runs').find((row) => row.system_id === system.id);
    if (!run) continue;

    const scopedSystemsResult = await api<SystemRow[] | { systems: SystemRow[] }>(
      page,
      showcaseSlug,
      `/systems?capability_id=${encodeURIComponent(capability.id)}`,
    );
    expect(scopedSystemsResult.ok, 'Capability-scoped Showcase Systems must be readable').toBe(true);
    expect(
      unwrap(scopedSystemsResult.body, 'systems').some((row) => row.id === system.id),
      'discovered Showcase System must remain visible in its Capability scope',
    ).toBe(true);
    return { capability, system, run };
  }

  throw new Error('Showcase needs a real System → Capability → Run graph for the routed-axes canary');
}

async function expectRealBreadcrumb(
  page: Page,
  capability: CapabilityRow,
  system: SystemRow,
  run?: RunRow,
): Promise<void> {
  const breadcrumb = page.locator('app-semantic-zoom-breadcrumb');
  await expect(breadcrumb).toBeVisible();
  await expect(breadcrumb).toContainText(capability.name);
  await expect(breadcrumb).toContainText(system.name);
  if (run) await expect(breadcrumb).toContainText(run.id.slice(0, 12));
}

async function logout(page: Page): Promise<void> {
  await page.evaluate(async () => {
    const refreshToken = localStorage.getItem('agentium_refresh_token');
    if (refreshToken) {
      await fetch('/api/v1/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      }).catch(() => undefined);
    }
    localStorage.removeItem('agentium_token');
    localStorage.removeItem('agentium_refresh_token');
  }).catch(() => undefined);
}

test.describe.serial('Lot 3 — Showcase then internal routed-axes canary', () => {
  test.skip(!canaryEnabled, 'Set E2E_LOT3_CANARY=1 to exercise the deployed Lot 3 canary');

  test.afterEach(async ({ page }) => logout(page));

  test('Showcase preserves identity across lenses, scopes, graph breadcrumb and history', async ({ page }, testInfo: TestInfo) => {
    await login(page, showcaseSlug);
    const workspace = await api<WorkspaceSummary>(page, showcaseSlug, `/auth/workspaces/${showcaseSlug}`);
    expect(workspace.ok).toBe(true);
    expect(features(workspace.body.settings)['cockpit_router_axes_v3']).toBe(true);
    const { capability, system, run } = await discoverShowcaseGraph(page);

    await page.goto(`/runs/${encodeURIComponent(run.id)}?lens=operate`);
    await expect(page.locator('app-run-view')).toBeVisible();
    await expectRealBreadcrumb(page, capability, system, run);

    const steer = page.locator('app-side-rail a.ck-rail-item').filter({ hasText: /Steer/i });
    await expect(steer).toBeVisible();
    await steer.click();
    await expect(page).toHaveURL(new RegExp(`/runs/${run.id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\?`));
    let url = new URL(page.url());
    expect(url.searchParams.get('lens')).toBe('steer');
    expect(url.searchParams.get('systemId')).toBe(system.id);
    expect(url.searchParams.get('capabilityId')).toBe(capability.id);

    await page.reload();
    await expectRealBreadcrumb(page, capability, system, run);
    await page.goBack();
    await expect(page.locator('app-run-view')).toBeVisible();
    expect(new URL(page.url()).searchParams.get('lens')).toBe('operate');
    await page.goForward();
    await expect(page.locator('app-run-view')).toBeVisible();
    expect(new URL(page.url()).searchParams.get('lens')).toBe('steer');

    await page.goto(`/capabilities/${encodeURIComponent(capability.id)}?lens=operate`);
    await expect(page.locator('app-capability-view')).toBeVisible();
    const systemsRequest = page.waitForRequest((request) => {
      const candidate = new URL(request.url());
      return request.method() === 'GET'
        && candidate.pathname === '/api/v1/systems'
        && candidate.searchParams.get('capability_id') === capability.id;
    });
    await page.locator('app-mini-rail a[href^="/systems"]').click();
    const scopedSystemsRequest = await systemsRequest;
    expect(scopedSystemsRequest.headers()['x-workspace-slug']).toBe(showcaseSlug);
    url = new URL(page.url());
    expect(url.pathname).toBe('/systems');
    expect(url.searchParams.get('scope')).toBe('systems');
    expect(url.searchParams.get('capabilityId')).toBe(capability.id);
    await expect(page.locator('app-systems-grid')).toBeVisible();

    await page.goto(
      `/systems/${encodeURIComponent(system.id)}?lens=operate&capabilityId=${encodeURIComponent(capability.id)}`,
    );
    await expect(page.locator('app-system-view')).toBeVisible();
    await expectRealBreadcrumb(page, capability, system);
    const runsRequest = page.waitForRequest((request) => {
      const candidate = new URL(request.url());
      return request.method() === 'GET'
        && candidate.pathname === '/api/v1/runs'
        && candidate.searchParams.get('system_id') === system.id
        && candidate.searchParams.get('capability_id') === capability.id;
    });
    await page.locator('app-mini-rail a[href^="/runs"]').click();
    const scopedRunsRequest = await runsRequest;
    expect(scopedRunsRequest.headers()['x-workspace-slug']).toBe(showcaseSlug);
    url = new URL(page.url());
    expect(url.pathname).toBe('/runs');
    expect(url.searchParams.get('scope')).toBe('runs');
    expect(url.searchParams.get('systemId')).toBe(system.id);
    expect(url.searchParams.get('capabilityId')).toBe(capability.id);
    await expect(page.locator('app-runs-list')).toBeVisible();

    const screenshot = testInfo.outputPath('lot3-showcase-canary.png');
    await page.screenshot({ path: screenshot, animations: 'disabled' });
    await testInfo.attach('lot3-showcase-canary', { path: screenshot, contentType: 'image/png' });
  });

  test('standard internal workspace passes the reduced canary with reversible data', async ({ page }) => {
    test.skip(
      !internalCanaryEnabled,
      'Set E2E_LOT3_INTERNAL_CANARY=1 after Showcase succeeds to run stage two',
    );
    const memberships = await login(page, internalSlug);
    const membership = memberships.find((workspace) => workspace.slug === internalSlug)!;
    expect(
      ['owner', 'admin', 'workspace_owner', 'workspace_admin'],
      'the internal canary requires workspace admin rights for reversible setup',
    ).toContain(membership.role_template || membership.role);

    const original = await api<WorkspaceSummary>(page, internalSlug, `/auth/workspaces/${internalSlug}`);
    expect(original.ok).toBe(true);
    const originalSettings = { ...(original.body.settings ?? {}) };
    const enabledSettings = {
      ...originalSettings,
      features: {
        ...features(originalSettings),
        cockpit_router_axes_v3: true,
      },
    };
    let system: SystemRow | null = null;
    try {
      const enabled = await api<WorkspaceSummary>(page, internalSlug, `/auth/workspaces/${internalSlug}`, {
        method: 'PATCH',
        body: { settings: enabledSettings },
      });
      expect(enabled.ok, `failed to enable internal canary (${enabled.status})`).toBe(true);

      const capabilities = await api<CapabilityRow[] | { capabilities: CapabilityRow[] }>(
        page,
        internalSlug,
        '/capabilities',
      );
      expect(capabilities.ok).toBe(true);
      const capability = unwrap(capabilities.body, 'capabilities')[0];
      expect(capability, 'the standard workspace needs one visible Capability').toBeTruthy();

      const created = await api<SystemRow>(page, internalSlug, '/systems', {
        method: 'POST',
        body: {
          name: `Lot 3 Canary ${Date.now()}`,
          objective: 'Ephemeral routed-axes acceptance canary',
          capability_id: capability.id,
          skill_ids: [],
          flow_definition: {},
          settings: { lot3_canary: true },
          status: 'active',
        },
      });
      expect(created.ok, `failed to create internal canary System (${created.status})`).toBe(true);
      system = created.body;

      const triggered = await api<RunRow>(page, internalSlug, `/systems/${system.id}/runs`, {
        method: 'POST',
        body: { trigger: 'lot3_canary', input_ref: { lot3_canary: true } },
      });
      expect(triggered.ok, `failed to trigger internal canary Run (${triggered.status})`).toBe(true);
      const run = triggered.body;

      await page.goto(`/runs/${encodeURIComponent(run.id)}?lens=operate`);
      await expect(page.locator('app-run-view')).toBeVisible();
      await expectRealBreadcrumb(page, capability, system, run);
      await page.locator('app-side-rail a.ck-rail-item').filter({ hasText: /Steer/i }).click();
      const routed = new URL(page.url());
      expect(routed.pathname).toBe(`/runs/${run.id}`);
      expect(routed.searchParams.get('lens')).toBe('steer');
      expect(routed.searchParams.get('systemId')).toBe(system.id);
      expect(routed.searchParams.get('capabilityId')).toBe(capability.id);

      await expect.poll(async () => {
        const status = await api<RunRow>(page, internalSlug, `/runs/${run.id}`);
        return status.ok ? status.body.status : `http-${status.status}`;
      }, { timeout: 30_000 }).toMatch(/completed|failed|cancelled/);
    } finally {
      // Restoring the workspace flag is the hard rollback guarantee. A failed
      // ephemeral-data cleanup must never prevent that settings restoration.
      let cleanupStatus: number | null = null;
      try {
        if (system) {
          const removed = await api<unknown>(page, internalSlug, `/systems/${system.id}`, {
            method: 'DELETE',
          });
          cleanupStatus = removed.status;
        }
      } finally {
        const restored = await api<WorkspaceSummary>(page, internalSlug, `/auth/workspaces/${internalSlug}`, {
          method: 'PATCH',
          body: { settings: originalSettings },
        });
        expect(restored.ok, `failed to restore internal settings (${restored.status})`).toBe(true);
      }
      if (cleanupStatus !== null) expect([204, 404]).toContain(cleanupStatus);
    }
  });
});
