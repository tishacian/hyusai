import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { findOctocityForbiddenPresentationTerms } from '../../src/app/features/mission-room/mission-room.presentation';

/**
 * Lot 0 — live workspace contract.
 *
 * This suite is deliberately opt-in because it reads the deployed workspace
 * through a real account. Credentials are injected through E2E_USERNAME and
 * E2E_PASSWORD and must never be committed.
 *
 * Run against production/staging:
 *   E2E_LIVE_CONTRACT=1 \
 *     E2E_EXPECTED_SHA=<deployed-40-hex-sha> E2E_SAFE_CONTENT_FREE=1 \
 *     E2E_{SHOWCASE,ANDRITZ,SENTINEL,OCTOCITY}_WORKSPACE_{ID,SLUG}=... \
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
const safeContentFree = process.env['E2E_SAFE_CONTENT_FREE'] === '1';
const expectedSha = process.env['E2E_EXPECTED_SHA'];
const username = process.env['E2E_USERNAME'];
const password = process.env['E2E_PASSWORD'];
const businessUsername = process.env['E2E_BUSINESS_USERNAME'];
const businessPassword = process.env['E2E_BUSINESS_PASSWORD'];
const configuredAndritzMemberCount = Number(
  process.env['E2E_EXPECTED_ANDRITZ_MEMBERS'] ?? '',
);
const expectedAndritzMemberCount = Number.isInteger(configuredAndritzMemberCount)
  && configuredAndritzMemberCount > 0
  ? configuredAndritzMemberCount
  : null;
const previewStorageKey = 'agentium_business_navigation_preview_slugs';

type WorkspaceRole = 'showcase' | 'andritz' | 'sentinel' | 'octocity';

type WorkspaceTarget = {
  role: WorkspaceRole;
  id: string;
  slug: string;
};

const workspaceTarget = (role: WorkspaceRole): WorkspaceTarget => {
  const prefix = `E2E_${role.toUpperCase()}_WORKSPACE`;
  const id = process.env[`${prefix}_ID`] ?? '';
  const slug = process.env[`${prefix}_SLUG`] ?? '';
  if (liveContract) {
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(id)) {
      throw new Error(`${prefix}_ID must be a canonical UUID`);
    }
    if (!/^[a-z0-9][a-z0-9._-]{0,99}$/.test(slug)) {
      throw new Error(`${prefix}_SLUG must be a canonical workspace slug`);
    }
  }
  return { role, id, slug };
};

const workspaceTargets = {
  showcase: workspaceTarget('showcase'),
  andritz: workspaceTarget('andritz'),
  sentinel: workspaceTarget('sentinel'),
  octocity: workspaceTarget('octocity'),
} satisfies Record<WorkspaceRole, WorkspaceTarget>;

if (liveContract) {
  const identities = Object.values(workspaceTargets);
  if (new Set(identities.map(({ id }) => id)).size !== identities.length) {
    throw new Error('workspace target UUIDs must be unique');
  }
  if (new Set(identities.map(({ slug }) => slug)).size !== identities.length) {
    throw new Error('workspace target slugs must be unique');
  }
}

const andritzTarget = workspaceTargets.andritz;
const workspaceSlug = andritzTarget.slug;

// A Playwright trace records network postData, including the login request.
// Live credentials must never be serialized into retained failure artifacts.
test.use({ trace: 'off', video: 'off', screenshot: 'off' });

type LoginResult = {
  ok: boolean;
  status: number;
  workspaceSlug?: string | null;
  workspaces?: Array<{
    id?: string;
    slug?: string;
    role?: string;
    roleTemplate?: string | null;
  }>;
  detail?: unknown;
};

type LoginCredentials = {
  username?: string;
  password?: string;
};

type BuildInfo = {
  revision?: string;
  service?: string;
  revision_verified?: boolean;
};

async function assertDeployedRevision(page: Page, testInfo: TestInfo): Promise<void> {
  expect(expectedSha, 'E2E_EXPECTED_SHA must be the deployed full SHA').toMatch(/^[0-9a-f]{40}$/);
  const revision = expectedSha as string;
  if (!testInfo.annotations.some(
    (annotation) => annotation.type === 'commit_sha' && annotation.description === revision,
  )) {
    testInfo.annotations.push({ type: 'commit_sha', description: revision });
  }

  const readBuildInfo = async (path: string): Promise<BuildInfo> => {
    const response = await page.request.get(`${path}?canary=${Date.now()}`, {
      headers: { Accept: 'application/json', 'Cache-Control': 'no-cache' },
    });
    expect(response.ok(), `${path} must be readable`).toBe(true);
    return response.json() as Promise<BuildInfo>;
  };
  const [backend, frontend] = await Promise.all([
    readBuildInfo('/api/v1/build-info'),
    readBuildInfo('/build-info.json'),
  ]);
  expect(backend).toMatchObject({
    revision,
    service: 'backend',
    revision_verified: true,
  });
  expect(frontend).toMatchObject({
    revision,
    service: 'frontend',
    revision_verified: true,
  });
}

async function login(
  page: Page,
  businessPreview: boolean,
  targetWorkspace: WorkspaceTarget = andritzTarget,
  rememberMe = false,
  credentials: LoginCredentials = { username, password },
): Promise<LoginResult> {
  expect(credentials.username, 'a username is required for the live contract').toBeTruthy();
  expect(credentials.password, 'a password is required for the live contract').toBeTruthy();

  await page.goto('/auth/signin');
  const result = await page.evaluate(
    async ({ email, secret, target, previewKey, preview, persistSession }) => {
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
      localStorage.setItem('agentium_workspace_slug', target.slug);
      localStorage.setItem(previewKey, JSON.stringify(preview ? [target.slug] : []));

      const workspacesResponse = await fetch('/api/v1/auth/workspaces', {
        headers: {
          Authorization: `Bearer ${body.token}`,
          'X-Workspace-Slug': target.slug,
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
              id?: string;
              slug?: string;
              role?: string;
              role_template?: string | null;
            }) => ({
              id: workspace.id,
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
      target: targetWorkspace,
      previewKey: previewStorageKey,
      preview: businessPreview,
      persistSession: rememberMe,
    },
  );

  expect(result.ok, `login failed with status ${result.status}`).toBe(true);
  expect(
    result.workspaces?.filter(
      (workspace) => workspace.id === targetWorkspace.id && workspace.slug === targetWorkspace.slug,
    ),
    `the authenticated membership must match the resolved ${targetWorkspace.role} target`,
  ).toHaveLength(1);
  return result;
}

async function attachViewport(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  if (safeContentFree) return;
  const path = testInfo.outputPath(name);
  await page.screenshot({ path, animations: 'disabled' });
  await testInfo.attach(name, { path, contentType: 'image/png' });
}

async function missionPresentationCorpus(page: Page): Promise<string> {
  const root = page.locator('[data-mission-room-extension="mission-room"]');
  await expect(root).toHaveCount(1);
  return root.evaluate((element) => {
    const attributes = ['aria-label', 'aria-description', 'title', 'placeholder', 'alt'];
    const values: string[] = [element.textContent || ''];
    for (const candidate of [element, ...Array.from(element.querySelectorAll('*'))]) {
      for (const attribute of attributes) {
        const value = candidate.getAttribute(attribute);
        if (value) values.push(value);
      }
    }
    return values.join('\n');
  });
}

async function client360DryRunProjection(page: Page): Promise<{
  status: number;
  dryRun: boolean;
  created: number | null;
  updated: number | null;
  recordsSeen: number | null;
  candidateMappingsCreated: number | null;
  opportunitiesDetected: number | null;
  previewCount: number | null;
}> {
  return page.evaluate(async (slug) => {
    const response = await fetch('/api/v1/client360/engines/opportunities/run', {
      method: 'POST',
      headers: {
        Authorization: localStorage.getItem('agentium_token') ?? '',
        'Content-Type': 'application/json',
        'X-Workspace-Slug': slug,
      },
      body: JSON.stringify({ dry_run: true }),
    });
    const raw: unknown = await response.json().catch(() => null);
    const body = raw && typeof raw === 'object' && !Array.isArray(raw)
      ? raw as Record<string, unknown>
      : {};
    const counter = (key: string): number | null =>
      Number.isInteger(body[key]) && Number(body[key]) >= 0 ? Number(body[key]) : null;

    // Deliberately project counters and booleans only. The engine preview can
    // contain business data and must never cross into Playwright/JUnit output.
    return {
      status: response.status,
      dryRun: body['dry_run'] === true,
      created: counter('created'),
      updated: counter('updated'),
      recordsSeen: counter('records_seen'),
      candidateMappingsCreated: counter('candidate_mappings_created'),
      opportunitiesDetected: counter('opportunities_detected'),
      previewCount: Array.isArray(body['preview']) ? body['preview'].length : null,
    };
  }, workspaceSlug);
}

async function crossTenantSystemIsolationProjection(
  page: Page,
  currentWorkspace: string,
  foreignWorkspace: string,
): Promise<{
  foreignDiscoveryStatus: number;
  foreignSystemDiscovered: boolean;
  crossTenantReadStatus: number | null;
}> {
  return page.evaluate(async ({ currentSlug, foreignSlug }) => {
    const token = localStorage.getItem('agentium_token') ?? '';
    const foreignResponse = await fetch('/api/v1/systems?include_retired=true&limit=100', {
      headers: { Authorization: token, 'X-Workspace-Slug': foreignSlug },
    });
    const raw: unknown = await foreignResponse.json().catch(() => null);
    const record = raw && typeof raw === 'object' && !Array.isArray(raw)
      ? raw as Record<string, unknown>
      : null;
    const systems = Array.isArray(raw)
      ? raw
      : Array.isArray(record?.['systems'])
        ? record['systems']
        : [];
    const foreignId = systems
      .map((row) => row && typeof row === 'object' && !Array.isArray(row)
        ? row as Record<string, unknown>
        : null)
      .find((row) => row?.['status'] === 'active' && typeof row['id'] === 'string')?.['id'];
    let crossTenantReadStatus: number | null = null;
    if (typeof foreignId === 'string') {
      const isolationResponse = await fetch(`/api/v1/systems/${encodeURIComponent(foreignId)}`, {
        headers: { Authorization: token, 'X-Workspace-Slug': currentSlug },
      });
      crossTenantReadStatus = isolationResponse.status;
      await isolationResponse.body?.cancel().catch(() => undefined);
    }

    // Never return the foreign ID, name, response body or workspace payload.
    return {
      foreignDiscoveryStatus: foreignResponse.status,
      foreignSystemDiscovered: typeof foreignId === 'string',
      crossTenantReadStatus,
    };
  }, { currentSlug: currentWorkspace, foreignSlug: foreignWorkspace });
}

test.describe('Lot 0 — live workspace experience contract', () => {
  test.skip(!liveContract, 'Set E2E_LIVE_CONTRACT=1 to exercise the deployed workspace');

  test.beforeEach(async ({ page }, testInfo) => {
    await assertDeployedRevision(page, testInfo);
  });

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

  test('Andritz business preview exposes the three-app shell', async ({ page }, testInfo) => {
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

  test('the three Andritz surfaces survive deep links, history and reload', async ({ page }, testInfo) => {
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
    const client360DryRun = await client360DryRunProjection(page);
    expect(client360DryRun).toMatchObject({
      status: 200,
      dryRun: true,
      created: 0,
      updated: 0,
    });
    for (const counter of [
      client360DryRun.recordsSeen,
      client360DryRun.candidateMappingsCreated,
      client360DryRun.opportunitiesDetected,
      client360DryRun.previewCount,
    ]) {
      expect(counter).toBeGreaterThanOrEqual(0);
    }
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
    await login(page, true, andritzTarget, true);
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

    const loginResult = await login(page, false, andritzTarget, false, {
      username: businessUsername,
      password: businessPassword,
    });
    const membership = loginResult.workspaces?.find(
      (workspace) => workspace.id === andritzTarget.id && workspace.slug === workspaceSlug,
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

  test('deployed Andritz profile, entitlements and active Systems match the Lot 4 contract', async ({ page }) => {
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
        workspaceId: workspace.id,
        statuses: [
          workspaceResponse.status,
          iamResponse.status,
          systemsResponse.status,
        ],
        mode: workspace.mode,
        navigationProfile: workspace.settings?.navigation_profile,
        features: {
          app_entitlements_v1: workspace.settings?.features?.app_entitlements_v1,
          workspace_experience_v2: workspace.settings?.features?.workspace_experience_v2,
        },
        iam: iam.config,
        memberAppEntitlements: Array.isArray(iam.members)
          ? iam.members.map((member: { app_entitlements?: string[] }) =>
              Array.isArray(member.app_entitlements) ? member.app_entitlements : [],
            )
          : [],
        activeSystems: systems
          .filter((system: { status?: string }) => system.status === 'active')
          .map((system: { name?: string; flow_definition?: { variant?: string } }) => ({
            name: system.name,
            variant: system.flow_definition?.variant,
          })),
      };
    }, workspaceSlug);

    expect(baseline.workspaceId).toBe(andritzTarget.id);
    expect(baseline.statuses).toEqual([200, 200, 200]);
    expect(baseline.mode).toBe('builder');
    expect(baseline.navigationProfile).toEqual({
      key: 'business_end_user',
      default_route: '/chat',
      primary_surfaces: ['chat', 'client360-pdr', 'knowledge-capture'],
      advanced_access: 'admin_only',
    });
    expect(baseline.features).toEqual({
      app_entitlements_v1: true,
      workspace_experience_v2: true,
    });
    expect(baseline.memberAppEntitlements.length).toBeGreaterThan(0);
    if (expectedAndritzMemberCount !== null) {
      expect(baseline.memberAppEntitlements).toHaveLength(expectedAndritzMemberCount);
    }
    for (const grants of baseline.memberAppEntitlements) {
      expect(grants).toEqual(['chat', 'client360-pdr', 'knowledge-capture']);
    }
    expect(
      baseline.memberAppEntitlements.reduce(
        (total: number, grants: string[]) => total + grants.length,
        0,
      ),
    ).toBe(baseline.memberAppEntitlements.length * 3);
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
    await expect.poll(() => new URL(page.url()).pathname).toBe(
      `/workspace/${encodeURIComponent(workspaceSlug)}/settings`,
    );

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
              'navigation_resolver',
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
        redirectOwner: 'navigation_resolver',
        redirectReason: 'workspace_settings_entrypoint',
        redirected: true,
      },
    });
  });

  test('Showcase keeps the standard Agentium cockpit', async ({ page }, testInfo) => {
    test.skip(!liveAllWorkspaces, 'Set E2E_LIVE_ALL_WORKSPACES=1 to capture cross-workspace shells');
    await login(page, false, workspaceTargets.showcase);
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
      role: 'sentinel' as const,
      target: workspaceTargets.sentinel,
      assistant: 'AYA',
      appLabel: 'SENTINEL-CI',
      brandLines: ['REPUBLIQUE DE', "COTE D'IVOIRE"],
      brandEmblem: '/assets/brand/sentinel-ci-emblem.png?v=20260518-1',
      brandStyle: 'sentinel',
      actionPacks: ['global_voice_v1', 'sentinel_ci_aya_v1', 'sentinel_ci_aya_security_v1'],
      screenshot: 'sentinel-mission-room.png',
    },
    {
      role: 'octocity' as const,
      target: workspaceTargets.octocity,
      assistant: 'OCTAVE',
      appLabel: 'Octocity Mission Room',
      brandLines: ['AGENTIUM', 'MISSION ROOM'],
      brandEmblem: '/assets/brand/agentium-mark.svg',
      brandStyle: 'agentium',
      actionPacks: ['global_voice_v1', 'octave_mission_room_v1', 'octave_security_v1'],
      screenshot: 'octocity-workspace.png',
    },
  ]) {
    test(`${missionRoom.role === 'sentinel' ? 'Sentinel' : 'Octocity'} workspace keeps its immersive Mission Room shell`, async ({ page }, testInfo) => {
      test.skip(!liveAllWorkspaces, 'Set E2E_LIVE_ALL_WORKSPACES=1 to capture cross-workspace shells');
      await login(page, false, missionRoom.target);
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
        const [navigationResponse, systemsResponse, workspaceResponse] = await Promise.all([
          fetch('/api/v1/mission-room/navigation', { headers }),
          fetch('/api/v1/systems', { headers }),
          fetch(`/api/v1/auth/workspaces/${encodeURIComponent(slug)}`, { headers }),
        ]);
        const navigation = await navigationResponse.json().catch(() => ({}));
        const systemsBody = await systemsResponse.json().catch(() => []);
        const workspaceBody = await workspaceResponse.json().catch(() => ({}));
        const systems = Array.isArray(systemsBody) ? systemsBody : systemsBody.systems ?? [];
        return {
          workspaceId: workspaceBody.id,
          statuses: [navigationResponse.status, systemsResponse.status, workspaceResponse.status],
          app: navigation.app,
          items: Array.isArray(navigation.items) ? navigation.items : [],
          actionPacks: workspaceBody?.settings?.actions?.enabled_packs ?? [],
          activeSystemIds: systems
            .filter((system: { id?: string; status?: string }) => system.status === 'active')
            .map((system: { id?: string }) => system.id)
            .filter(Boolean),
        };
      }, missionRoom.target.slug);

      const foreignWorkspace = missionRoom.role === 'sentinel'
        ? workspaceTargets.octocity
        : workspaceTargets.sentinel;
      const isolation = await crossTenantSystemIsolationProjection(
        page,
        missionRoom.target.slug,
        foreignWorkspace.slug,
      );

      expect(binding.workspaceId).toBe(missionRoom.target.id);
      expect(binding.statuses).toEqual([200, 200, 200]);
      expect(isolation).toEqual({
        foreignDiscoveryStatus: 200,
        foreignSystemDiscovered: true,
        crossTenantReadStatus: 404,
      });
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
      expect(binding.actionPacks).toEqual(missionRoom.actionPacks);
      for (const item of binding.items as Array<{ key?: string; system_id?: string | null }>) {
        expect(item.system_id, `${missionRoom.role}:${item.key} has no System binding`).toBeTruthy();
        expect(
          binding.activeSystemIds,
          `${missionRoom.role}:${item.key} targets an inactive or foreign System`,
        ).toContain(item.system_id);
      }
      if (missionRoom.role === 'octocity') {
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

        for (const route of [
          '/hypervisor/mission-room/cockpit',
          '/hypervisor/mission-room/securite/monitor',
          '/hypervisor/mission-room/veille-sociale',
          '/hypervisor/mission-room/agenda/meeting/e2e-presentation-contract',
        ]) {
          await page.goto(route);
          const root = page.locator('[data-mission-room-extension="mission-room"]');
          await expect(root).toHaveAttribute(
            'data-mission-room-profile',
            'octocity_institutional_v1',
          );
          await expect.poll(
            async () => findOctocityForbiddenPresentationTerms(
              await missionPresentationCorpus(page),
            ),
            { message: `${route} must not render Sentinel vocabulary` },
          ).toEqual([]);
        }
        await page.goto('/hypervisor/mission-room/cockpit');
      } else {
        const corpus = await missionPresentationCorpus(page);
        expect(corpus).not.toMatch(/Octocity|\bOCTAVE\b|\bAsteria\b|\bMeridian\b/i);
      }
      await attachViewport(page, testInfo, missionRoom.screenshot);
    });
  }
});
