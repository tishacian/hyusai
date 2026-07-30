import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { expect, test, type Page, type Request } from '@playwright/test';

import { resolveWorkspaceAppCanaryEntryPolicy } from '../fixtures/workspace-app-canary';

/**
 * Lot 9 — post-activation canary executed only during a bounded probation.
 *
 * The same unique structural marker used by the preflight identifies the
 * Workspace.  The browser additionally binds the exact probation ref and the
 * canonical installation/configuration digest.  It never contains a tenant,
 * application or provider name.  The canary is server-read-only; it may enter
 * the shell that the installed manifests actually declare and switches to a
 * second Workspace to prove that the previous runtime context is purged.
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
  api_prefixes?: string[];
  action_packs: string[];
  entitlement_keys: string[];
}

interface RuntimeMissionRoom {
  app_id: string;
  version?: string;
  manifest_digest?: string;
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
    mode?: string;
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
  requires_confirmation?: boolean;
  direct_safe?: boolean;
  handler?: { kind?: string; name?: string };
}

interface ActionExecution {
  matched?: boolean;
  action_id?: string;
  requires_confirmation?: boolean;
  result?: { action?: string; applied?: boolean } | null;
  audit_id?: string;
  reason?: string;
}

interface AppWorkspaceCandidate {
  summary: WorkspaceSummary;
  bootstrap: WorkspaceBootstrap;
  runtime: NonNullable<WorkspaceBootstrap['workspace_app_runtime']>;
  experience: NonNullable<NonNullable<WorkspaceBootstrap['workspace_app_runtime']>['experience']>;
  routeTarget: RuntimeInstallation;
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

function canonicalPath(value: string): string {
  return pathOnly(value).replace(/\/$/, '') || '/';
}

function routeWithinScope(path: string, scope: string): boolean {
  const normalized = pathOnly(path).replace(/\/$/, '') || '/';
  const normalizedScope = pathOnly(scope).replace(/\/$/, '') || '/';
  return normalized === normalizedScope || normalized.startsWith(`${normalizedScope}/`);
}

function sortedStrings(values: Iterable<string>): string[] {
  return [...values].sort((left, right) => left.localeCompare(right));
}

function runtimeIdentitySubject(
  workspaceId: string,
  runtime: NonNullable<WorkspaceBootstrap['workspace_app_runtime']>,
): Record<string, unknown> {
  const experience = runtime.experience;
  const mission = experience?.mission_room;
  return {
    workspace_id: workspaceId,
    mode: runtime.mode ?? null,
    enabled: runtime.enabled ?? false,
    rollout_phase: runtime.rollout_phase ?? null,
    rollout_ref: runtime.rollout_ref ?? null,
    installations: [...(runtime.installations ?? [])]
      .sort((left, right) => left.app_id.localeCompare(right.app_id))
      .map((item) => ({
        app_id: item.app_id,
        version: item.version,
        manifest_digest: item.manifest_digest,
        category: item.category,
        routes: sortedStrings(item.routes),
        primary_surface_id: item.primary_surface_id,
        default_route: item.default_route,
        branding_namespace: item.branding_namespace,
        action_packs: sortedStrings(item.action_packs),
        entitlement_keys: sortedStrings(item.entitlement_keys),
      })),
    experience: {
      shell: experience?.shell ?? null,
      routes: sortedStrings(experience?.routes ?? []),
      primary_surface_ids: sortedStrings(experience?.primary_surface_ids ?? []),
      default_routes: experience?.default_routes ?? {},
      branding_namespaces: sortedStrings(experience?.branding_namespaces ?? []),
      action_packs: sortedStrings(experience?.action_packs ?? []),
      mission_room: mission ? {
        app_id: mission.app_id ?? null,
        version: mission.version ?? null,
        manifest_digest: mission.manifest_digest ?? null,
        profile: mission.profile ?? null,
        brand_style: mission.brand_style ?? null,
        default_route: mission.default_route ?? null,
        primary_surface_id: mission.primary_surface_id ?? null,
      } : null,
    },
  };
}

function runtimeIdentitySha256(
  workspaceId: string,
  runtime: NonNullable<WorkspaceBootstrap['workspace_app_runtime']>,
): string {
  return hash(canonical(runtimeIdentitySubject(workspaceId, runtime)));
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
  options: { method?: 'GET' | 'POST'; body?: unknown; noStore?: boolean } = {},
): Promise<ApiResult<T>> {
  return page.evaluate(async ({ slug, apiPath, method, body, noStore }) => {
    const headers: Record<string, string> = {
      Authorization: localStorage.getItem('agentium_token') || '',
      'X-Workspace-Slug': slug,
    };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (noStore) {
      headers['Cache-Control'] = 'no-cache, no-store';
      headers.Pragma = 'no-cache';
    }
    const response = await fetch(`/api/v1${apiPath}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: noStore ? 'no-store' : 'default',
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
    noStore: options.noStore ?? false,
  }) as Promise<ApiResult<T>>;
}

async function directSwitchWorkspace(
  page: Page,
  from: WorkspaceSummary,
  to: WorkspaceSummary,
  shell: 'standard' | 'business' | 'immersive',
): Promise<{
  requests: Array<{ path: string; workspaceHeader: string }>;
  stop: () => void;
}> {
  const requests: Array<{ path: string; workspaceHeader: string }> = [];
  const observe = (request: Request): void => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith('/api/v1/')) return;
    requests.push({
      path: url.pathname,
      workspaceHeader: request.headers()['x-workspace-slug'] ?? '',
    });
  };
  page.on('request', observe);
  let observerTransferred = false;
  const nextRequest = page.waitForRequest((request) => (
    new URL(request.url()).pathname.startsWith('/api/v1/')
    && request.headers()['x-workspace-slug'] === to.slug
  ));
  try {
    if (shell === 'business') {
      const select = page.locator(
        'app-business-shell-header select[title="Changer de workspace"]',
      );
      await expect(
        select,
        'the business app shell must switch Workspace without leaving its application route first',
      ).toBeVisible();
      await select.selectOption(to.slug);
    } else if (shell === 'standard') {
      await page.getByTestId('workspace-switcher-toggle').click();
      await page.locator('app-title-bar button').filter({ hasText: to.name }).first().click();
    } else {
      const select = page.getByTestId('mission-workspace-switch');
      await expect(
        select,
        'the immersive app shell must switch Workspace directly from MissionRail',
      ).toBeVisible();
      await select.selectOption(to.slug);
    }
    await nextRequest;
    await expect.poll(() => page.evaluate(() => localStorage.getItem('agentium_workspace_slug')))
      .toBe(to.slug);
    observerTransferred = true;
  } finally {
    if (!observerTransferred) page.off('request', observe);
  }
  return {
    requests,
    stop: () => page.off('request', observe),
  };
}

async function discoverAlternateAppWorkspace(
  page: Page,
  memberships: WorkspaceSummary[],
  selected: WorkspaceSummary,
  selectedRuntime: NonNullable<WorkspaceBootstrap['workspace_app_runtime']>,
  selectedRoute: RuntimeInstallation,
): Promise<{ candidate: AppWorkspaceCandidate; foreignAction: Required<Pick<ActionManifest, 'action_id' | 'pack'>> }> {
  const selectedPacks = new Set(selectedRuntime.experience?.action_packs ?? []);
  const candidates: Array<{
    candidate: AppWorkspaceCandidate;
    foreignAction: Required<Pick<ActionManifest, 'action_id' | 'pack'>>;
  }> = [];
  for (const summary of memberships.filter((workspace) => workspace.id !== selected.id)) {
    const response = await api<WorkspaceBootstrap>(
      page,
      summary.slug,
      `/auth/workspaces/${encodeURIComponent(summary.slug)}`,
      { noStore: true },
    );
    const runtime = response.body.workspace_app_runtime;
    const experience = runtime?.experience;
    const installations = runtime?.installations ?? [];
    if (!response.ok || runtime?.valid !== true || !experience || installations.length === 0) continue;
    const entry = resolveWorkspaceAppCanaryEntryPolicy(
      experience.shell!,
      installations,
      new Set(response.body.app_entitlements ?? []),
      { immersiveAppId: experience.mission_room?.app_id },
    );
    if (entry.issues.length > 0 || !entry.routeTarget) continue;
    if (
      canonicalPath(entry.routeTarget.default_route) === canonicalPath(selectedRoute.default_route)
      || entry.routeTarget.primary_surface_id === selectedRoute.primary_surface_id
      || canonical(sortedStrings(experience.branding_namespaces ?? []))
        === canonical(sortedStrings(selectedRuntime.experience?.branding_namespaces ?? []))
      || runtimeIdentitySha256(summary.id, runtime)
        === runtimeIdentitySha256(selected.id, selectedRuntime)
    ) continue;
    const actions = await api<{ actions: ActionManifest[] }>(
      page,
      summary.slug,
      '/actions/effective?surface=chat',
      { noStore: true },
    );
    if (!actions.ok) continue;
    const foreign = actions.body.actions
      .filter((manifest): manifest is Required<Pick<ActionManifest, 'action_id' | 'pack'>> & ActionManifest => (
        typeof manifest.action_id === 'string'
        && typeof manifest.pack === 'string'
        && !selectedPacks.has(manifest.pack)
        && manifest.requires_confirmation === false
        && manifest.direct_safe === true
      ))
      .sort((left, right) => left.action_id.localeCompare(right.action_id))[0];
    if (!foreign) continue;
    candidates.push({
      candidate: {
        summary,
        bootstrap: response.body,
        runtime,
        experience,
        routeTarget: entry.routeTarget,
      },
      foreignAction: { action_id: foreign.action_id, pack: foreign.pack },
    });
  }
  expect(
    candidates.length,
    'a second Workspace App with a distinct route, surface and action pack is required for purge proof',
  ).toBeGreaterThan(0);
  candidates.sort((left, right) => (
    runtimeIdentitySha256(left.candidate.summary.id, left.candidate.runtime)
      .localeCompare(runtimeIdentitySha256(right.candidate.summary.id, right.candidate.runtime))
  ));
  return candidates[0]!;
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
      '/actions/manifests?surface=chat',
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
      '/actions/effective?surface=chat',
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
    const actionPackExecutions: Array<Record<string, unknown>> = [];
    for (const pack of sortedStrings(declaredPacks)) {
      const action = effectiveActions.body.actions
        .filter((manifest) => (
          manifest.pack === pack
          && typeof manifest.action_id === 'string'
          && manifest.handler?.kind !== 'legacy_adapter'
          && manifest.requires_confirmation === false
          && manifest.direct_safe === true
        ))
        .sort((left, right) => left.action_id!.localeCompare(right.action_id!))[0];
      expect(
        action,
        `installed action pack ${pack} must expose a direct-safe chat action for semantic probing`,
      ).toBeTruthy();
      const execution = await api<ActionExecution>(
        page,
        selected.summary.slug,
        '/actions/execute',
        {
          method: 'POST',
          body: {
            action_id: action!.action_id,
            surface: 'chat',
            confirm: false,
            payload: {
              canary_probe_ref: `sha256:${hash(`${expectedSha}:${selected.summary.id}:${pack}`)}`,
            },
          },
        },
      );
      expect(execution.ok, `direct-safe action probe failed for ${pack} (${execution.status})`)
        .toBe(true);
      expect(execution.body).toMatchObject({
        matched: true,
        action_id: action!.action_id,
        requires_confirmation: false,
        reason: 'proposed',
        result: { action: action!.action_id, applied: false },
      });
      expect(execution.body.audit_id).toMatch(/^[0-9a-f-]{36}$/i);
      actionPackExecutions.push({
        pack,
        action_id: action!.action_id,
        audit_id: execution.body.audit_id,
        http_status: execution.status,
        matched: execution.body.matched,
        reason: execution.body.reason,
        response_action_id: execution.body.action_id,
        result_action: execution.body.result?.action ?? null,
        applied: execution.body.result?.applied ?? null,
        requires_confirmation: execution.body.requires_confirmation,
      });
    }

    const appEntitlements = new Set(selected.bootstrap.app_entitlements ?? []);
    expect(
      selected.bootstrap.effective_features?.['workspace_app_platform_v1'],
      'runtime authority must be the source of the shell entry contract',
    ).toBe(true);
    const entryPolicy = resolveWorkspaceAppCanaryEntryPolicy(
      runtimeExperience!.shell!,
      runtimeInstallations,
      appEntitlements,
      { immersiveAppId: runtimeExperience?.mission_room?.app_id },
    );
    expect(
      entryPolicy.issues,
      'the installed shell has no honestly enforceable entry proof',
    ).toEqual([]);
    expect(entryPolicy.routeTarget, 'the installed set must expose an entry route').toBeTruthy();
    const routeTarget = entryPolicy.routeTarget!;
    const declaredEntitlements = new Set(entryPolicy.declaredEntitlements);
    const entryGateChecked = true;
    const alternateSelection = await discoverAlternateAppWorkspace(
      page,
      memberships,
      selected.summary,
      runtime!,
      routeTarget,
    );
    const alternate = alternateSelection.candidate;
    const deniedExecution = await api<ActionExecution>(
      page,
      selected.summary.slug,
      '/actions/execute',
      {
        method: 'POST',
        body: {
          action_id: alternateSelection.foreignAction.action_id,
          surface: 'chat',
          confirm: false,
          payload: {
            canary_probe_ref: `sha256:${hash(
              `${expectedSha}:${selected.summary.id}:${alternateSelection.foreignAction.pack}:denied`,
            )}`,
          },
        },
      },
    );
    expect(deniedExecution.ok).toBe(true);
    expect(deniedExecution.body).toMatchObject({
      matched: false,
      action_id: alternateSelection.foreignAction.action_id,
      reason: 'not_visible',
    });
    expect(deniedExecution.body.audit_id).toMatch(/^[0-9a-f-]{36}$/i);
    const foreignActionDenial = {
      pack: alternateSelection.foreignAction.pack,
      action_id: alternateSelection.foreignAction.action_id,
      audit_id: deniedExecution.body.audit_id,
      http_status: deniedExecution.status,
      matched: deniedExecution.body.matched,
      reason: deniedExecution.body.reason,
    };

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
      expect(entryPolicy.mode).toBe('business_entitlement');
      expect(entryPolicy.entitlementGate).toBe(true);
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
      expect(entryPolicy.mode).toBe('immersive_extension');
      expect(entryPolicy.entitlementGate).toBe('not_applicable');
      expect(declaredEntitlements.size).toBe(0);
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
      expect(entryPolicy.mode).toBe('standard_route');
      expect(entryPolicy.entitlementGate).toBe('not_applicable');
      expect(declaredEntitlements.size).toBe(0);
      await expect(page.locator('app-title-bar')).toBeVisible();
      await expect(page.locator('app-business-shell-header')).toHaveCount(0);
    }

    const previousBrand = await shellRoot.getAttribute('data-workspace-app-brand');
    const switchNetwork = await directSwitchWorkspace(
      page,
      selected.summary,
      alternate.summary,
      runtimeExperience!.shell!,
    );
    let alternateBootstrap: ApiResult<WorkspaceBootstrap>;
    try {
      await expect.poll(
        () => routeWithinScope(canonicalPath(page.url()), alternate.routeTarget.default_route),
        { message: 'the direct switch must land on the alternate Workspace App route' },
      ).toBe(true);
      expect(
        routeWithinScope(canonicalPath(page.url()), routeTarget.default_route),
        'the previous Workspace App route must not survive the committed switch',
      ).toBe(false);
      await expect(page.getByTestId('workspace-app-unavailable')).toHaveCount(0);
      await expect(shellRoot).not.toHaveAttribute(
        'data-workspace-app-brand',
        previousBrand ?? (runtimeExperience?.branding_namespaces ?? []).join(','),
      );
      await expect(
        page.locator(`[data-mission-room-extension="${routeTarget.primary_surface_id}"]`),
        'the previous Workspace App object marker must be absent after the switch',
      ).toHaveCount(0);
      alternateBootstrap = await api<WorkspaceBootstrap>(
        page,
        alternate.summary.slug,
        `/auth/workspaces/${encodeURIComponent(alternate.summary.slug)}`,
        { noStore: true },
      );
      expect(alternateBootstrap.ok).toBe(true);
      expect(alternateBootstrap.body.id).toBe(alternate.summary.id);
      expect(
        runtimeIdentitySha256(alternate.summary.id, alternateBootstrap.body.workspace_app_runtime!),
      ).toBe(runtimeIdentitySha256(alternate.summary.id, alternate.runtime));
      await page.waitForTimeout(250);
    } finally {
      switchNetwork.stop();
    }
    const firstNewHeader = switchNetwork.requests.findIndex(
      (request) => request.workspaceHeader === alternate.summary.slug,
    );
    expect(firstNewHeader, 'the switch must issue at least one request for the new Workspace')
      .toBeGreaterThanOrEqual(0);
    const postCommitRequests = switchNetwork.requests.slice(firstNewHeader);
    const oldHeaderAfterNew = postCommitRequests.filter(
      (request) => request.workspaceHeader === selected.summary.slug,
    );
    const newHeaderRequests = postCommitRequests.filter(
      (request) => request.workspaceHeader === alternate.summary.slug,
    );
    expect(
      oldHeaderAfterNew,
      'no request may reuse the previous X-Workspace-Slug after the new context is observable',
    ).toEqual([]);
    expect(newHeaderRequests.length).toBeGreaterThan(0);
    const workspaceSwitch = {
      from_workspace_sha256: hash(selected.summary.id),
      to_workspace_sha256: hash(alternate.summary.id),
      from_runtime_identity_sha256: runtimeIdentitySha256(selected.summary.id, runtime!),
      to_runtime_identity_sha256: runtimeIdentitySha256(alternate.summary.id, alternate.runtime),
      from_route_sha256: hash(canonicalPath(routeTarget.default_route)),
      to_route_sha256: hash(canonicalPath(alternate.routeTarget.default_route)),
      from_primary_surface_sha256: hash(routeTarget.primary_surface_id),
      to_primary_surface_sha256: hash(alternate.routeTarget.primary_surface_id),
      from_header_sha256: hash(selected.summary.slug),
      to_header_sha256: hash(alternate.summary.slug),
      observed_request_paths_sha256: hash(canonical(
        postCommitRequests.map((request) => request.path),
      )),
      cache_revalidation_path_sha256: hash(
        `/api/v1/auth/workspaces/${alternate.summary.slug}`,
      ),
      observed_request_count: postCommitRequests.length,
      new_header_request_count: newHeaderRequests.length,
      old_header_after_new_count: oldHeaderAfterNew.length,
      cache_revalidation: 'network_no_store',
    };

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
        action_pack_isolation: actionPackExecutions.length === declaredPacks.size
          && foreignActionDenial.matched === false,
        workspace_epoch_purge: workspaceSwitch.old_header_after_new_count === 0
          && workspaceSwitch.from_runtime_identity_sha256
            !== workspaceSwitch.to_runtime_identity_sha256,
      },
      diagnostics: {
        installed_count: subject.length,
        declared_route_and_shell: true,
        branding_runtime_to_ui: true,
        runtime_shell: runtimeExperience?.shell,
        entry_policy: entryPolicy.mode,
        shell_entry_boundary: entryGateChecked,
        entitlement_gate: entryPolicy.entitlementGate,
        action_count: actions.body.manifests.length,
        effective_action_count: effectiveActions.body.actions.length,
        declared_action_pack_count: declaredPacks.size,
        declared_entitlement_count: declaredEntitlements.size,
        rendered_route_sha256: hash(pathOnly(routeTarget.default_route)),
        switched_workspace_sha256: hash(alternate.summary.id),
        action_pack_executions: actionPackExecutions,
        foreign_action_denial: foreignActionDenial,
        workspace_switch: workspaceSwitch,
      },
    });
  });
});
