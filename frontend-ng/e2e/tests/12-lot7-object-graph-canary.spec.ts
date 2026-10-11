import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { expect, test, type Page, type TestInfo } from '@playwright/test';

/**
 * Lot 7 — authenticated, sequential object-graph rollout canary.
 *
 * The target is discovered only through the persisted
 * `settings.experience.system_360_canary = "v1"` marker. No workspace slug,
 * object name or database id is part of this test. The same suite validates
 * Capability, Run and SkillInvocation one at a time through
 * E2E_LOT7_PROJECTION.
 *
 * This suite intentionally keeps traces, video and screenshots disabled: it
 * authenticates with a live principal and emits only a redacted JSON proof.
 */

const enabled = process.env['E2E_LOT7_CANARY'] === '1';
const username = process.env['E2E_USERNAME'];
const password = process.env['E2E_PASSWORD'];
const expectedSha = (process.env['E2E_EXPECTED_SHA'] ?? '').trim().toLowerCase();
const requestedWorkspaceId = process.env['E2E_LOT7_WORKSPACE_ID']?.trim();
const evidencePath = process.env['E2E_LOT7_EVIDENCE'];
const baseUrl = process.env['E2E_BASE_URL'] ?? 'https://agentium.papai.ai';
const environment = process.env['E2E_ENVIRONMENT']?.trim() || new URL(baseUrl).hostname;
const runnerContext = {
  project_id: process.env['CI_PROJECT_ID']?.trim(),
  pipeline_id: process.env['CI_PIPELINE_ID']?.trim(),
  job_id: process.env['CI_JOB_ID']?.trim(),
};

const projections = ['capability', 'run', 'skill_invocation'] as const;
const lenses = ['build', 'operate', 'steer', 'govern'] as const;

type Projection = (typeof projections)[number];
type Lens = (typeof lenses)[number];

const projectionConfig: Record<Projection, {
  feature: string;
  objectType: Projection;
  facets: readonly string[];
  appSelector: string;
  tablistLabel: string;
}> = {
  capability: {
    feature: 'capability_360_projection_v1',
    objectType: 'capability',
    facets: ['overview', 'systems', 'outcomes', 'policies'],
    appSelector: 'app-capability-view',
    tablistLabel: 'Capability facets',
  },
  run: {
    feature: 'run_360_projection_v1',
    objectType: 'run',
    facets: ['overview', 'invocations', 'payloads', 'checkpoints'],
    appSelector: 'app-run-view',
    tablistLabel: 'Run facets',
  },
  skill_invocation: {
    feature: 'skill_invocation_360_projection_v1',
    objectType: 'skill_invocation',
    facets: ['overview', 'io', 'runtime', 'governance'],
    appSelector: 'app-skill-invocation-view',
    tablistLabel: 'Skill invocation facets',
  },
};

test.use({ trace: 'off', video: 'off', screenshot: 'off' });

interface WorkspaceSummary {
  id: string;
  slug: string;
  name: string;
  mode?: string;
  settings?: Record<string, unknown>;
}

interface SystemRow {
  id: string;
  capability_id?: string | null;
  status?: string;
  settings?: Record<string, unknown>;
}

interface CapabilityRow {
  id: string;
  slug: string;
  name: string;
}

interface SkillRow {
  id: string;
  slug: string;
  name: string;
}

interface InvocationRow {
  id?: string;
  run_id?: string;
  skill_id?: string | null;
  skill_slug?: string | null;
  status?: string;
  execution_evidence?: {
    resolution?: string | null;
    execution_snapshot_sha256?: string | null;
  };
}

interface RunRow {
  id: string;
  system_id?: string | null;
  capability_id?: string | null;
  status?: string;
  started_at?: string | null;
  completed_at?: string | null;
  flow_evidence?: {
    flow_version_id?: string | null;
    flow_snapshot_sha256?: string | null;
    execution_snapshot_at?: string | null;
    runtime_revision?: string | null;
  };
  invocations?: InvocationRow[];
  skill_invocations?: InvocationRow[];
}

interface ProjectionGateRow {
  projection: Projection;
  feature: string;
  phase?: 'probation' | 'verified';
  revision: string;
  system_id: string;
  capability_id: string;
  evidence_sha256?: string;
  lease_id?: string;
  staged_at?: string;
  expires_at?: string;
}

interface PerspectiveFact {
  key: string;
  label: string;
  state: 'available' | 'not_measured' | 'not_configured' | 'restricted' | 'unavailable';
  value: unknown | null;
}

interface PerspectiveBlock {
  id: string;
  title: string;
  facts: PerspectiveFact[];
}

interface ObjectPerspective {
  schema_version: 1;
  snapshot_id: string;
  generated_at: string;
  window: string;
  identity: {
    workspace_id: string;
    object_type: Projection;
    object_id: string;
    capability_id?: string | null;
    system_id?: string | null;
    run_id?: string | null;
    skill_id?: string | null;
    skill_slug?: string | null;
    skill_invocation_id?: string | null;
  };
  header: Record<string, PerspectiveFact>;
  lens: Lens;
  facets: Record<string, { blocks: PerspectiveBlock[] }>;
}

interface BuildInfo {
  revision: string;
  service: 'backend' | 'frontend';
  revision_verified: boolean;
}

interface ApiResult<T> {
  ok: boolean;
  status: number;
  body: T;
}

interface RuntimeTarget {
  run: RunRow;
  invocation: InvocationRow & { id: string };
  invocations: Array<InvocationRow & { id: string }>;
  catalogSkill: SkillRow;
}

interface ProjectionTarget {
  objectId: string;
  apiPath: (lens: Lens) => string;
  uiPath: string;
}

interface GateOffCandidate {
  workspace: WorkspaceSummary;
  objectId: string;
  perspectivePath: string;
  legacyPath: string;
  legacyKind: 'capability' | 'run' | 'run_with_invocation';
  invocationLabel?: string;
}

function isProjection(value: unknown): value is Projection {
  return typeof value === 'string' && projections.includes(value as Projection);
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function features(settings: Record<string, unknown> | undefined): Record<string, unknown> {
  return asRecord(settings?.['features']) ?? {};
}

function projectionGateRows(settings: Record<string, unknown> | undefined): ProjectionGateRow[] {
  const gate = asRecord(settings?.['_lot7_projection_gate_v1']);
  expect(gate?.['schema_version'], 'the server-owned Lot 7 gate must use schema v1').toBe(1);
  const rows = gate?.['activations'];
  expect(Array.isArray(rows), 'the server-owned Lot 7 gate must expose activations').toBe(true);
  return (rows as unknown[]).map((value, index) => {
    const row = asRecord(value);
    expect(row, `Lot 7 gate row ${index} must be an object`).toBeTruthy();
    expect(isProjection(row?.['projection']), `Lot 7 gate row ${index} has an unknown projection`).toBe(true);
    return row as unknown as ProjectionGateRow;
  });
}

function marker(system: SystemRow): unknown {
  return asRecord(asRecord(system.settings)?.['experience'])?.['system_360_canary'];
}

function unwrap<T>(body: T[] | Record<string, T[]>, key: string): T[] {
  if (Array.isArray(body)) return body;
  const value = body?.[key];
  return Array.isArray(value) ? value : [];
}

function projectionWasRevoked(result: ApiResult<unknown>): boolean {
  const body = asRecord(result.body);
  const detail = asRecord(body?.['detail']);
  return result.status === 410 && detail?.['code'] === 'OBJECT_PROJECTION_REVOKED';
}

function stableJson(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${stableJson(record[key])}`).join(',')}}`;
}

function fingerprint(value: unknown): string {
  return createHash('sha256').update(stableJson(value)).digest('hex');
}

function normalizedText(value: string): string {
  return value.replace(/\s+/g, ' ').trim();
}

function simpleFactValue(value: unknown): string {
  if (value == null) return '—';
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>;
    return String(record['name'] ?? record['label'] ?? record['slug'] ?? record['id'] ?? JSON.stringify(value));
  }
  return String(value);
}

function formattedFactValue(value: unknown): string {
  if (value == null) return 'Unavailable';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(simpleFactValue).join(' · ');
  return JSON.stringify(value);
}

function utcEvidenceTimestamp(value: string): string {
  const normalized = value.trim();
  if (/Z$|[+-]\d{2}:\d{2}$/.test(normalized)) return normalized;
  // Backend DateTime columns are UTC-naive and may carry six microsecond
  // digits. Appending Z preserves that precision; Date#toISOString would
  // silently truncate it to milliseconds and break exact DB revalidation.
  return `${normalized}Z`;
}

function xmlAttribute(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('"', '&quot;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
}

function writeJson(path: string, value: unknown): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, {
    encoding: 'utf8',
    mode: 0o600,
  });
}

async function switchWorkspaceThroughTitleBar(
  page: Page,
  from: WorkspaceSummary,
  to: WorkspaceSummary,
): Promise<void> {
  const nextWorkspaceRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname.startsWith('/api/v1/')
      && request.headers()['x-workspace-slug'] === to.slug;
  });
  await page.getByTestId('workspace-switcher-toggle').click();
  await page.locator('app-title-bar button').filter({ hasText: to.name }).first().click();
  await nextWorkspaceRequest;
  await expect.poll(() => page.evaluate(() => localStorage.getItem('agentium_workspace_slug')))
    .toBe(to.slug);
}

async function login(page: Page): Promise<WorkspaceSummary[]> {
  expect(username, 'E2E_USERNAME is required for the Lot 7 canary').toBeTruthy();
  expect(password, 'E2E_PASSWORD is required for the Lot 7 canary').toBeTruthy();
  await page.goto('/auth/signin');
  const result = await page.evaluate(
    async ({ email, secret }) => {
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
    },
    { email: username as string, secret: password as string },
  );
  expect(result.ok, `login or workspace discovery failed (${result.status})`).toBe(true);
  const workspaces = (Array.isArray(result.workspaces) ? result.workspaces : []) as WorkspaceSummary[];
  expect(workspaces.length, 'the canary principal needs at least one authorized workspace').toBeGreaterThan(0);
  return workspaces;
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
    localStorage.removeItem('agentium_workspace_slug');
  }).catch(() => undefined);
}

async function api<T>(
  page: Page,
  workspaceSlug: string,
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<ApiResult<T>> {
  return page.evaluate(
    async ({ slug, apiPath, method, body }) => {
      const response = await fetch(`/api/v1${apiPath}`, {
        method,
        headers: {
          Authorization: localStorage.getItem('agentium_token') || '',
          'X-Workspace-Slug': slug,
          ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const text = await response.text();
      let responseBody: unknown = null;
      if (text) {
        try { responseBody = JSON.parse(text); } catch { responseBody = text; }
      }
      return { ok: response.ok, status: response.status, body: responseBody };
    },
    { slug: workspaceSlug, apiPath: path, method: options.method ?? 'GET', body: options.body },
  ) as Promise<ApiResult<T>>;
}

async function buildInfo(page: Page, path: string): Promise<BuildInfo> {
  const response = await page.request.get(`${path}?canary=${Date.now()}`, {
    headers: { Accept: 'application/json', 'Cache-Control': 'no-cache' },
  });
  expect(response.ok(), `${path} must be readable`).toBe(true);
  return response.json() as Promise<BuildInfo>;
}

async function workspaceDetail(page: Page, workspace: WorkspaceSummary): Promise<WorkspaceSummary> {
  const result = await api<WorkspaceSummary>(
    page,
    workspace.slug,
    `/auth/workspaces/${encodeURIComponent(workspace.slug)}`,
  );
  expect(result.ok, `workspace ${workspace.id} details must be readable`).toBe(true);
  return result.body;
}

async function discoverRuntimeTarget(
  page: Page,
  workspace: WorkspaceSummary,
  system: SystemRow,
  runId: string,
  stagedAt: string,
  revision: string,
): Promise<RuntimeTarget> {
  const skillResult = await api<SkillRow[] | { skills: SkillRow[] }>(page, workspace.slug, '/skills');
  expect(skillResult.ok, 'the catalog Skill list must be readable').toBe(true);
  const skills = unwrap(skillResult.body, 'skills');
  const stagedAtMs = new Date(stagedAt).getTime();
  expect(Number.isFinite(stagedAtMs), 'probation.staged_at must be parseable').toBe(true);

  const detail = await api<RunRow>(page, workspace.slug, `/runs/${encodeURIComponent(runId)}`);
  expect(detail.ok, `triggered Run ${runId} must be readable`).toBe(true);
  expect(detail.body.id, 'the runtime proof must use exactly the triggered Run id').toBe(runId);
  const flowEvidence = detail.body.flow_evidence;
  const executionSnapshotAt = new Date(flowEvidence?.execution_snapshot_at ?? '').getTime();
  expect(detail.body.status, 'the triggered Run must complete successfully').toBe('completed');
  expect(detail.body.system_id).toBe(system.id);
  expect(detail.body.started_at).toBeTruthy();
  expect(detail.body.completed_at).toBeTruthy();
  expect(flowEvidence?.flow_version_id, 'the triggered Run needs an exact flow version').toBeTruthy();
  expect(flowEvidence?.flow_snapshot_sha256).toMatch(/^[0-9a-f]{64}$/);
  expect(flowEvidence?.runtime_revision).toBe(revision);
  expect(Number.isFinite(executionSnapshotAt)).toBe(true);
  expect(executionSnapshotAt).toBeGreaterThanOrEqual(stagedAtMs);

  const fullLedger = detail.body.invocations ?? detail.body.skill_invocations ?? [];
  const invocations = fullLedger.filter((item): item is InvocationRow & { id: string } =>
    typeof item.id === 'string'
    && item.id.length > 0
    && item.status === 'completed'
    && item.execution_evidence?.resolution === 'resolved'
    && /^[0-9a-f]{64}$/.test(item.execution_evidence.execution_snapshot_sha256 ?? ''),
  );
  expect(invocations.length, 'the triggered Run needs a non-empty invocation ledger').toBeGreaterThan(0);
  expect(invocations.length, 'every invocation must be completed with a resolved snapshot')
    .toBe(fullLedger.length);
  const invocation = invocations.find((item) => skills.some((skill) =>
    (item.skill_slug && skill.slug === item.skill_slug)
    || (item.skill_id && skill.id === item.skill_id),
  ));
  expect(invocation, 'one immutable invocation must resolve to a visible catalog Skill').toBeTruthy();
  const catalogSkill = skills.find((skill) =>
    (invocation!.skill_slug && skill.slug === invocation!.skill_slug)
    || (invocation!.skill_id && skill.id === invocation!.skill_id),
  );
  expect(catalogSkill).toBeTruthy();
  return { run: detail.body, invocation: invocation!, invocations, catalogSkill: catalogSkill! };
}

async function triggerAndAwaitCanaryRun(
  page: Page,
  workspace: WorkspaceSummary,
  system: SystemRow,
  expiresAtMs: number,
): Promise<string> {
  let inputRef: Record<string, unknown> = {
    query: 'Run the authenticated Lot 7 projection canary against the configured context.',
    lot7_projection_canary: true,
  };
  const configuredInput = process.env['E2E_LOT7_RUN_INPUT_JSON'];
  if (configuredInput) {
    const parsed = JSON.parse(configuredInput) as unknown;
    expect(asRecord(parsed), 'E2E_LOT7_RUN_INPUT_JSON must encode one JSON object').toBeTruthy();
    inputRef = parsed as Record<string, unknown>;
  }
  const triggered = await api<{ id?: string; status?: string }>(
    page,
    workspace.slug,
    `/systems/${encodeURIComponent(system.id)}/runs`,
    {
      method: 'POST',
      body: { trigger: 'lot7_projection_canary', input_ref: inputRef },
    },
  );
  expect(triggered.ok, `failed to trigger the Lot 7 canary Run (${triggered.status})`).toBe(true);
  expect(triggered.body.id).toBeTruthy();
  const runId = triggered.body.id as string;
  const deadline = Math.min(Date.now() + 5 * 60 * 1_000, expiresAtMs - 10_000);
  while (Date.now() < deadline) {
    const current = await api<RunRow>(page, workspace.slug, `/runs/${encodeURIComponent(runId)}`);
    expect(current.ok, `triggered Run ${runId} became unreadable`).toBe(true);
    if (current.body.status === 'completed') return runId;
    if (['failed', 'cancelled', 'hitl_pending'].includes(current.body.status ?? '')) {
      throw new Error(
        `triggered Run ${runId} reached non-automatic terminal state ${current.body.status}`,
      );
    }
    await page.waitForTimeout(1_000);
  }
  throw new Error(`triggered Run ${runId} did not complete before the canary deadline`);
}

function targetFor(
  projection: Projection,
  capability: CapabilityRow,
  runtime: RuntimeTarget,
  system: SystemRow,
): ProjectionTarget {
  if (projection === 'capability') {
    return {
      objectId: capability.id,
      apiPath: (lens) => `/capabilities/${encodeURIComponent(capability.id)}/perspective?lens=${lens}&window=30d`,
      uiPath: `/capabilities/${encodeURIComponent(capability.id)}`,
    };
  }
  if (projection === 'run') {
    return {
      objectId: runtime.run.id,
      apiPath: (lens) => `/runs/${encodeURIComponent(runtime.run.id)}/perspective?lens=${lens}&window=30d`,
      uiPath: `/runs/${encodeURIComponent(runtime.run.id)}?capabilityId=${encodeURIComponent(capability.id)}&systemId=${encodeURIComponent(system.id)}`,
    };
  }
  return {
    objectId: runtime.invocation.id,
    apiPath: (lens) => `/runs/${encodeURIComponent(runtime.run.id)}/invocations/${encodeURIComponent(runtime.invocation.id)}/perspective?lens=${lens}&window=30d`,
    uiPath: `/runs/${encodeURIComponent(runtime.run.id)}/invocations/${encodeURIComponent(runtime.invocation.id)}?capabilityId=${encodeURIComponent(capability.id)}&systemId=${encodeURIComponent(system.id)}`,
  };
}

async function candidateForGateOff(
  page: Page,
  projection: Projection,
  workspace: WorkspaceSummary,
): Promise<GateOffCandidate | null> {
  const detail = await workspaceDetail(page, workspace);
  const workspaceFeatures = features(detail.settings);
  if (workspaceFeatures[projectionConfig[projection].feature] === true) return null;

  if (projection === 'capability') {
    const result = await api<CapabilityRow[] | { capabilities: CapabilityRow[] }>(
      page,
      workspace.slug,
      '/capabilities',
    );
    const capability = result.ok ? unwrap(result.body, 'capabilities')[0] : undefined;
    if (!capability) return null;
    return {
      workspace: detail,
      objectId: capability.id,
      perspectivePath: `/capabilities/${encodeURIComponent(capability.id)}/perspective?lens=build&window=30d`,
      legacyPath: `/capabilities/${encodeURIComponent(capability.id)}?lens=build`,
      legacyKind: 'capability',
    };
  }

  // A legacy Run is required, not an arbitrary id. For SkillInvocation we
  // additionally require one persisted invocation embedded in that Run.
  if (workspaceFeatures['run_360_projection_v1'] === true) return null;
  const result = await api<RunRow[] | { runs: RunRow[] }>(page, workspace.slug, '/runs?limit=100');
  if (!result.ok) return null;
  for (const row of unwrap(result.body, 'runs')) {
    const detailResult = await api<RunRow>(page, workspace.slug, `/runs/${encodeURIComponent(row.id)}`);
    if (!detailResult.ok) continue;
    if (projection === 'run') {
      return {
        workspace: detail,
        objectId: row.id,
        perspectivePath: `/runs/${encodeURIComponent(row.id)}/perspective?lens=build&window=30d`,
        legacyPath: `/runs/${encodeURIComponent(row.id)}?lens=build`,
        legacyKind: 'run',
      };
    }
    const invocation = [...(detailResult.body.invocations ?? detailResult.body.skill_invocations ?? [])]
      .find((item): item is InvocationRow & { id: string } => typeof item.id === 'string' && item.id.length > 0);
    if (!invocation) continue;
    return {
      workspace: detail,
      objectId: invocation.id,
      perspectivePath: `/runs/${encodeURIComponent(row.id)}/invocations/${encodeURIComponent(invocation.id)}/perspective?lens=build&window=30d`,
      legacyPath: `/runs/${encodeURIComponent(row.id)}?lens=build`,
      legacyKind: 'run_with_invocation',
      invocationLabel: invocation.skill_slug || invocation.skill_id || invocation.id,
    };
  }
  return null;
}

async function proveLegacyUi(page: Page, candidate: GateOffCandidate): Promise<void> {
  await page.evaluate((slug) => localStorage.setItem('agentium_workspace_slug', slug), candidate.workspace.slug);
  await page.goto(candidate.legacyPath);
  await expect.poll(() => page.evaluate(() => localStorage.getItem('agentium_workspace_slug')))
    .toBe(candidate.workspace.slug);
  if (candidate.legacyKind === 'capability') {
    await expect(page.locator('app-capability-view')).toBeVisible();
    await expect(page.locator('app-capability-view ck-object-perspective')).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'Purpose', exact: true })).toBeVisible();
    return;
  }
  await expect(page.locator('app-run-view ck-page-frame')).toBeVisible();
  await expect(page.locator('app-run-view ck-object-perspective')).toHaveCount(0);
  if (candidate.legacyKind === 'run_with_invocation') {
    await expect(page.getByText(candidate.invocationLabel as string, { exact: true }).first()).toBeVisible();
    await expect(page.locator('[data-testid="run-skill-invocation-links"]')).toHaveCount(0);
  }
}

async function legacyUiIsReachable(page: Page, candidate: GateOffCandidate): Promise<boolean> {
  await page.evaluate((slug) => localStorage.setItem('agentium_workspace_slug', slug), candidate.workspace.slug);
  await page.goto(candidate.legacyPath);
  if (candidate.legacyKind === 'capability') {
    const component = await page.locator('app-capability-view').isVisible({ timeout: 5_000 }).catch(() => false);
    const purpose = await page.getByRole('heading', { name: 'Purpose', exact: true })
      .isVisible({ timeout: 2_000 }).catch(() => false);
    return component && purpose && await page.locator('app-capability-view ck-object-perspective').count() === 0;
  }
  const frame = await page.locator('app-run-view ck-page-frame').isVisible({ timeout: 5_000 }).catch(() => false);
  if (!frame || await page.locator('app-run-view ck-object-perspective').count() !== 0) return false;
  if (candidate.legacyKind !== 'run_with_invocation') return true;
  const invocation = await page.getByText(candidate.invocationLabel as string, { exact: true })
    .first().isVisible({ timeout: 2_000 }).catch(() => false);
  return invocation && await page.locator('[data-testid="run-skill-invocation-links"]').count() === 0;
}

async function chromeSignature(
  page: Page,
  config: (typeof projectionConfig)[Projection],
): Promise<Record<string, unknown>> {
  const root = page.locator(config.appSelector);
  return {
    header: normalizedText(await root.locator('ck-object-header header').innerText()),
    tabs: (await root.getByRole('tablist', { name: config.tablistLabel }).getByRole('tab').allTextContents())
      .map(normalizedText),
  };
}

async function selectLens(
  page: Page,
  lens: Lens,
  expectedPath: string,
  config: (typeof projectionConfig)[Projection],
  objectId: string,
): Promise<void> {
  const label = lens[0].toUpperCase() + lens.slice(1);
  const link = page.locator('app-side-rail a.ck-rail-item').filter({ hasText: new RegExp(label, 'i') });
  await expect(link).toHaveCount(1);
  await link.click();
  await expect.poll(() => {
    const url = new URL(page.url());
    return `${url.pathname}|${url.searchParams.get('lens')}`;
  }).toBe(`${expectedPath}|${lens}`);
  await expect(page.locator(
    `${config.appSelector} ck-object-perspective section[data-object-type="${config.objectType}"][data-object-id="${objectId}"][data-perspective-lens="${lens}"][data-perspective-facet="overview"]`,
  )).toBeVisible();
}

test.describe.serial('Lot 7 — authenticated object graph rollout canary', () => {
  test.skip(!enabled, 'Set E2E_LOT7_CANARY=1 to exercise the deployed Lot 7 canary');

  test.afterEach(async ({ page }) => logout(page));

  test('attests one sequential projection without collapsing runtime into catalog', async ({ page }, testInfo: TestInfo) => {
    const requestedProjection = process.env['E2E_LOT7_PROJECTION'];
    expect(isProjection(requestedProjection), 'E2E_LOT7_PROJECTION must be capability, run or skill_invocation')
      .toBe(true);
    const projection = requestedProjection as Projection;
    const config = projectionConfig[projection];
    expect(expectedSha, 'E2E_EXPECTED_SHA must be the deployed full SHA').toMatch(/^[0-9a-f]{40}$/);

    const backendBuild = await buildInfo(page, '/api/v1/build-info');
    const frontendBuild = await buildInfo(page, '/build-info.json');
    expect(backendBuild).toMatchObject({
      revision: expectedSha,
      service: 'backend',
      revision_verified: true,
    });
    expect(frontendBuild).toMatchObject({
      revision: expectedSha,
      service: 'frontend',
      revision_verified: true,
    });

    const memberships = await login(page);
    const scopedMemberships = requestedWorkspaceId
      ? memberships.filter((workspace) => workspace.id === requestedWorkspaceId)
      : memberships;
    if (requestedWorkspaceId) {
      expect(
        scopedMemberships,
        'E2E_LOT7_WORKSPACE_ID must identify one Workspace authorized for the canary principal',
      ).toHaveLength(1);
    }
    const discoveries: Array<{ workspace: WorkspaceSummary; system: SystemRow }> = [];
    for (const membership of scopedMemberships) {
      const workspace = await workspaceDetail(page, membership);
      const result = await api<SystemRow[] | { systems: SystemRow[] }>(
        page,
        workspace.slug,
        '/systems?status=active&limit=2147483647',
      );
      expect(result.ok, `Systems must be readable for authorized workspace ${workspace.id}`).toBe(true);
      const marked = unwrap(result.body, 'systems').filter((system) => marker(system) === 'v1');
      if (requestedWorkspaceId) {
        expect(
          marked,
          'the explicitly targeted Workspace must contain exactly one active v1 canary marker',
        ).toHaveLength(1);
      } else if (marked.length !== 1) {
        continue;
      }
      const system = marked[0];
      const gate = asRecord(workspace.settings?.['_lot7_projection_gate_v1']);
      const rows = Array.isArray(gate?.['activations']) ? gate?.['activations'] as unknown[] : [];
      const matchingProbation = rows.some((item) => {
        const row = asRecord(item);
        return row?.['projection'] === projection
          && row?.['phase'] === 'probation'
          && row?.['revision'] === expectedSha
          && row?.['system_id'] === system.id;
      });
      if (!requestedWorkspaceId && !matchingProbation) continue;
      discoveries.push({ workspace, system });
    }
    expect(
      discoveries,
      'exactly one targeted Workspace must contain one v1 marker and this projection/SHA probation',
    ).toHaveLength(1);
    const { workspace, system } = discoveries[0];
    expect(system.capability_id, 'the marked System must have a Capability').toBeTruthy();
    const workspaceFeatures = features(workspace.settings);
    expect(workspaceFeatures[config.feature], `${config.feature} must be explicitly enabled`).toBe(true);
    const projectionIndex = projections.indexOf(projection);
    for (const predecessor of projections.slice(0, projectionIndex + 1)) {
      expect(
        workspaceFeatures[projectionConfig[predecessor].feature],
        `${projectionConfig[predecessor].feature} must respect Capability→Run→SkillInvocation order`,
      ).toBe(true);
    }
    const gateRows = projectionGateRows(workspace.settings);
    expect(
      gateRows.map((row) => row.projection),
      'the server-owned gate must be the exact active Capability→Run→SkillInvocation prefix',
    ).toEqual(projections.slice(0, projectionIndex + 1));
    for (const [index, row] of gateRows.entries()) {
      const gatedProjection = projections[index];
      expect(row.feature).toBe(projectionConfig[gatedProjection].feature);
      expect(row.system_id).toBe(system.id);
      expect(row.capability_id).toBe(system.capability_id);
      expect(row.revision).toBe(expectedSha);
      if (index < projectionIndex) {
        expect(row.phase ?? 'verified').toBe('verified');
        expect(row.evidence_sha256).toMatch(/^[0-9a-f]{64}$/);
      }
    }
    const probation = gateRows[projectionIndex];
    expect(probation.phase, 'the projection under test must be inside its probation lease').toBe('probation');
    expect(probation.lease_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
    expect(probation.staged_at).toBeTruthy();
    expect(probation.expires_at).toBeTruthy();
    const probationStartedAt = new Date(probation.staged_at as string).getTime();
    const probationExpiresAt = new Date(probation.expires_at as string).getTime();
    expect(Number.isFinite(probationStartedAt)).toBe(true);
    expect(Number.isFinite(probationExpiresAt)).toBe(true);
    expect(probationExpiresAt).toBeGreaterThan(probationStartedAt);
    expect(probationExpiresAt - probationStartedAt).toBeLessThanOrEqual(30 * 60 * 1_000);
    expect(Date.now(), 'the probation lease must still be live').toBeLessThan(probationExpiresAt);

    const capabilitiesResult = await api<CapabilityRow[] | { capabilities: CapabilityRow[] }>(
      page,
      workspace.slug,
      '/capabilities',
    );
    expect(capabilitiesResult.ok).toBe(true);
    const capability = unwrap(capabilitiesResult.body, 'capabilities')
      .find((row) => row.id === system.capability_id);
    expect(capability, 'the marked System Capability must resolve in the same workspace').toBeTruthy();

    // A real execution is mandatory even for the Capability step. It gives
    // every activation proof a concrete catalog Skill/runtime invocation
    // distinction rather than a type-only assertion.
    const triggeredRunId = await triggerAndAwaitCanaryRun(
      page,
      workspace,
      system,
      probationExpiresAt,
    );
    const runtime = await discoverRuntimeTarget(
      page,
      workspace,
      system,
      triggeredRunId,
      probation.staged_at as string,
      expectedSha,
    );
    const flowEvidence = runtime.run.flow_evidence!;
    expect(runtime.run.status).toBe('completed');
    expect(flowEvidence.flow_version_id).toBeTruthy();
    expect(flowEvidence.flow_snapshot_sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(flowEvidence.runtime_revision).toBe(expectedSha);
    expect(new Date(flowEvidence.execution_snapshot_at as string).getTime())
      .toBeGreaterThanOrEqual(probationStartedAt);
    expect(runtime.invocations.length).toBeGreaterThan(0);
    expect(runtime.invocations.every((item) =>
      item.status === 'completed'
      && item.execution_evidence?.resolution === 'resolved'
      && /^[0-9a-f]{64}$/.test(item.execution_evidence.execution_snapshot_sha256 ?? ''),
    )).toBe(true);
    expect(runtime.invocation.id).not.toBe(runtime.catalogSkill.id);
    expect(runtime.invocation.skill_slug || runtime.invocation.skill_id).toBeTruthy();
    const rawInvocation = await api<InvocationRow>(
      page,
      workspace.slug,
      `/runs/${encodeURIComponent(runtime.run.id)}/invocations/${encodeURIComponent(runtime.invocation.id)}`,
    );
    if (workspaceFeatures['skill_invocation_360_projection_v1'] === true) {
      expect(rawInvocation.ok).toBe(true);
      expect(rawInvocation.body.id).toBe(runtime.invocation.id);
      expect(rawInvocation.body.run_id).toBe(runtime.run.id);
    } else {
      expect(rawInvocation.status, 'the runtime object route must stay closed before its rollout').toBe(404);
    }

    const target = targetFor(projection, capability as CapabilityRow, runtime, system);
    const payloads = {} as Record<Lens, ObjectPerspective>;
    for (const lens of lenses) {
      const result = await api<ObjectPerspective>(page, workspace.slug, target.apiPath(lens));
      expect(result.ok, `${projection}/${lens} perspective failed (${result.status})`).toBe(true);
      payloads[lens] = result.body;
      expect(result.body.schema_version).toBe(1);
      expect(result.body.lens).toBe(lens);
      expect(result.body.window).toBe('30d');
      expect(result.body.identity.workspace_id).toBe(workspace.id);
      expect(result.body.identity.object_type).toBe(config.objectType);
      expect(result.body.identity.object_id).toBe(target.objectId);
      expect(Object.keys(result.body.facets).sort()).toEqual([...config.facets].sort());
      for (const facet of config.facets) {
        expect(result.body.facets[facet]?.blocks.length, `${projection}/${lens}/${facet} needs blocks`)
          .toBeGreaterThan(0);
      }
    }
    const reference = payloads.build;
    for (const lens of lenses) {
      expect(payloads[lens].identity).toEqual(reference.identity);
      expect(payloads[lens].header).toEqual(reference.header);
      expect(payloads[lens].snapshot_id).toBe(reference.snapshot_id);
      expect(Object.keys(payloads[lens].facets).sort()).toEqual(Object.keys(reference.facets).sort());
    }
    const projectionHashes = Object.fromEntries(
      lenses.map((lens) => [lens, fingerprint(payloads[lens].facets)]),
    ) as Record<Lens, string>;
    expect(new Set(Object.values(projectionHashes)).size).toBe(4);
    const overviewBlocks = lenses.map((lens) =>
      payloads[lens].facets['overview'].blocks.map((block) => block.id).sort().join('|'),
    );
    expect(new Set(overviewBlocks).size).toBe(4);

    const targetPath = new URL(target.uiPath, baseUrl).pathname;
    await page.evaluate((slug) => localStorage.setItem('agentium_workspace_slug', slug), workspace.slug);
    const initialSeparator = target.uiPath.includes('?') ? '&' : '?';
    await page.goto(`${target.uiPath}${initialSeparator}lens=build`);
    await expect(page.locator(config.appSelector)).toBeVisible();
    await expect(page.locator(
      `${config.appSelector} ck-object-perspective section[data-object-type="${config.objectType}"][data-object-id="${target.objectId}"][data-perspective-lens="build"][data-perspective-facet="overview"]`,
    )).toBeVisible();
    const invariantChrome = await chromeSignature(page, config);
    expect(invariantChrome.tabs).toEqual(config.facets.map((facet) =>
      facet === 'io' ? 'I/O' : facet[0].toUpperCase() + facet.slice(1),
    ));

    const renderedFactSources = {} as Record<Lens, {
      block_id: string;
      fact_key: string;
      fact_label: string;
      fact_state: PerspectiveFact['state'];
      api_fact_sha256: string;
      rendered_text_sha256: string;
    }>;
    for (const lens of lenses) {
      if (lens !== 'build') await selectLens(page, lens, targetPath, config, target.objectId);
      const url = new URL(page.url());
      expect(url.pathname).toBe(targetPath);
      expect(url.searchParams.get('lens')).toBe(lens);
      expect(await chromeSignature(page, config)).toEqual(invariantChrome);
      const rendered = await page.locator(
        `${config.appSelector} #ck-tabpanel-overview article[data-block-id]`,
      ).evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-block-id')).filter(Boolean).sort());
      expect(rendered).toEqual(
        payloads[lens].facets['overview'].blocks.map((block) => block.id).sort(),
      );
      const sourceBlock = payloads[lens].facets['overview'].blocks[0];
      const sourceFact = sourceBlock?.facts[0];
      expect(sourceBlock, `${projection}/${lens} must expose one overview block`).toBeTruthy();
      expect(sourceFact, `${projection}/${lens} must expose one overview fact`).toBeTruthy();
      const renderedFact = page.locator(
        `${config.appSelector} #ck-tabpanel-overview article[data-block-id="${sourceBlock.id}"] `
          + `[data-fact-key="${sourceFact.key}"]`,
      );
      await expect(renderedFact.locator('dt')).toHaveText(sourceFact.label);
      if (sourceFact.state === 'available') {
        await expect(renderedFact.locator('.fact-value'))
          .toHaveText(formattedFactValue(sourceFact.value));
      } else {
        await expect(renderedFact.locator('.fact-state'))
          .toHaveAttribute('data-state', sourceFact.state);
      }
      const renderedFactText = normalizedText(await renderedFact.innerText());
      renderedFactSources[lens] = {
        block_id: sourceBlock.id,
        fact_key: sourceFact.key,
        fact_label: sourceFact.label,
        fact_state: sourceFact.state,
        api_fact_sha256: fingerprint(sourceFact),
        rendered_text_sha256: fingerprint(renderedFactText),
      };
    }

    if (projection === 'skill_invocation') {
      const catalogLink = page.getByRole('link', { name: 'Open catalog Skill', exact: true });
      await expect(catalogLink).toBeVisible();
      const href = await catalogLink.getAttribute('href');
      expect(href).toBeTruthy();
      const catalogPath = new URL(href as string, baseUrl).pathname;
      expect(catalogPath).toBe(`/skills/${encodeURIComponent(runtime.catalogSkill.slug)}`);
      expect(catalogPath).not.toBe(targetPath);
      expect(targetPath).toContain(`/runs/${runtime.run.id}/invocations/${runtime.invocation.id}`);
    }

    // The same authorized principal must see a real legacy object in a
    // second workspace where this exact gate is off. We also use that
    // workspace header against the target object, proving tenant isolation.
    const gateOffCandidates: GateOffCandidate[] = [];
    for (const alternate of memberships.filter((item) => item.id !== workspace.id)) {
      const candidate = await candidateForGateOff(page, projection, alternate);
      if (!candidate) continue;
      const isolationPath = projection === 'capability'
        ? `/capabilities/${encodeURIComponent(target.objectId)}`
        : `/runs/${encodeURIComponent(runtime.run.id)}`;
      const isolated = await api<unknown>(page, candidate.workspace.slug, isolationPath);
      if (isolated.status !== 404) continue;
      const disabled = await api<unknown>(page, candidate.workspace.slug, candidate.perspectivePath);
      if (!projectionWasRevoked(disabled)) continue;
      gateOffCandidates.push(candidate);
    }
    // Prefer a portfolio shell, but try every honest candidate: business
    // shells may intentionally deny canonical cockpit routes even though the
    // principal can read their APIs.
    gateOffCandidates.sort((left, right) =>
      Number(right.workspace.mode === 'portfolio') - Number(left.workspace.mode === 'portfolio'));
    let gateOff: GateOffCandidate | null = null;
    for (const candidate of gateOffCandidates) {
      if (await legacyUiIsReachable(page, candidate)) {
        gateOff = candidate;
        break;
      }
    }
    expect(
      gateOff,
      'a second authorized workspace with the gate off and a real legacy object is required',
    ).toBeTruthy();
    await proveLegacyUi(page, gateOff as GateOffCandidate);

    // Exercise the real SPA selector while one primary-workspace projection
    // is still in flight. Deliver that stale payload only after the alternate
    // workspace owns the shell; it must never repopulate the new context.
    await switchWorkspaceThroughTitleBar(
      page,
      (gateOff as GateOffCandidate).workspace,
      workspace,
    );
    await page.goto(`${target.uiPath}${initialSeparator}lens=build`);
    await expect(page.locator(
      `${config.appSelector} ck-object-perspective section[data-object-id="${target.objectId}"]`,
    )).toBeVisible();

    let releaseDelayedResponse!: () => void;
    let markDelayedRequestSeen!: () => void;
    let markDelayedResponseDelivered!: () => void;
    const delayedRelease = new Promise<void>((resolve) => { releaseDelayedResponse = resolve; });
    const delayedRequestSeen = new Promise<void>((resolve) => { markDelayedRequestSeen = resolve; });
    const delayedResponseDelivered = new Promise<void>(
      (resolve) => { markDelayedResponseDelivered = resolve; },
    );
    let delayed = false;
    const perspectiveRoute = '**/api/v1/**/perspective?*';
    const delayedPath = `/api/v1${target.apiPath('build').split('?')[0]}`;
    await page.route(perspectiveRoute, async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (
        !delayed
        && request.headers()['x-workspace-slug'] === workspace.slug
        && url.pathname === delayedPath
        && url.searchParams.get('lens') === 'build'
      ) {
        delayed = true;
        markDelayedRequestSeen();
        await delayedRelease;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(payloads.build),
        });
        markDelayedResponseDelivered();
        return;
      }
      await route.continue();
    });

    await page.reload();
    await delayedRequestSeen;
    await switchWorkspaceThroughTitleBar(
      page,
      workspace,
      (gateOff as GateOffCandidate).workspace,
    );
    await expect(page.locator(
      `${config.appSelector} ck-object-perspective section[data-object-id="${target.objectId}"]`,
    )).toHaveCount(0);
    expect(page.url()).not.toContain(target.objectId);
    releaseDelayedResponse();
    await delayedResponseDelivered;
    await expect(page.locator(
      `ck-object-perspective section[data-object-id="${target.objectId}"]`,
    )).toHaveCount(0);
    expect(page.url()).not.toContain(target.objectId);
    await page.unroute(perspectiveRoute);

    const validatedAt = new Date();
    expect(validatedAt.getTime(), 'validation must complete before the probation expires')
      .toBeLessThan(probationExpiresAt);
    const subject = {
      workspace_id: workspace.id,
      system_id: system.id,
      capability_id: capability!.id,
      projection,
    };
    const runnerPropertyRows = Object.entries(runnerContext)
      .filter((entry): entry is [string, string] => Boolean(entry[1]))
      .map(([key, value]) =>
        `<property name="runner_${xmlAttribute(key)}" value="${xmlAttribute(value)}" />`,
      );
    const junitXml = [
      `<testsuite name="lot7-object-graph-canary" tests="1" failures="0" errors="0" skipped="0">`,
      '<properties>',
      `<property name="revision" value="${xmlAttribute(expectedSha)}" />`,
      `<property name="workspace_id" value="${xmlAttribute(workspace.id)}" />`,
      `<property name="system_id" value="${xmlAttribute(system.id)}" />`,
      `<property name="capability_id" value="${xmlAttribute(capability!.id)}" />`,
      `<property name="projection" value="${xmlAttribute(projection)}" />`,
      `<property name="lease_id" value="${xmlAttribute(probation.lease_id as string)}" />`,
      ...runnerPropertyRows,
      '</properties>',
      '<testcase classname="lot7.object_graph" name="authenticated canary" />',
      '</testsuite>',
    ].join('');
    const runnerArtifactRef = `sha256:${createHash('sha256').update(junitXml).digest('hex')}`;
    const sourceManifest = {
      schema_version: 1,
      kind: 'lot7_projection_behavior_source',
      subject,
      gate: {
        phase: 'probation',
        lease_id: probation.lease_id,
        revision: probation.revision,
        staged_at: probation.staged_at,
        expires_at: probation.expires_at,
      },
      runtime: {
        run_id: runtime.run.id,
        status: runtime.run.status,
        started_at: utcEvidenceTimestamp(runtime.run.started_at as string),
        execution_snapshot_at: utcEvidenceTimestamp(flowEvidence.execution_snapshot_at as string),
        completed_at: utcEvidenceTimestamp(runtime.run.completed_at as string),
        runtime_revision: flowEvidence.runtime_revision,
        flow_version_id: flowEvidence.flow_version_id,
        flow_snapshot_sha256: flowEvidence.flow_snapshot_sha256,
        primary_invocation_id: runtime.invocation.id,
        catalog_skill_id: runtime.catalogSkill.id,
        invocations: runtime.invocations.map((invocation) => ({
          id: invocation.id,
          status: invocation.status,
          resolution: invocation.execution_evidence?.resolution,
          execution_snapshot_sha256: invocation.execution_evidence?.execution_snapshot_sha256,
        })),
      },
      gate_off_workspace_id: gateOff!.workspace.id,
      runner_artifact_ref: runnerArtifactRef,
      build_info: {
        backend: {
          revision: backendBuild.revision,
          service: backendBuild.service,
          revision_verified: backendBuild.revision_verified,
        },
        frontend: {
          revision: frontendBuild.revision,
          service: frontendBuild.service,
          revision_verified: frontendBuild.revision_verified,
        },
      },
      projection_sha256: projectionHashes,
      rendered_fact_sources: renderedFactSources,
      invariant_chrome_sha256: fingerprint(invariantChrome),
      suite: 'frontend-ng/e2e/tests/12-lot7-object-graph-canary.spec.ts',
    };
    const evidence = {
      schema_version: 2,
      result: 'passed',
      subject,
      validated_by: username,
      validated_at: validatedAt.toISOString(),
      revision: expectedSha,
      environment,
      source_manifest: sourceManifest,
      source_ref: `sha256:${fingerprint(sourceManifest)}`,
      runner_artifact: {
        format: 'junit_xml',
        artifact_ref: runnerArtifactRef,
        content_base64: Buffer.from(junitXml, 'utf8').toString('base64'),
      },
    };
    const outputPath = evidencePath || testInfo.outputPath(`lot7-${projection}-evidence.json`);
    writeJson(outputPath, evidence);
    await testInfo.attach(`lot7-${projection}-evidence`, {
      path: outputPath,
      contentType: 'application/json',
    });
  });
});
