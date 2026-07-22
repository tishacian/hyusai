import { createHash, randomUUID } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

import {
  resolveWorkspaceAppCanaryEntryPolicy,
  type WorkspaceAppCanaryEntryPolicy,
  type WorkspaceAppCanaryShell,
} from '../fixtures/workspace-app-canary';

/**
 * Lot 9 — authenticated Workspace App lifecycle canary.
 *
 * The target is the unique Workspace carrying the dedicated structural marker;
 * no workspace slug/name, app id/name or row id is embedded in this source.
 * Its runtime authority must be disabled and its installed set must already be
 * nonempty. The canary discovers an installed app with at least two
 * strict-semver manifests, exercises its lifecycle, then restores the exact
 * initial installation ledger (apart from monotonic revisions and receipts).
 *
 * This is intentionally opt-in and mutating: operation/audit receipts remain,
 * while the original nonempty installed set is left ready for probation.
 * Traces, video and screenshots stay disabled because a live principal is used.
 */

const enabled = process.env['E2E_LOT9_CANARY'] === '1';
const username = process.env['E2E_USERNAME'];
const password = process.env['E2E_PASSWORD'];
const expectedSha = (process.env['E2E_EXPECTED_SHA'] ?? '').trim().toLowerCase();
const evidencePath = process.env['E2E_LOT9_EVIDENCE'];

test.use({ trace: 'off', video: 'off', screenshot: 'off' });

interface WorkspaceSummary {
  id: string;
  slug: string;
  role: string;
  role_template?: string | null;
}

interface WorkspaceBootstrap {
  settings?: Record<string, unknown>;
  app_entitlements?: string[];
  workspace_app_runtime?: {
    enabled?: boolean;
    valid?: boolean;
    rollout_phase?: string;
    rollout_ref?: string | null;
  };
}

interface ManifestEntry {
  app_id: string;
  version: string;
  manifest_digest: string;
  manifest: {
    schema_version: number;
    app_id: string;
    version: string;
    category: string;
    compatibility: { workspace_app_platform: number; agentium_api: string };
    routes: string[];
    branding: { namespace: string };
    action_packs: string[];
    entitlement_keys: string[];
    experience: {
      shell: WorkspaceAppCanaryShell;
      primary_surface_id: string;
      default_route: string;
      mission_room?: Record<string, unknown> | null;
    };
  };
}

interface Installation {
  app_id: string;
  state: 'installed' | 'uninstalled';
  version: string | null;
  manifest_digest: string | null;
  configuration: Record<string, unknown>;
  revision: number;
}

interface LifecyclePlan {
  workspace_id: string;
  app_id: string;
  operation: 'install' | 'upgrade' | 'rollback' | 'uninstall';
  from: { state: string; version: string | null; manifest_digest: string | null; revision: number };
  to: { state: string; version: string | null; manifest_digest: string | null };
  plan_sha256: string;
}

interface LifecycleReceipt {
  workspace_id: string;
  operation_id: string;
  operation: 'install' | 'upgrade' | 'rollback' | 'uninstall';
  app_id: string;
  plan_sha256: string;
  manifest_digest: string;
  idempotent_replay: boolean;
  installation: Installation;
}

interface ApiResult<T> {
  ok: boolean;
  status: number;
  body: T;
}

interface Candidate {
  workspace: WorkspaceSummary;
  initial: ManifestEntry;
  initialInstallation: Installation;
  oldest: ManifestEntry;
  newest: ManifestEntry;
  versions: ManifestEntry[];
  initialInstallations: Installation[];
  initialInstallationsSha256: string;
  initialLedgerSha256: string;
  runtimeShell: WorkspaceAppCanaryShell;
  entryPolicy: WorkspaceAppCanaryEntryPolicy;
  declaredEntitlementCount: number;
}

function isAdmin(workspace: WorkspaceSummary): boolean {
  return workspace.role === 'owner'
    || workspace.role === 'admin'
    || workspace.role_template === 'workspace_owner'
    || workspace.role_template === 'workspace_admin';
}

function semver(value: string): readonly [number, number, number] | null {
  const match = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/.exec(value);
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : null;
}

function compareVersion(left: string, right: string): number {
  const a = semver(left);
  const b = semver(right);
  if (!a || !b) return left.localeCompare(right);
  for (let index = 0; index < 3; index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return 0;
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

function installationDigest(rows: Installation[]): string {
  return hash(canonical(installationSubject(rows)));
}

function ledgerSubject(rows: Installation[]): Array<Record<string, unknown>> {
  return rows
    .map((row) => ({
      app_id: row.app_id,
      state: row.state,
      version: row.version,
      manifest_digest: row.manifest_digest,
      configuration: row.configuration ?? {},
    }))
    .sort((left, right) => String(left.app_id).localeCompare(String(right.app_id)));
}

function ledgerDigest(rows: Installation[]): string {
  return hash(canonical(ledgerSubject(rows)));
}

function lifecycleOperationProof(receipt: LifecycleReceipt): Record<string, string> {
  return {
    operation: receipt.operation,
    operation_id_sha256: hash(receipt.operation_id),
    plan_sha256: receipt.plan_sha256,
    manifest_digest: receipt.manifest_digest,
  };
}

function canaryMarker(settings: Record<string, unknown> | undefined): unknown {
  const experience = settings?.['experience'];
  return experience && typeof experience === 'object'
    ? (experience as Record<string, unknown>)['workspace_app_platform_canary']
    : undefined;
}

function writeEvidence(path: string | undefined, payload: unknown): void {
  if (!path) return;
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(payload, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
}

async function login(page: Page): Promise<WorkspaceSummary[]> {
  expect(username, 'E2E_USERNAME is required for the Lot 9 canary').toBeTruthy();
  expect(password, 'E2E_PASSWORD is required for the Lot 9 canary').toBeTruthy();
  await page.goto('/auth/signin');
  const result = await page.evaluate(async ({ email, secret }) => {
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
  options: { method?: 'GET' | 'POST'; body?: unknown; idempotencyKey?: string } = {},
): Promise<ApiResult<T>> {
  return page.evaluate(async ({ slug, apiPath, method, body, idempotencyKey }) => {
    const headers: Record<string, string> = {
      Authorization: localStorage.getItem('agentium_token') || '',
      'X-Workspace-Slug': slug,
    };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;
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
    idempotencyKey: options.idempotencyKey,
  }) as Promise<ApiResult<T>>;
}

async function discover(page: Page, workspaces: WorkspaceSummary[]): Promise<Candidate> {
  const marked: Array<{ workspace: WorkspaceSummary; bootstrap: WorkspaceBootstrap }> = [];
  for (const workspace of workspaces.filter(isAdmin)) {
    const bootstrap = await api<WorkspaceBootstrap>(
      page,
      workspace.slug,
      `/auth/workspaces/${encodeURIComponent(workspace.slug)}`,
    );
    if (bootstrap.ok && canaryMarker(bootstrap.body.settings) === 'v1') {
      marked.push({ workspace, bootstrap: bootstrap.body });
    }
  }
  expect(marked, 'exactly one admin Workspace must carry the Lot 9 canary marker').toHaveLength(1);
  const [{ workspace, bootstrap }] = marked;
  expect(bootstrap.workspace_app_runtime).toMatchObject({
    enabled: false,
    valid: true,
    rollout_phase: 'disabled',
  });

  const candidates: Candidate[] = [];
  {
    const registry = await api<{ workspace_id: string; manifests: ManifestEntry[] }>(
      page,
      workspace.slug,
      '/governance/workspace-apps/manifests',
    );
    const ledger = await api<{ workspace_id: string; installations: Installation[] }>(
      page,
      workspace.slug,
      '/governance/workspace-apps/installations',
    );
    expect(registry.ok && ledger.ok, 'admin Workspace App discovery must succeed').toBe(true);
    expect(registry.body.workspace_id).toBe(workspace.id);
    expect(ledger.body.workspace_id).toBe(workspace.id);
    const initialSubject = installationSubject(ledger.body.installations);
    expect(initialSubject, 'the marked Workspace must start with a nonempty installed set')
      .not.toHaveLength(0);
    const initialInstallationsSha256 = installationDigest(ledger.body.installations);

    const installed = new Map(ledger.body.installations.map((row) => [row.app_id, row]));
    const grouped = new Map<string, ManifestEntry[]>();
    for (const entry of registry.body.manifests) {
      expect(entry.manifest.app_id).toBe(entry.app_id);
      expect(entry.manifest.version).toBe(entry.version);
      expect(entry.manifest_digest).toMatch(/^[0-9a-f]{64}$/);
      const values = grouped.get(entry.app_id) ?? [];
      values.push(entry);
      grouped.set(entry.app_id, values);
    }
    const manifestByInstallation = new Map(
      registry.body.manifests.map((entry) => [
        `${entry.app_id}\u0000${entry.version}\u0000${entry.manifest_digest}`,
        entry,
      ]),
    );
    const runtimeInstallations = ledger.body.installations
      .filter((row) => row.state === 'installed')
      .map((row) => manifestByInstallation.get(
        `${row.app_id}\u0000${row.version ?? ''}\u0000${row.manifest_digest ?? ''}`,
      ));
    expect(
      runtimeInstallations.every((entry): entry is ManifestEntry => entry !== undefined),
      'every installed row must resolve to an exact compatible registry manifest',
    ).toBe(true);
    const resolvedInstallations = runtimeInstallations.filter(
      (entry): entry is ManifestEntry => entry !== undefined,
    );
    const nonStandardShells = [...new Set(
      resolvedInstallations
        .map((entry) => entry.manifest.experience.shell)
        .filter((shell) => shell !== 'standard'),
    )];
    expect(nonStandardShells.length, 'the installed set must declare one coherent shell')
      .toBeLessThanOrEqual(1);
    const runtimeShell = nonStandardShells[0] ?? 'standard';
    const missionOwner = resolvedInstallations.find((entry) => (
      entry.manifest.experience.mission_room !== null
      && entry.manifest.experience.mission_room !== undefined
    ));
    const entryResolution = resolveWorkspaceAppCanaryEntryPolicy(
      runtimeShell,
      resolvedInstallations.map((entry) => ({
        app_id: entry.app_id,
        primary_surface_id: entry.manifest.experience.primary_surface_id,
        entitlement_keys: entry.manifest.entitlement_keys,
      })),
      new Set(bootstrap.app_entitlements ?? []),
      { immersiveAppId: missionOwner?.app_id },
    );
    expect(
      entryResolution.issues,
      'the restored installed set must support the post-canary entry proof for the same principal',
    ).toEqual([]);
    for (const versions of grouped.values()) {
      versions.sort((left, right) => compareVersion(left.version, right.version));
      const row = installed.get(versions[0].app_id);
      const initial = row?.state === 'installed'
        ? versions.find((entry) => (
          entry.version === row.version && entry.manifest_digest === row.manifest_digest
        ))
        : undefined;
      if (versions.length >= 2 && row?.state === 'installed' && initial) {
        candidates.push({
          workspace,
          initial,
          initialInstallation: row,
          oldest: versions[0],
          newest: versions.at(-1)!,
          versions,
          initialInstallations: ledger.body.installations,
          initialInstallationsSha256,
          initialLedgerSha256: ledgerDigest(ledger.body.installations),
          runtimeShell,
          entryPolicy: entryResolution.mode,
          declaredEntitlementCount: entryResolution.declaredEntitlements.length,
        });
      }
    }
  }
  expect(
    candidates.length,
    'the marked authority-disabled Workspace must have an installed app with two versions',
  ).toBeGreaterThan(0);
  candidates.sort((left, right) => left.initial.manifest_digest.localeCompare(right.initial.manifest_digest));
  return candidates[0];
}

function request(
  operation: LifecyclePlan['operation'],
  entry: ManifestEntry,
  configuration?: Record<string, unknown>,
): Record<string, unknown> {
  const body: Record<string, unknown> = {
    operation,
    app_id: entry.app_id,
    target_version: operation === 'uninstall' ? null : entry.version,
    expected_manifest_digest: entry.manifest_digest,
  };
  if (configuration !== undefined && operation !== 'uninstall') {
    body['configuration'] = configuration;
  }
  return body;
}

async function planAndApplyApi(
  page: Page,
  workspace: WorkspaceSummary,
  operation: LifecyclePlan['operation'],
  entry: ManifestEntry,
  key: string,
  configuration?: Record<string, unknown>,
): Promise<{ plan: LifecyclePlan; receipt: LifecycleReceipt }> {
  const body = request(operation, entry, configuration);
  const planned = await api<LifecyclePlan>(page, workspace.slug, '/governance/workspace-apps/plan', {
    method: 'POST',
    body,
  });
  expect(planned.ok, `${operation} plan failed (${planned.status})`).toBe(true);
  expect(planned.body.workspace_id).toBe(workspace.id);
  expect(planned.body.app_id).toBe(entry.app_id);
  const applied = await api<LifecycleReceipt>(page, workspace.slug, '/governance/workspace-apps/apply', {
    method: 'POST',
    idempotencyKey: key,
    body: { ...body, expected_plan_sha256: planned.body.plan_sha256 },
  });
  expect(applied.ok, `${operation} apply failed (${applied.status})`).toBe(true);
  expect(applied.body.plan_sha256).toBe(planned.body.plan_sha256);
  expect(applied.body.manifest_digest).toBe(entry.manifest_digest);
  return { plan: planned.body, receipt: applied.body };
}

async function applyThroughUi(
  page: Page,
  operation: 'upgrade' | 'rollback' | 'uninstall',
  entry: ManifestEntry,
): Promise<LifecycleReceipt> {
  const button = page.locator(
    `button[data-operation="${operation}"][data-manifest-digest="${entry.manifest_digest}"]`,
  );
  await expect(button).toHaveCount(1);
  const planResponse = page.waitForResponse((response) => (
    response.url().endsWith('/api/v1/governance/workspace-apps/plan')
    && response.request().method() === 'POST'
  ));
  await button.click();
  const planHttp = await planResponse;
  expect(planHttp.ok()).toBe(true);
  const plan = await planHttp.json() as LifecyclePlan;
  expect(plan.operation).toBe(operation);
  expect(plan.app_id).toBe(entry.app_id);
  expect(plan.to.manifest_digest).toBe(operation === 'uninstall' ? null : entry.manifest_digest);
  await expect(page.getByTestId('workspace-app-manifest-digest')).toHaveText(entry.manifest_digest);
  await expect(page.getByTestId('workspace-app-plan-sha')).toHaveText(plan.plan_sha256);

  let idempotencyKey = '';
  const applyRequest = page.waitForRequest((candidate) => {
    if (!candidate.url().endsWith('/api/v1/governance/workspace-apps/apply')) return false;
    idempotencyKey = candidate.headers()['idempotency-key'] ?? '';
    return candidate.method() === 'POST';
  });
  const applyResponse = page.waitForResponse((response) => (
    response.url().endsWith('/api/v1/governance/workspace-apps/apply')
    && response.request().method() === 'POST'
  ));
  await page.getByTestId('workspace-app-apply').click();
  await applyRequest;
  expect(idempotencyKey).toMatch(/^workspace-app:(upgrade|rollback|uninstall):/);
  const applyHttp = await applyResponse;
  expect(applyHttp.ok()).toBe(true);
  const receipt = await applyHttp.json() as LifecycleReceipt;
  expect(receipt.operation).toBe(operation);
  expect(receipt.app_id).toBe(entry.app_id);
  expect(receipt.plan_sha256).toBe(plan.plan_sha256);
  expect(receipt.manifest_digest).toBe(entry.manifest_digest);
  await expect(page.getByTestId('workspace-app-receipt')).toContainText(operation);
  return receipt;
}

async function cleanup(page: Page, candidate: Candidate | null): Promise<void> {
  if (!candidate) return;
  const ledger = await api<{ installations: Installation[] }>(
    page,
    candidate.workspace.slug,
    '/governance/workspace-apps/installations',
  );
  expect(ledger.ok, `cleanup ledger read failed (${ledger.status})`).toBe(true);
  const row = ledger.body.installations.find((entry) => entry.app_id === candidate.initial.app_id);
  const exactInitial = row?.state === 'installed'
    && row.version === candidate.initial.version
    && row.manifest_digest === candidate.initial.manifest_digest
    && canonical(row.configuration ?? {}) === canonical(candidate.initialInstallation.configuration ?? {});

  if (!exactInitial && row?.state === 'installed') {
    const current = candidate.versions.find((entry) => (
      entry.version === row.version && entry.manifest_digest === row.manifest_digest
    ));
    if (!current) {
      throw new Error('cleanup cannot acknowledge an installed manifest absent from the trusted registry');
    }
    await planAndApplyApi(
      page,
      candidate.workspace,
      'uninstall',
      current,
      `lot9-cleanup-uninstall:${hash(`${candidate.workspace.id}:${current.manifest_digest}:${Date.now()}`)}`,
    );
  }

  if (!exactInitial) {
    await planAndApplyApi(
      page,
      candidate.workspace,
      'install',
      candidate.initial,
      `lot9-cleanup-install:${hash(`${candidate.workspace.id}:${candidate.initial.manifest_digest}:${Date.now()}`)}`,
      candidate.initialInstallation.configuration ?? {},
    );
  }

  const restored = await api<{ installations: Installation[] }>(
    page,
    candidate.workspace.slug,
    '/governance/workspace-apps/installations',
  );
  expect(restored.ok, `cleanup verification failed (${restored.status})`).toBe(true);
  expect(ledgerSubject(restored.body.installations)).toEqual(ledgerSubject(candidate.initialInstallations));
  expect(ledgerDigest(restored.body.installations)).toBe(candidate.initialLedgerSha256);
}

test.describe.serial('Lot 9 — Workspace App preflight canary', () => {
  test.skip(!enabled, 'Set E2E_LOT9_CANARY=1 to execute the mutating Lot 9 canary');

  test('discovers the dedicated target and leaves a proven nonempty installation set', async ({ page }) => {
    expect(expectedSha, 'E2E_EXPECTED_SHA must be the deployed full SHA').toMatch(/^[0-9a-f]{40}$/);
    for (const path of ['/api/v1/build-info', '/build-info.json']) {
      const response = await page.request.get(`${path}?canary=${Date.now()}`, {
        headers: { Accept: 'application/json', 'Cache-Control': 'no-cache' },
      });
      expect(response.ok(), `${path} must be readable`).toBe(true);
      expect(await response.json()).toMatchObject({ revision: expectedSha, revision_verified: true });
    }

    const workspaces = await login(page);
    let candidate: Candidate | null = null;
    let succeeded = false;
    try {
      candidate = await discover(page, workspaces);
      const runNonce = randomUUID();
      await planAndApplyApi(
        page,
        candidate.workspace,
        'uninstall',
        candidate.initial,
        `lot9-normalize-uninstall:${hash(`${runNonce}:${candidate.workspace.id}:${candidate.initial.manifest_digest}`)}`,
      );
      const normalized = await planAndApplyApi(
        page,
        candidate.workspace,
        'install',
        candidate.oldest,
        `lot9-normalize-install:${hash(`${runNonce}:${candidate.workspace.id}:${candidate.oldest.manifest_digest}`)}`,
        candidate.initial.manifest_digest === candidate.oldest.manifest_digest
          ? candidate.initialInstallation.configuration ?? {}
          : undefined,
      );
      expect(normalized.receipt.installation).toMatchObject({
        state: 'installed',
        version: candidate.oldest.version,
        manifest_digest: candidate.oldest.manifest_digest,
      });

      await page.evaluate((slug) => localStorage.setItem('agentium_workspace_slug', slug), candidate.workspace.slug);
      await page.goto('/governance/workspace-apps');
      await expect(page.getByTestId('workspace-app-catalog')).toBeVisible();
      const upgrade = await applyThroughUi(page, 'upgrade', candidate.newest);
      expect(upgrade.installation.version).toBe(candidate.newest.version);
      const rollback = await applyThroughUi(page, 'rollback', candidate.oldest);
      expect(rollback.installation.version).toBe(candidate.oldest.version);
      const uninstalled = await applyThroughUi(page, 'uninstall', candidate.oldest);
      expect(uninstalled.installation).toMatchObject({
        state: 'uninstalled',
        version: null,
        manifest_digest: null,
      });

      const restoreKey = `lot9-reinstall:${hash(`${runNonce}:${candidate.workspace.id}:${candidate.initial.manifest_digest}`)}`;
      const restored = await planAndApplyApi(
        page,
        candidate.workspace,
        'install',
        candidate.initial,
        restoreKey,
        candidate.initialInstallation.configuration ?? {},
      );
      expect(restored.receipt.installation).toMatchObject({
        state: 'installed',
        version: candidate.initial.version,
        manifest_digest: candidate.initial.manifest_digest,
        configuration: candidate.initialInstallation.configuration ?? {},
      });
      const replayResult = await api<LifecycleReceipt>(
        page,
        candidate.workspace.slug,
        '/governance/workspace-apps/apply',
        {
          method: 'POST',
          idempotencyKey: restoreKey,
          body: {
            ...request(
              'install',
              candidate.initial,
              candidate.initialInstallation.configuration ?? {},
            ),
            expected_plan_sha256: restored.plan.plan_sha256,
          },
        },
      );
      expect(replayResult.ok).toBe(true);
      expect(replayResult.body.idempotent_replay).toBe(true);
      expect(replayResult.body.operation_id).toBe(restored.receipt.operation_id);

      const finalLedger = await api<{ workspace_id: string; installations: Installation[] }>(
        page,
        candidate.workspace.slug,
        '/governance/workspace-apps/installations',
      );
      expect(finalLedger.ok).toBe(true);
      expect(finalLedger.body.installations.find((row) => row.app_id === candidate?.oldest.app_id))
        .toMatchObject({
          state: 'installed',
          version: candidate.initial.version,
          manifest_digest: candidate.initial.manifest_digest,
          configuration: candidate.initialInstallation.configuration ?? {},
        });
      expect(installationSubject(finalLedger.body.installations))
        .toEqual(installationSubject(candidate.initialInstallations));
      expect(installationDigest(finalLedger.body.installations))
        .toBe(candidate.initialInstallationsSha256);
      expect(ledgerSubject(finalLedger.body.installations))
        .toEqual(ledgerSubject(candidate.initialInstallations));
      expect(ledgerDigest(finalLedger.body.installations))
        .toBe(candidate.initialLedgerSha256);
      writeEvidence(evidencePath, {
        schema_version: 1,
        kind: 'lot9_workspace_app_preflight_observation',
        tested_revision: expectedSha,
        generated_at: new Date().toISOString(),
        runner: {
          protected_ci: process.env['CI'] === 'true'
            && process.env['CI_COMMIT_REF_PROTECTED'] === 'true',
          pipeline_id: process.env['CI_PIPELINE_ID'] ?? null,
          job_id: process.env['CI_JOB_ID'] ?? null,
        },
        target: {
          workspace_sha256: hash(candidate.workspace.id),
          installations_sha256: candidate.initialInstallationsSha256,
        },
        checks: {
          lifecycle_idempotency: true,
          upgrade_rollback_uninstall: true,
          legacy_gate_off: true,
        },
        diagnostics: {
          exact_initial_ledger_restored: true,
          exact_initial_reinstalled: true,
          restored_runtime_shell: candidate.runtimeShell,
          restored_entry_policy: candidate.entryPolicy,
          restored_declared_entitlement_count: candidate.declaredEntitlementCount,
          ledger_sha256: candidate.initialLedgerSha256,
          exercised_manifest_digests: [
            candidate.oldest.manifest_digest,
            candidate.newest.manifest_digest,
            candidate.initial.manifest_digest,
          ],
          lifecycle_operation_proofs: [
            normalized.receipt,
            upgrade,
            rollback,
            uninstalled,
            restored.receipt,
          ].map(lifecycleOperationProof),
          idempotent_replay_proof: {
            operation_id_sha256: hash(restored.receipt.operation_id),
            replayed_operation_id_sha256: hash(replayResult.body.operation_id),
            idempotent_replay: replayResult.body.idempotent_replay,
          },
          restored_manifest_digest: candidate.initial.manifest_digest,
          final_installed_count: installationSubject(finalLedger.body.installations).length,
        },
      });
      succeeded = true;
    } finally {
      if (!succeeded) await cleanup(page, candidate);
      await logout(page);
    }
  });
});
