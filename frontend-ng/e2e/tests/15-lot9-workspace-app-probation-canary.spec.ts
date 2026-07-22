import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

/**
 * Lot 9 — post-activation canary executed only during a bounded probation.
 *
 * The same unique structural marker used by the preflight identifies the
 * Workspace.  The browser additionally binds the exact probation ref and the
 * canonical installation/configuration digest.  It never contains a tenant,
 * application or provider name.  The canary is server-read-only; it may enter
 * the admin's local business preview and switch to a second Workspace to prove
 * that the previous runtime context is purged.
 */

const enabled = process.env['E2E_LOT9_POST_CANARY'] === '1';
const username = process.env['E2E_USERNAME'];
const password = process.env['E2E_PASSWORD'];
const expectedSha = (process.env['E2E_EXPECTED_SHA'] ?? '').trim().toLowerCase();
const evidencePath = process.env['E2E_LOT9_POST_EVIDENCE'];

test.use({ trace: 'off', video: 'off', screenshot: 'off' });

interface WorkspaceSummary {
  id: string;
  name: string;
  slug: string;
  role: string;
  role_template?: string | null;
}

interface RuntimeInstallation {
  app_id: string;
  version: string;
  manifest_digest: string;
  category: string;
  routes: string[];
  primary_surface_id: string;
  default_route: string;
  branding_namespace: string;
  action_packs: string[];
  entitlement_keys: string[];
}

interface RuntimeMissionRoom {
  profile: string;
  label: string;
  brand_style: string;
  default_route: string;
  primary_surface_id: string;
}

interface WorkspaceBootstrap {
  id: string;
  settings?: Record<string, unknown>;
  effective_features?: Record<string, boolean>;
  app_entitlements?: string[];
  workspace_app_runtime?: {
    enabled?: boolean;
    valid?: boolean;
    rollout_phase?: string;
    rollout_ref?: string | null;
    installations?: RuntimeInstallation[];
    experience?: {
      shell?: 'standard' | 'business' | 'immersive';
      routes?: string[];
      primary_surface_ids?: string[];
      default_routes?: Record<string, string>;
      branding_namespaces?: string[];
      action_packs?: string[];
      mission_room?: RuntimeMissionRoom | null;
    };
  };
}

interface Installation {
  app_id: string;
  state: 'installed' | 'uninstalled';
  version: string | null;
  manifest_digest: string | null;
  configuration: Record<string, unknown>;
}

interface ApiResult<T> {
  ok: boolean;
  status: number;
  body: T;
}

interface ActionManifest {
  action_id?: string;
  pack?: string;
  visible?: boolean;
}

function hash(value: string): string {
  return createHash('sha256').update(value).digest('hex');
}

function canonical(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map((item) => canonical(item)).join(',')}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record).sort().map((key) => (
    `${JSON.stringify(key)}:${canonical(record[key])}`
  )).join(',')}}`;
}

function installationSubject(rows: Installation[]): Array<Record<string, string>> {
  return rows
    .filter((row) => row.state === 'installed')
    .map((row) => ({
      app_id: row.app_id,
      version: row.version ?? '',
      manifest_digest: row.manifest_digest ?? '',
      configuration_sha256: hash(canonical(row.configuration ?? {})),
    }))
    .sort((left, right) => left.app_id.localeCompare(right.app_id));
}

function pathOnly(value: string): string {
  try {
    return new URL(value, 'https://agentium.invalid').pathname;
  } catch {
    return value.split(/[?#]/, 1)[0] || '/';
  }
}

function routeWithinScope(path: string, scope: string): boolean {
  const normalized = pathOnly(path).replace(/\/$/, '') || '/';
  const normalizedScope = pathOnly(scope).replace(/\/$/, '') || '/';
  return normalized === normalizedScope || normalized.startsWith(`${normalizedScope}/`);
}

function sortedStrings(values: Iterable<string>): string[] {
  return [...values].sort((left, right) => left.localeCompare(right));
}

function marker(settings: Record<string, unknown> | undefined): unknown {
  const experience = settings?.['experience'];
  return experience && typeof experience === 'object'
    ? (experience as Record<string, unknown>)['workspace_app_platform_canary']
    : undefined;
}

function isAdmin(workspace: WorkspaceSummary): boolean {
  return workspace.role === 'owner'
    || workspace.role === 'admin'
    || workspace.role_template === 'workspace_owner'
    || workspace.role_template === 'workspace_admin';
}

function writeEvidence(path: string | undefined, payload: unknown): void {
  if (!path) return;
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(payload, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
}

async function login(page: Page): Promise<WorkspaceSummary[]> {
  expect(username, 'E2E_USERNAME is required for the Lot 9 post canary').toBeTruthy();
  expect(password, 'E2E_PASSWORD is required for the Lot 9 post canary').toBeTruthy();
  await page.goto('/auth/signin');
  const result = await page.evaluate(async ({ email, secret }) => {
    const response = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password: secret, remember_me: false }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || !body.token) return { ok: false, status: response.status, workspaces: [] };
    localStorage.setItem('agentium_token', `Bearer ${body.token}`);
    if (body.refresh_token) localStorage.setItem('agentium_refresh_token', body.refresh_token);
    const memberships = await fetch('/api/v1/auth/workspaces', {
      headers: { Authorization: `Bearer ${body.token}` },
    });
    return {
      ok: memberships.ok,
      status: memberships.status,
      workspaces: memberships.ok ? await memberships.json().catch(() => []) : [],
    };
  }, { email: username as string, secret: password as string });
  expect(result.ok, `login or workspace discovery failed (${result.status})`).toBe(true);
  return (Array.isArray(result.workspaces) ? result.workspaces : []) as WorkspaceSummary[];
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

async function api<T>(
  page: Page,
  workspaceSlug: string,
  path: string,
  options: { method?: 'GET' | 'POST'; body?: unknown } = {},
): Promise<ApiResult<T>> {
  return page.evaluate(async ({ slug, apiPath, method, body }) => {
    const headers: Record<string, string> = {
      Authorization: localStorage.getItem('agentium_token') || '',
      'X-Workspace-Slug': slug,
    };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const response = await fetch(`/api/v1${apiPath}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    let parsed: unknown = null;
    if (text) {
      try { parsed = JSON.parse(text); } catch { parsed = text; }
    }
    return { ok: response.ok, status: response.status, body: parsed };
  }, {
    slug: workspaceSlug,
    apiPath: path,
    method: options.method ?? 'GET',
    body: options.body,
  }) as Promise<ApiResult<T>>;
}

async function switchWorkspace(
  page: Page,
  from: WorkspaceSummary,
  to: WorkspaceSummary,
): Promise<void> {
  const nextRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname.startsWith('/api/v1/')
      && request.headers()['x-workspace-slug'] === to.slug;
  });
  await page.getByTitle(from.name, { exact: true }).click();
  await page.locator('app-title-bar button').filter({ hasText: to.name }).first().click();
  await nextRequest;
  await expect.poll(() => page.evaluate(() => localStorage.getItem('agentium_workspace_slug')))
    .toBe(to.slug);
}

test.describe.serial('Lot 9 — Workspace App probation canary', () => {
  test.skip(!enabled, 'Set E2E_LOT9_POST_CANARY=1 during a staged probation');
  test.setTimeout(5 * 60 * 1_000);
  test.afterEach(async ({ page }) => logout(page));

  test('proves the staged runtime on the same workspace and installation set', async ({ page }) => {
    expect(expectedSha, 'E2E_EXPECTED_SHA must be the deployed full SHA').toMatch(/^[0-9a-f]{40}$/);
    for (const path of ['/api/v1/build-info', '/build-info.json']) {
      const response = await page.request.get(`${path}?canary=${Date.now()}`, {
        headers: { Accept: 'application/json', 'Cache-Control': 'no-cache' },
      });
      expect(response.ok(), `${path} must be readable`).toBe(true);
      expect(await response.json()).toMatchObject({ revision: expectedSha, revision_verified: true });
    }

    const memberships = await login(page);
    const marked: Array<{ summary: WorkspaceSummary; bootstrap: WorkspaceBootstrap }> = [];
    for (const summary of memberships.filter(isAdmin)) {
      const response = await api<WorkspaceBootstrap>(
        page,
        summary.slug,
        `/auth/workspaces/${encodeURIComponent(summary.slug)}`,
      );
      if (response.ok && marker(response.body.settings) === 'v1') {
        marked.push({ summary, bootstrap: response.body });
      }
    }
    expect(marked, 'exactly one admin Workspace must carry the Lot 9 marker').toHaveLength(1);
    const selected = marked[0]!;
    const runtime = selected.bootstrap.workspace_app_runtime;
    expect(runtime).toMatchObject({ enabled: true, valid: true, rollout_phase: 'probation' });
    expect(runtime?.rollout_ref).toMatch(/^sha256:[0-9a-f]{64}$/);
    const runtimeInstallations = runtime?.installations ?? [];
    const runtimeExperience = runtime?.experience;
    expect(runtimeInstallations.length).toBeGreaterThan(0);
    expect(runtimeExperience, 'the probation runtime must expose an effective experience').toBeTruthy();
    expect(runtimeExperience?.routes?.length, 'the runtime must own at least one route').toBeGreaterThan(0);
    expect(Object.keys(runtimeExperience?.default_routes ?? {}).length).toBe(runtimeInstallations.length);
    expect(runtimeExperience?.branding_namespaces?.length, 'the runtime must declare observable branding')
      .toBeGreaterThan(0);
    expect(runtimeExperience?.action_packs?.length, 'the runtime must declare a real action boundary')
      .toBeGreaterThan(0);
    for (const installation of runtimeInstallations) {
      expect(installation.routes.length, 'every installed app must own a route').toBeGreaterThan(0);
      expect(installation.action_packs.length, 'every probation app must contribute a real action pack')
        .toBeGreaterThan(0);
      expect(runtimeExperience?.default_routes?.[installation.app_id]).toBe(installation.default_route);
      expect(installation.routes.some((scope) => routeWithinScope(installation.default_route, scope)))
        .toBe(true);
    }
    const installationBrands = sortedStrings(new Set(
      runtimeInstallations.map((installation) => installation.branding_namespace),
    ));
    expect(sortedStrings(runtimeExperience?.branding_namespaces ?? [])).toEqual(installationBrands);
    const installationPacks = sortedStrings(new Set(
      runtimeInstallations.flatMap((installation) => installation.action_packs),
    ));
    expect(sortedStrings(runtimeExperience?.action_packs ?? [])).toEqual(installationPacks);

    const ledger = await api<{ workspace_id: string; installations: Installation[] }>(
      page,
      selected.summary.slug,
      '/governance/workspace-apps/installations',
    );
    expect(ledger.ok).toBe(true);
    expect(ledger.body.workspace_id).toBe(selected.summary.id);
    const subject = installationSubject(ledger.body.installations);
    expect(subject.length).toBeGreaterThan(0);
    const installationsSha256 = hash(canonical(subject));
    expect(runtimeInstallations.map((row) => ({
      app_id: row.app_id,
      version: row.version,
      manifest_digest: row.manifest_digest,
    })).sort((left, right) => left.app_id.localeCompare(right.app_id))).toEqual(
      subject.map(({ configuration_sha256: _configuration, ...row }) => row),
    );

    const installed = runtimeInstallations[0];
    expect(installed).toBeTruthy();
    const blockedMutation = await api<{ detail?: { code?: string } }>(
      page,
      selected.summary.slug,
      '/governance/workspace-apps/plan',
      {
        method: 'POST',
        body: {
          operation: 'upgrade',
          app_id: installed!.app_id,
          target_version: installed!.version,
          expected_manifest_digest: installed!.manifest_digest,
        },
      },
    );
    expect(blockedMutation.status).toBe(409);
    expect(blockedMutation.body.detail?.code).toBe('runtime_authority_active');

    const actions = await api<{ manifests: ActionManifest[] }>(
      page,
      selected.summary.slug,
      '/actions/manifests',
    );
    expect(actions.ok).toBe(true);
    const declaredPacks = new Set(runtimeExperience?.action_packs ?? []);
    expect(declaredPacks.size, 'action-pack isolation is not proven by an empty runtime boundary')
      .toBeGreaterThan(0);
    expect(actions.body.manifests.length, 'the runtime boundary must expose at least one catalog action')
      .toBeGreaterThan(0);
    expect(actions.body.manifests.every((manifest) => (
      typeof manifest.action_id === 'string'
      && manifest.action_id.length > 0
      && typeof manifest.pack === 'string'
      && declaredPacks.has(manifest.pack)
      && manifest.visible === true
    )), 'catalog actions must be visible and belong only to installed packs').toBe(true);
    const catalogPacks = new Set(actions.body.manifests.map((manifest) => manifest.pack as string));
    expect(sortedStrings(catalogPacks)).toEqual(sortedStrings(declaredPacks));

    const effectiveActions = await api<{ actions: ActionManifest[] }>(
      page,
      selected.summary.slug,
      '/actions/effective',
    );
    expect(effectiveActions.ok).toBe(true);
    expect(effectiveActions.body.actions.length, 'at least one installed-pack action must be effective')
      .toBeGreaterThan(0);
    expect(effectiveActions.body.actions.every((manifest) => (
      typeof manifest.action_id === 'string'
      && manifest.action_id.length > 0
      && typeof manifest.pack === 'string'
      && declaredPacks.has(manifest.pack)
    )), 'effective actions must not leak a pack outside the runtime boundary').toBe(true);
    const effectivePacks = new Set(effectiveActions.body.actions.map((manifest) => manifest.pack as string));
    expect(sortedStrings(effectivePacks)).toEqual(sortedStrings(declaredPacks));

    const declaredEntitlements = new Set(
      runtimeInstallations.flatMap((installation) => installation.entitlement_keys),
    );
    expect(
      declaredEntitlements.size,
      'a post-activation canary must declare at least one real entry entitlement',
    ).toBeGreaterThan(0);
    const appEntitlements = new Set(selected.bootstrap.app_entitlements ?? []);
    let entryGateChecked = false;
    let routeTarget = runtimeInstallations[0]!;
    expect(
      selected.bootstrap.effective_features?.['workspace_app_platform_v1'],
      'runtime authority itself must keep manifest entry entitlements fail closed',
    ).toBe(true);
    expect(runtimeExperience?.shell, 'entitlement UI proof currently requires the business shell')
      .toBe('business');
    const gateTargets = runtimeInstallations.filter((installation) => (
      installation.entitlement_keys.includes(installation.primary_surface_id)
    ));
    expect(gateTargets.length, 'no declared entitlement can be confronted with a primary entry route')
      .toBeGreaterThan(0);
    const grantedTarget = gateTargets.find((installation) => (
      appEntitlements.has(installation.primary_surface_id)
    ));
    expect(grantedTarget, 'the canary principal needs one granted declared entry for an honest UI proof')
      .toBeTruthy();
    routeTarget = grantedTarget!;
    entryGateChecked = true;

    expect(
      runtimeExperience?.routes?.some((scope) => routeWithinScope(routeTarget.default_route, scope)),
      'the selected default route must remain inside the authoritative aggregate route boundary',
    ).toBe(true);
    await page.evaluate((slug) => localStorage.setItem('agentium_workspace_slug', slug), selected.summary.slug);
    if (runtimeExperience?.shell === 'business') {
      await page.goto(`/workspace/${encodeURIComponent(selected.summary.slug)}/settings`);
      const preview = page.getByRole('button', { name: 'Preview business shell', exact: true });
      await expect(
        preview,
        'an admin must be able to enter the effective business shell without mutating workspace settings',
      ).toBeVisible();
      await preview.click();
      await expect.poll(() => pathOnly(page.url())).not.toContain('/workspace/');
    }
    await page.goto(routeTarget.default_route);
    await expect.poll(() => routeWithinScope(new URL(page.url()).pathname, routeTarget.default_route), {
      message: 'the declared default route must render without resolver drift',
    }).toBe(true);
    await expect(page.getByTestId('workspace-app-unavailable')).toHaveCount(0);
    const shellRoot = page.locator('app-shell > div').first();
    await expect(shellRoot).toBeVisible();
    await expect(shellRoot).toHaveAttribute(
      'data-workspace-app-brand',
      (runtimeExperience?.branding_namespaces ?? []).join(','),
    );
    await expect(page.locator('app-shell main router-outlet + *').first()).toBeAttached();

    if (runtimeExperience?.shell === 'business') {
      await expect(page.locator('app-business-shell-header')).toBeVisible();
      await expect(page.locator('app-title-bar')).toHaveCount(0);
      if (declaredEntitlements.size > 0) {
        const renderedEntries = await page.locator('app-business-shell-header nav a').evaluateAll((elements) => (
          elements.map((element) => new URL((element as HTMLAnchorElement).href).pathname)
        ));
        const gateTargets = runtimeInstallations.filter((installation) => (
          installation.entitlement_keys.includes(installation.primary_surface_id)
        ));
        for (const installation of gateTargets) {
          expect(renderedEntries.includes(pathOnly(installation.default_route))).toBe(
            appEntitlements.has(installation.primary_surface_id),
          );
        }
        const activeEntry = page.locator('app-business-shell-header nav a.business-nav-active');
        await expect(activeEntry).toHaveCount(1);
        expect(pathOnly((await activeEntry.getAttribute('href')) ?? '')).toBe(
          pathOnly(routeTarget.default_route),
        );
      }
    } else if (runtimeExperience?.shell === 'immersive') {
      await expect(page.locator('app-business-shell-header')).toHaveCount(0);
      await expect(page.locator('app-title-bar')).toHaveCount(0);
      await expect(page.locator('app-mission-room-extension-host')).toBeAttached();
      await expect(page.locator('[data-mission-room-extension]')).toHaveAttribute(
        'data-mission-room-extension',
        routeTarget.primary_surface_id,
      );
      await expect(page.locator('app-mission-room .mission-shell')).toBeVisible();
      const mission = runtimeExperience.mission_room;
      expect(mission, 'an immersive runtime must expose its brand style contract').toBeTruthy();
      expect(mission?.brand_style?.length).toBeGreaterThan(0);
      await expect(page.locator('app-mission-room .mission-shell')).toHaveAttribute(
        'data-workspace-app-brand-style',
        mission!.brand_style,
      );
      await expect(page.locator('app-mission-rail .mission-rail')).toHaveAttribute(
        'aria-label',
        `Navigation ${mission?.label}`,
      );
    } else {
      expect(runtimeExperience?.shell).toBe('standard');
      await expect(page.locator('app-title-bar')).toBeVisible();
      await expect(page.locator('app-business-shell-header')).toHaveCount(0);
    }

    const alternate = memberships.find((workspace) => workspace.id !== selected.summary.id);
    expect(alternate, 'a second Workspace is required to prove context purge').toBeTruthy();
    if (runtimeExperience?.shell === 'business') {
      const exitPreview = page.locator('app-business-shell-header button.business-action');
      await expect(exitPreview, 'the local business preview must expose its reversible admin exit')
        .toBeVisible();
      await exitPreview.click();
      await expect(page.locator('app-title-bar')).toBeVisible();
    }
    await page.goto(`/workspace/${encodeURIComponent(selected.summary.slug)}/settings`);
    await expect(page.locator('app-title-bar')).toBeVisible();
    await switchWorkspace(page, selected.summary, alternate!);
    const alternateBootstrap = await api<WorkspaceBootstrap>(
      page,
      alternate!.slug,
      `/auth/workspaces/${encodeURIComponent(alternate!.slug)}`,
    );
    expect(alternateBootstrap.ok).toBe(true);
    expect(alternateBootstrap.body.workspace_app_runtime?.rollout_ref)
      .not.toBe(runtime?.rollout_ref);

    writeEvidence(evidencePath, {
      schema_version: 1,
      kind: 'lot9_workspace_app_postactivation_observation',
      tested_revision: expectedSha,
      generated_at: new Date().toISOString(),
      runner: {
        protected_ci: process.env['CI'] === 'true'
          && process.env['CI_COMMIT_REF_PROTECTED'] === 'true',
        pipeline_id: process.env['CI_PIPELINE_ID'] ?? null,
        job_id: process.env['CI_JOB_ID'] ?? null,
      },
      target: {
        workspace_sha256: hash(selected.summary.id),
        installations_sha256: installationsSha256,
        probation_ref: runtime?.rollout_ref,
      },
      checks: {
        runtime_bootstrap: true,
        entry_gate: entryGateChecked,
        action_pack_isolation: true,
        workspace_epoch_purge: true,
      },
      diagnostics: {
        installed_count: subject.length,
        declared_route_and_shell: true,
        branding_runtime_to_ui: true,
        entitlement_gate: entryGateChecked,
        action_count: actions.body.manifests.length,
        effective_action_count: effectiveActions.body.actions.length,
        declared_action_pack_count: declaredPacks.size,
        declared_entitlement_count: declaredEntitlements.size,
        rendered_route_sha256: hash(pathOnly(routeTarget.default_route)),
        switched_workspace_sha256: hash(alternate!.id),
      },
    });
  });
});
