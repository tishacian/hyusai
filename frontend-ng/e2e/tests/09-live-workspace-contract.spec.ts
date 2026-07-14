import { expect, test, type Page, type TestInfo } from '@playwright/test';

/**
 * Lot 0 — live workspace contract.
 *
 * This suite is deliberately opt-in because it reads the deployed workspace
 * through a real account. Credentials are injected through E2E_USERNAME and
 * E2E_PASSWORD and must never be committed.
 *
 * Run against production/staging:
 *   E2E_LIVE_CONTRACT=1 E2E_WORKSPACE_SLUG=andritz \
 *     E2E_USERNAME=... E2E_PASSWORD=... \
 *     npx playwright test 09-live-workspace-contract.spec.ts
 *
 * Optional existing non-admin member (no account provisioning):
 *   E2E_LIVE_NON_ADMIN=1 \
 *     E2E_BUSINESS_USERNAME=... E2E_BUSINESS_PASSWORD=...
 */

const liveContract = process.env['E2E_LIVE_CONTRACT'] === '1';
const liveAllWorkspaces = process.env['E2E_LIVE_ALL_WORKSPACES'] === '1';
const liveForceRefresh = process.env['E2E_LIVE_FORCE_REFRESH'] === '1';
const liveNonAdmin = process.env['E2E_LIVE_NON_ADMIN'] === '1';
const workspaceSlug = process.env['E2E_WORKSPACE_SLUG'] ?? 'andritz';
const username = process.env['E2E_USERNAME'];
const password = process.env['E2E_PASSWORD'];
const businessUsername = process.env['E2E_BUSINESS_USERNAME'];
const businessPassword = process.env['E2E_BUSINESS_PASSWORD'];
const previewStorageKey = 'agentium_business_navigation_preview_slugs';

// A Playwright trace records network postData, including the login request.
// Live credentials must never be serialized into retained failure artifacts.
test.use({ trace: 'off', video: 'off' });

type LoginResult = {
  ok: boolean;
  status: number;
  workspaceSlug?: string | null;
  workspaces?: Array<{ slug?: string; role?: string; roleTemplate?: string | null }>;
  detail?: unknown;
};

type LoginCredentials = {
  username?: string;
  password?: string;
};

async function login(
  page: Page,
  businessPreview: boolean,
  targetWorkspaceSlug = workspaceSlug,
  rememberMe = false,
  credentials: LoginCredentials = { username, password },
): Promise<LoginResult> {
  expect(credentials.username, 'a username is required for the live contract').toBeTruthy();
  expect(credentials.password, 'a password is required for the live contract').toBeTruthy();

  await page.goto('/auth/signin');
  const result = await page.evaluate(
    async ({ email, secret, slug, previewKey, preview, persistSession }) => {
      const response = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password: secret, remember_me: persistSession }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || !body.token) {
        return { ok: false, status: response.status, detail: body.detail ?? body };
      }

      localStorage.setItem('agentium_token', `Bearer ${body.token}`);
      if (body.refresh_token) {
        localStorage.setItem('agentium_refresh_token', body.refresh_token);
      }
      localStorage.setItem('agentium_workspace_slug', slug);
      localStorage.setItem(previewKey, JSON.stringify(preview ? [slug] : []));

      const workspacesResponse = await fetch('/api/v1/auth/workspaces', {
        headers: {
          Authorization: `Bearer ${body.token}`,
          'X-Workspace-Slug': slug,
        },
      });
      const workspaces = workspacesResponse.ok
        ? await workspacesResponse.json().catch(() => [])
        : [];

      return {
        ok: true,
        status: response.status,
        workspaceSlug: body.workspace_slug ?? null,
        workspaces: Array.isArray(workspaces)
          ? workspaces.map((workspace: {
              slug?: string;
              role?: string;
              role_template?: string | null;
            }) => ({
              slug: workspace.slug,
              role: workspace.role,
              roleTemplate: workspace.role_template,
            }))
          : [],
      };
    },
    {
      email: credentials.username as string,
      secret: credentials.password as string,
      slug: targetWorkspaceSlug,
      previewKey: previewStorageKey,
      preview: businessPreview,
      persistSession: rememberMe,
    },
  );

  expect(result.ok, `login failed with status ${result.status}`).toBe(true);
  expect(result.workspaces?.some((workspace) => workspace.slug === targetWorkspaceSlug)).toBe(true);
  return result;
}

async function attachViewport(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  const path = testInfo.outputPath(name);
  await page.screenshot({ path, animations: 'disabled' });
  await testInfo.attach(name, { path, contentType: 'image/png' });
}

test.describe('Lot 0 — live workspace experience contract', () => {
  test.skip(!liveContract, 'Set E2E_LIVE_CONTRACT=1 to exercise the deployed workspace');

  test.afterEach(async ({ page }) => {
    const refreshToken = await page
      .evaluate(() => localStorage.getItem('agentium_refresh_token'))
      .catch(() => null);
    if (!refreshToken) return;

    const logout = await page.request.post('/api/v1/auth/logout', {
      data: { refresh_token: refreshToken },
    });
    expect(logout.ok(), 'the renewable E2E session must be revoked after the test').toBe(true);
    await page.evaluate(() => {
      localStorage.removeItem('agentium_token');
      localStorage.removeItem('agentium_refresh_token');
    });
  });

  test('Andritz business preview exposes exactly the three active apps', async ({ page }, testInfo) => {
    await login(page, true);
    await page.goto('/chat');

    const businessNav = page.getByRole('navigation', { name: 'Navigation métier' });
    await expect(businessNav).toBeVisible();
    const links = businessNav.getByRole('link');
    await expect(links).toHaveCount(3);
    await expect(businessNav.getByRole('link', { name: 'Recherche' })).toHaveAttribute('href', '/chat');
    await expect(businessNav.getByRole('link', { name: 'Client360 PDR' })).toHaveAttribute('href', '/client360');
    await expect(businessNav.getByRole('link', { name: 'Capture de connaissances' })).toHaveAttribute(
      'href',
      '/knowledge/capture',
    );
    await expect(page.locator('app-side-rail')).toHaveCount(0);

    await page.reload();
    await expect(businessNav).toBeVisible();
    await expect(page).toHaveURL(/\/chat(?:[?#].*)?$/);
    await attachViewport(page, testInfo, 'andritz-business-shell.png');
  });

  test('the three Andritz apps survive deep links, history and reload', async ({ page }, testInfo) => {
    await login(page, true);

    const workspaceHeaders: Array<string | undefined> = [];
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.origin === new URL(page.url()).origin && url.pathname.startsWith('/api/v1/')) {
        const headers = request.headers();
        if (headers['authorization']?.startsWith('Bearer ')) {
          workspaceHeaders.push(headers['x-workspace-slug']);
        }
      }
    });

    await page.goto('/chat');
    await expect(page.locator('app-chat-workspace')).toBeVisible();
    await attachViewport(page, testInfo, 'andritz-recherche.png');

    await page.goto('/client360');
    await expect(page.locator('app-client360-page')).toBeVisible();
    await expect(page.locator('body')).toContainText('Client360 PDR');
    await attachViewport(page, testInfo, 'andritz-client360.png');

    await page.goto('/knowledge/capture');
    await expect(page.locator('app-capture-router')).toBeVisible();
    await expect(page.locator('body')).toContainText(/Capture de connaissances|Capture expert/);
    await attachViewport(page, testInfo, 'andritz-knowledge-capture.png');

    await page.reload();
    await expect(page).toHaveURL(/\/knowledge\/capture(?:[?#].*)?$/);
    await page.goBack();
    await expect(page).toHaveURL(/\/client360(?:[?#].*)?$/);
    await page.goBack();
    await expect(page).toHaveURL(/\/chat(?:[?#].*)?$/);
    await page.goForward();
    await expect(page).toHaveURL(/\/client360(?:[?#].*)?$/);

    expect(workspaceHeaders.length, 'no authenticated API request carried a workspace header').toBeGreaterThan(0);
    expect(workspaceHeaders.every((slug) => slug === workspaceSlug)).toBe(true);
  });

  test('a forced access-token expiry retries inside the selected workspace', async ({ page }) => {
    test.skip(
      !liveForceRefresh,
      'Set E2E_LIVE_FORCE_REFRESH=1 on a candidate deployment that includes the scoped retry fix',
    );
    await login(page, true, workspaceSlug, true);
    await page.goto('/chat');
    await expect(page.getByRole('navigation', { name: 'Navigation métier' })).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => Boolean(localStorage.getItem('agentium_refresh_token'))))
      .toBe(true);

    type ObservedResponse = {
      path: string;
      status: number;
      authKind: 'bearer' | 'other' | 'none';
      wasForced: boolean;
      workspace: string | undefined;
    };
    const observed: ObservedResponse[] = [];
    const forcedAuthorization = 'Bearer lot0-forced-expired-token';
    let refreshAttempts = 0;
    let capture = false;
    page.on('request', (request) => {
      if (!capture) return;
      const url = new URL(request.url());
      if (url.origin === new URL(page.url()).origin && url.pathname === '/api/v1/auth/refresh') {
        refreshAttempts += 1;
      }
    });
    page.on('response', (response) => {
      if (!capture) return;
      const url = new URL(response.url());
      if (url.origin !== new URL(page.url()).origin || !url.pathname.startsWith('/api/v1/')) return;
      const headers = response.request().headers();
      const authorization = headers['authorization'];
      observed.push({
        path: url.pathname,
        status: response.status(),
        authKind: authorization?.startsWith('Bearer ')
          ? 'bearer'
          : authorization
            ? 'other'
            : 'none',
        wasForced: authorization === forcedAuthorization,
        workspace: headers['x-workspace-slug'],
      });
    });

    await page.evaluate(
      (forcedToken) => localStorage.setItem('agentium_token', forcedToken),
      forcedAuthorization,
    );
    capture = true;
    await page.getByRole('link', { name: 'Client360 PDR' }).click();

    await expect(page).toHaveURL(/\/client360(?:[?#].*)?$/);
    await expect(page.locator('app-client360-page')).toBeVisible();
    await expect
      .poll(() => observed.some((entry) => entry.path === '/api/v1/auth/refresh' && entry.status === 200))
      .toBe(true);
    await expect.poll(() => refreshAttempts).toBe(1);
    await expect
      .poll(
        () => {
          const paths = new Set(
            observed
              .filter(
                (entry) =>
                  entry.path.startsWith('/api/v1/client360/') &&
                  entry.wasForced &&
                  entry.status === 401,
              )
              .map((entry) => entry.path),
          );
          return paths.size > 0 && [...paths].every(
            (path) => observed.some(
              (entry) =>
                entry.path === path &&
                !entry.wasForced &&
                entry.authKind === 'bearer' &&
                entry.status === 200,
            ),
          );
        },
        { message: 'each forced Client360 401 must settle through a bearer retry' },
      )
      .toBe(true);
    // Let late 401 responses settle before asserting the terminal refresh
    // count; a second rotation must not arrive after the first 200 response.
    await page.waitForTimeout(750);
    expect(refreshAttempts, 'all concurrent 401 responses must share exactly one refresh attempt').toBe(1);

    const forcedTokenResponses = observed.filter(
      (entry) =>
        entry.path.startsWith('/api/v1/client360/') &&
        entry.wasForced,
    );
    const expiredResponses = forcedTokenResponses.filter((entry) => entry.status === 401);
    const expiredPaths = new Set(expiredResponses.map((entry) => entry.path));
    const retryResponses = observed.filter(
      (entry) =>
        expiredPaths.has(entry.path) &&
        !entry.wasForced,
    );
    expect(expiredResponses.length, 'the forced token did not trigger an authenticated failure').toBeGreaterThan(0);
    expect(
      forcedTokenResponses.every((entry) => entry.status === 401),
      'an invalid access token must fail closed with 401, never 5xx',
    ).toBe(true);
    expect(
      forcedTokenResponses.every((entry) => entry.workspace === workspaceSlug),
      'every forced request must stay in the selected workspace',
    ).toBe(true);
    expect(retryResponses.length, 'no Client360 request was retried after token refresh').toBeGreaterThan(0);
    expect(
      retryResponses.every((entry) => entry.authKind === 'bearer'),
      'every replay must use a bearer without retaining its value in the test report',
    ).toBe(true);
    expect(
      retryResponses.every((entry) => entry.workspace === workspaceSlug),
      'every retried request must stay in the selected workspace',
    ).toBe(true);
    expect(
      retryResponses.every((entry) => entry.status === 200),
      'every replay with the refreshed bearer must succeed',
    ).toBe(true);
    for (const path of expiredPaths) {
      expect(
        retryResponses.some((entry) => entry.path === path && entry.status === 200),
        `${path} did not complete its 401 → 200 retry`,
      ).toBe(true);
    }
    await expect
      .poll(() => page.evaluate(
        (forcedToken) => localStorage.getItem('agentium_token') !== forcedToken,
        forcedAuthorization,
      ))
      .toBe(true);
  });

  test('business preview redirects advanced routes while admin mode keeps the full cockpit', async ({ page }) => {
    await login(page, true);
    await page.goto('/systems');
    await expect(page).toHaveURL(/\/chat(?:[?#].*)?$/);
    await expect(page.getByRole('navigation', { name: 'Navigation métier' })).toBeVisible();

    await page.evaluate((previewKey) => localStorage.setItem(previewKey, '[]'), previewStorageKey);
    await page.goto('/systems');
    await expect(page).toHaveURL(/\/systems(?:[?#].*)?$/);
    await expect(page.locator('app-side-rail')).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Navigation métier' })).toHaveCount(0);
  });

  test('a non-admin member gets the three-app shell without preview', async ({ page }) => {
    test.skip(!liveNonAdmin, 'Set E2E_LIVE_NON_ADMIN=1 to exercise an existing business member');
    expect(
      businessUsername,
      'E2E_BUSINESS_USERNAME is required when E2E_LIVE_NON_ADMIN=1',
    ).toBeTruthy();
    expect(
      businessPassword,
      'E2E_BUSINESS_PASSWORD is required when E2E_LIVE_NON_ADMIN=1',
    ).toBeTruthy();

    const loginResult = await login(page, false, workspaceSlug, false, {
      username: businessUsername,
      password: businessPassword,
    });
    const membership = loginResult.workspaces?.find(
      (workspace) => workspace.slug === workspaceSlug,
    );
    expect(membership).toBeDefined();
    expect(membership?.role).toBe('member');
    expect(['owner', 'admin']).not.toContain(membership?.role);
    expect(['workspace_owner', 'workspace_admin']).not.toContain(membership?.roleTemplate);
    expect(
      await page.evaluate((previewKey) => localStorage.getItem(previewKey), previewStorageKey),
    ).toBe('[]');

    await page.goto('/systems');
    await expect(page).toHaveURL(/\/chat(?:[?#].*)?$/);

    const businessNav = page.getByRole('navigation', { name: 'Navigation métier' });
    await expect(businessNav).toBeVisible();
    const links = businessNav.getByRole('link');
    await expect(links).toHaveCount(3);
    expect(
      await links.evaluateAll((items) =>
        items.map((item) => ({
          name: item.getAttribute('aria-label'),
          href: item.getAttribute('href'),
        })),
      ),
    ).toEqual([
      { name: 'Recherche', href: '/chat' },
      { name: 'Client360 PDR', href: '/client360' },
      { name: 'Capture de connaissances', href: '/knowledge/capture' },
    ]);
    await expect(page.getByRole('button', { name: 'Mode avancé' })).toHaveCount(0);
    await expect(page.locator('app-side-rail')).toHaveCount(0);
  });

  test('deployed Andritz profile, IAM flags and active Systems match the Lot 0 baseline', async ({ page }) => {
    await login(page, false);
    const baseline = await page.evaluate(async (slug) => {
      const token = localStorage.getItem('agentium_token') ?? '';
      const headers = { Authorization: token, 'X-Workspace-Slug': slug };
      const [workspaceResponse, iamResponse, systemsResponse] = await Promise.all([
        fetch(`/api/v1/auth/workspaces/${encodeURIComponent(slug)}`, { headers }),
        fetch('/api/v1/iam/summary', { headers }),
        fetch('/api/v1/systems', { headers }),
      ]);
      const workspace = await workspaceResponse.json().catch(() => ({}));
      const iam = await iamResponse.json().catch(() => ({}));
      const systemsBody = await systemsResponse.json().catch(() => []);
      const systems = Array.isArray(systemsBody) ? systemsBody : systemsBody.systems ?? [];
      return {
        statuses: [workspaceResponse.status, iamResponse.status, systemsResponse.status],
        mode: workspace.mode,
        navigationProfile: workspace.settings?.navigation_profile,
        iam: iam.config,
        activeSystems: systems
          .filter((system: { status?: string }) => system.status === 'active')
          .map((system: { name?: string; flow_definition?: { variant?: string } }) => ({
            name: system.name,
            variant: system.flow_definition?.variant,
          })),
      };
    }, workspaceSlug);

    expect(baseline.statuses).toEqual([200, 200, 200]);
    expect(baseline.mode).toBe('builder');
    expect(baseline.navigationProfile).toEqual({
      key: 'business_end_user',
      default_route: '/chat',
      primary_surfaces: ['chat', 'client360-pdr', 'knowledge-capture'],
      advanced_access: 'admin_only',
    });
    expect(baseline.iam).toEqual({
      version: 3,
      role_flags: {
        contributors_see_only_own_sessions: true,
        reviewers_inherit_contributor: true,
        require_second_eye_for_ingestion: false,
      },
      capability_overrides: {},
    });
    expect(baseline.activeSystems).toHaveLength(5);
    expect(
      new Set(
        baseline.activeSystems.map((system: { name?: string }) => system.name),
      ).size,
      'the five active Andritz Systems must have unique names',
    ).toBe(5);
    expect(
      new Map(
        baseline.activeSystems.map((system: { name?: string; variant?: string }) => [
          system.name,
          system.variant,
        ]),
      ),
    ).toEqual(
      new Map([
        ['Andritz Workspace Chat', 'chat_transverse_v1'],
        ['Andritz Chat Agentic', 'chat_agentic_thinking_v1'],
        ['Andritz Expert Knowledge Capture System', 'expert_knowledge_capture'],
        ['Client360 PDR', 'client360_pdr'],
        ['News Lab', 'intelligence'],
      ]),
    );
  });

  test('resolved navigation is persisted with canonical routes and no user identity', async ({ page }) => {
    await login(page, false);

    type NavigationAuditLog = {
      id?: string;
      details?: {
        requested_route?: string;
        resolved_route?: string;
      };
    };

    const initialAudit = await page.evaluate(async (slug) => {
      const token = localStorage.getItem('agentium_token') ?? '';
      const response = await fetch('/api/v1/audit?event_type=navigation.resolved&limit=25', {
        headers: { Authorization: token, 'X-Workspace-Slug': slug },
      });
      const body = await response.json().catch(() => ({}));
      return {
        status: response.status,
        ids: response.ok
          ? (Array.isArray(body.logs) ? body.logs : [])
              .map((entry: NavigationAuditLog) => entry.id)
              .filter((id: string | undefined): id is string => Boolean(id))
          : [],
      };
    }, workspaceSlug);
    expect(initialAudit.status, 'the initial navigation audit read must be authorized').toBe(200);
    const existingIds = initialAudit.ids;

    await page.goto('/workspace');
    await expect(page).toHaveURL(/\/workspace\/andritz\/settings(?:[?#].*)?$/);

    await expect
      .poll(
        async () =>
          page.evaluate(async ({ slug, priorIds }) => {
            const token = localStorage.getItem('agentium_token') ?? '';
            const response = await fetch(
              '/api/v1/audit?event_type=navigation.resolved&limit=25',
              {
                headers: {
                  Authorization: token,
                  'X-Workspace-Slug': slug,
                },
              },
            );
            if (!response.ok) return false;
            const body = await response.json().catch(() => ({}));
            const logs = Array.isArray(body.logs) ? body.logs : [];
            return logs.some(
              (entry: NavigationAuditLog) =>
                Boolean(entry.id) &&
                !priorIds.includes(entry.id as string) &&
                entry.details?.requested_route === '/workspace' &&
                entry.details?.resolved_route === '/workspace/:slug/settings',
            );
          }, { slug: workspaceSlug, priorIds: existingIds }),
        {
          message: 'navigation.resolved was not persisted after the workspace redirect',
          timeout: 10_000,
        },
      )
      .toBe(true);

    // Never return the raw audit row to Playwright: a failing assertion would
    // serialize any accidental PII into the report. Only expected values and
    // structural booleans cross the browser boundary.
    const audit = await page.evaluate(async ({ slug, priorIds }) => {
      const token = localStorage.getItem('agentium_token') ?? '';
      const response = await fetch('/api/v1/audit?event_type=navigation.resolved&limit=25', {
        headers: { Authorization: token, 'X-Workspace-Slug': slug },
      });
      const body = await response.json().catch(() => ({}));
      const isRecord = (value: unknown): value is Record<string, unknown> =>
        Boolean(value) && typeof value === 'object' && !Array.isArray(value);
      const logs: Record<string, unknown>[] = Array.isArray(body.logs)
        ? body.logs.filter(
            (entry: unknown): entry is Record<string, unknown> => isRecord(entry),
          )
        : [];
      const rawLog = logs.find((entry) => {
        const details = isRecord(entry['details']) ? entry['details'] : null;
        return (
          typeof entry['id'] === 'string' &&
          !priorIds.includes(entry['id']) &&
          details?.['requested_route'] === '/workspace' &&
          details?.['resolved_route'] === '/workspace/:slug/settings'
        );
      });
      const rawDetails = rawLog && isRecord(rawLog['details']) ? rawLog['details'] : null;
      const allowedLogKeys = [
        'id',
        'timestamp',
        'event_type',
        'actor',
        'details',
        'trace_id',
        'agent_id',
        'severity',
      ];
      const allowedDetailKeys = [
        'schema_version',
        'requested_route',
        'resolved_route',
        'effective_workspace',
        'effective_surface',
        'redirect_owner',
        'redirect_reason',
        'redirected',
      ];
      const hasExactlyKeys = (
        value: Record<string, unknown> | null | undefined,
        allowed: string[],
      ): boolean => Boolean(
        value &&
        Object.keys(value).length === allowed.length &&
        Object.keys(value).every((key) => allowed.includes(key)),
      );
      const containsEmail = (value: unknown): boolean => {
        if (typeof value === 'string') {
          return /[^\s/@]+@[^\s/@]+\.[^\s/@]+/.test(value);
        }
        if (Array.isArray(value)) return value.some(containsEmail);
        return isRecord(value) && Object.values(value).some(containsEmail);
      };
      const allowExpected = <T extends string | number | boolean>(
        actual: unknown,
        expected: T,
      ): T | null => actual === expected ? expected : null;

      return {
        status: response.status,
        found: Boolean(rawLog),
        hasOnlyAllowedKeys: hasExactlyKeys(rawLog, allowedLogKeys),
        detailsHaveOnlyAllowedKeys: hasExactlyKeys(rawDetails, allowedDetailKeys),
        containsEmailLikeValue: rawLog ? containsEmail(rawLog) : false,
        projection: {
          idPresent: typeof rawLog?.['id'] === 'string' && rawLog['id'].length > 0,
          timestampPresent:
            typeof rawLog?.['timestamp'] === 'string' && rawLog['timestamp'].length > 0,
          eventType: allowExpected(rawLog?.['event_type'], 'navigation.resolved'),
          actor: allowExpected(rawLog?.['actor'], 'authenticated_user'),
          traceIdIsNull: rawLog?.['trace_id'] === null,
          agentIdIsNull: rawLog?.['agent_id'] === null,
          severity: allowExpected(rawLog?.['severity'], 'info'),
          details: {
            schemaVersion: allowExpected(rawDetails?.['schema_version'], 1),
            requestedRoute: allowExpected(rawDetails?.['requested_route'], '/workspace'),
            resolvedRoute: allowExpected(
              rawDetails?.['resolved_route'],
              '/workspace/:slug/settings',
            ),
            effectiveWorkspace: allowExpected(rawDetails?.['effective_workspace'], slug),
            effectiveSurface: allowExpected(
              rawDetails?.['effective_surface'],
              'workspace-admin',
            ),
            redirectOwner: allowExpected(
              rawDetails?.['redirect_owner'],
              'workspace_entrypoint',
            ),
            redirectReason: allowExpected(
              rawDetails?.['redirect_reason'],
              'workspace_settings_entrypoint',
            ),
            redirected: allowExpected(rawDetails?.['redirected'], true),
          },
        },
      };
    }, { slug: workspaceSlug, priorIds: existingIds });

    expect(audit.status).toBe(200);
    expect(audit.found).toBe(true);
    expect(audit.hasOnlyAllowedKeys).toBe(true);
    expect(audit.detailsHaveOnlyAllowedKeys).toBe(true);
    expect(audit.containsEmailLikeValue).toBe(false);
    expect(audit.projection).toEqual({
      idPresent: true,
      timestampPresent: true,
      eventType: 'navigation.resolved',
      actor: 'authenticated_user',
      traceIdIsNull: true,
      agentIdIsNull: true,
      severity: 'info',
      details: {
        schemaVersion: 1,
        requestedRoute: '/workspace',
        resolvedRoute: '/workspace/:slug/settings',
        effectiveWorkspace: workspaceSlug,
        effectiveSurface: 'workspace-admin',
        redirectOwner: 'workspace_entrypoint',
        redirectReason: 'workspace_settings_entrypoint',
        redirected: true,
      },
    });
  });

  test('Showcase keeps the standard Agentium cockpit', async ({ page }, testInfo) => {
    test.skip(!liveAllWorkspaces, 'Set E2E_LIVE_ALL_WORKSPACES=1 to capture cross-workspace shells');
    await login(page, false, 'agentium-showcase');
    await page.goto('/systems');

    await expect(page).toHaveURL(/\/systems(?:[?#].*)?$/);
    await expect(page.locator('app-title-bar')).toBeVisible();
    await expect(page.locator('app-side-rail')).toBeVisible();
    await expect(page.locator('app-business-shell-header')).toHaveCount(0);
    await expect(page.locator('app-mission-room')).toHaveCount(0);
    await expect
      .poll(
        () => page.locator('app-systems-grid a[href^="/systems/"]:not([href="/systems/new"])').count(),
        { timeout: 20_000 },
      )
      .toBeGreaterThan(0);
    await attachViewport(page, testInfo, 'showcase-standard-shell.png');
  });

  for (const missionRoom of [
    {
      slug: 'sentinel-ci',
      assistant: 'AYA',
      appLabel: 'SENTINEL-CI',
      brandLines: ['REPUBLIQUE DE', "COTE D'IVOIRE"],
      brandEmblem: '/assets/brand/sentinel-ci-emblem.png?v=20260518-1',
      brandStyle: 'sentinel',
      screenshot: 'sentinel-mission-room.png',
    },
    {
      slug: 'octocity-mission-room',
      assistant: 'OCTAVE',
      appLabel: 'Octocity Mission Room',
      brandLines: ['AGENTIUM', 'MISSION ROOM'],
      brandEmblem: '/assets/brand/agentium-mark.svg',
      brandStyle: 'agentium',
      screenshot: 'octocity-mission-room.png',
    },
  ]) {
    test(`${missionRoom.slug} keeps its immersive Mission Room shell`, async ({ page }, testInfo) => {
      test.skip(!liveAllWorkspaces, 'Set E2E_LIVE_ALL_WORKSPACES=1 to capture cross-workspace shells');
      await login(page, false, missionRoom.slug);
      await page.goto('/hypervisor');

      await expect(page).toHaveURL(/\/hypervisor\/mission-room\/cockpit(?:[?#].*)?$/);
      await expect(page.locator('app-mission-room')).toBeVisible();
      await expect(page.locator('app-title-bar')).toHaveCount(0);
      await expect(page.locator('app-side-rail')).toHaveCount(0);
      await expect(page.locator('body')).toContainText(missionRoom.assistant);
      await expect(page.locator('app-mission-rail .mission-nav-item')).toHaveCount(7);
      await expect(page.locator('app-mission-room .loading-panel')).toHaveCount(0, { timeout: 30_000 });
      const missionRail = page.locator('app-mission-rail .mission-rail');
      await expect(missionRail).toHaveAttribute('aria-label', `Navigation ${missionRoom.appLabel}`);
      await expect(missionRail.locator('.rail-brand')).toHaveAttribute(
        'aria-label',
        missionRoom.appLabel,
      );
      await expect(missionRail.locator('.assistant-avatar')).toHaveText(missionRoom.assistant);
      await expect(missionRail.locator('.brand-emblem')).toHaveAttribute(
        'src',
        missionRoom.brandEmblem,
      );
      for (const brandLine of missionRoom.brandLines) {
        await expect(missionRail.locator('.brand-wordmark')).toContainText(brandLine);
      }
      if (missionRoom.brandStyle === 'agentium') {
        await expect(missionRail).toHaveClass(/agentium-brand/);
      } else {
        await expect(missionRail).not.toHaveClass(/agentium-brand/);
      }

      const binding = await page.evaluate(async (slug) => {
        const token = localStorage.getItem('agentium_token') ?? '';
        const headers = { Authorization: token, 'X-Workspace-Slug': slug };
        const [navigationResponse, systemsResponse] = await Promise.all([
          fetch('/api/v1/mission-room/navigation', { headers }),
          fetch('/api/v1/systems', { headers }),
        ]);
        const navigation = await navigationResponse.json().catch(() => ({}));
        const systemsBody = await systemsResponse.json().catch(() => []);
        const systems = Array.isArray(systemsBody) ? systemsBody : systemsBody.systems ?? [];
        return {
          statuses: [navigationResponse.status, systemsResponse.status],
          app: navigation.app,
          items: Array.isArray(navigation.items) ? navigation.items : [],
          activeSystemIds: systems
            .filter((system: { id?: string; status?: string }) => system.status === 'active')
            .map((system: { id?: string }) => system.id)
            .filter(Boolean),
        };
      }, missionRoom.slug);

      expect(binding.statuses).toEqual([200, 200]);
      expect(binding.app?.assistant_label).toBe(missionRoom.assistant);
      expect(binding.app?.label).toBe(missionRoom.appLabel);
      expect(binding.items.map((item: { key?: string }) => item.key)).toEqual([
        'cockpit',
        'strategie',
        'securite',
        'reputation',
        'agenda',
        'presse',
        'decisions',
      ]);
      expect(binding.items).toHaveLength(7);
      for (const item of binding.items as Array<{ key?: string; system_id?: string | null }>) {
        expect(item.system_id, `${missionRoom.slug}:${item.key} has no System binding`).toBeTruthy();
        expect(
          binding.activeSystemIds,
          `${missionRoom.slug}:${item.key} targets an inactive or foreign System`,
        ).toContain(item.system_id);
      }
      if (missionRoom.slug === 'octocity-mission-room') {
        await expect(page.locator('app-mission-room')).not.toContainText(/SENTINEL/i);
        expect(JSON.stringify(binding)).not.toMatch(/SENTINEL|\bAYA\b/i);
        expect(binding.app?.brand).toEqual({
          label: 'Octocity Mission Room',
          lines: ['AGENTIUM', 'MISSION ROOM'],
          emblem: '/assets/brand/agentium-mark.svg',
          style: 'agentium',
        });
        expect(
          Object.fromEntries(
            binding.items.map(
              (item: { key?: string; system_name?: string }) => [item.key, item.system_name],
            ),
          ),
        ).toEqual({
          cockpit: 'OCTAVE Mission Room',
          strategie: 'OCTAVE Territorial Map',
          securite: 'OCTAVE Open Intelligence',
          reputation: 'OCTAVE Open Intelligence',
          agenda: 'OCTAVE Mission Room',
          presse: 'OCTAVE Open Intelligence',
          decisions: 'OCTAVE Decision Desk',
        });
        expect(
          binding.items.every((item: { variant?: string }) => item.variant?.startsWith('octocity_')),
        ).toBe(true);
      }
      await attachViewport(page, testInfo, missionRoom.screenshot);
    });
  }
});
