import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { expect, test, type Page, type TestInfo } from '@playwright/test';

/**
 * Lot 6 — authenticated System 360 behavioural canary.
 *
 * The System is discovered exclusively from the persisted
 * `settings.experience.system_360_canary = "v1"` marker.  No System name,
 * slug, Capability slug or object id is embedded in this test.
 *
 * Traces, automatic screenshots and video stay disabled because the login
 * transaction contains live credentials. Interactive runs may attach one
 * post-login screenshot; safe-deployment runs retain no media.
 */

const enabled = process.env['E2E_LOT6_CANARY'] === '1';
const username = process.env['E2E_USERNAME'];
const password = process.env['E2E_PASSWORD'];
const expectedSha = process.env['E2E_EXPECTED_SHA'];
const expectedShowcaseWorkspaceId = process.env['E2E_SHOWCASE_WORKSPACE_ID'] ?? '';
const expectedShowcaseWorkspaceSlug = process.env['E2E_SHOWCASE_WORKSPACE_SLUG'] ?? '';
const runnerAttestationPath = process.env['E2E_LOT6_RUNNER_ATTESTATION'];
const behaviorAttestationPath = process.env['E2E_LOT6_BEHAVIOR_ATTESTATION'];
const protectedRunner = process.env['E2E_PROTECTED_RUNNER_CANARIES'] === '1';
const playwrightRuntimeAttestationPath = process.env['E2E_PLAYWRIGHT_RUNTIME_ATTESTATION'];
const claimId = 'LOT6-SYSTEM360-PERSPECTIVES';
const lenses = ['build', 'operate', 'steer', 'govern'] as const;
const facets = ['overview', 'runs', 'design', 'context'] as const;
const factStates = [
  'available',
  'not_measured',
  'not_configured',
  'restricted',
  'unavailable',
] as const;

if (enabled) {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
    expectedShowcaseWorkspaceId,
  )) {
    throw new Error('E2E_SHOWCASE_WORKSPACE_ID must be a canonical UUID');
  }
  if (!/^[a-z0-9][a-z0-9._-]{0,99}$/.test(expectedShowcaseWorkspaceSlug)) {
    throw new Error('E2E_SHOWCASE_WORKSPACE_SLUG must be a canonical workspace slug');
  }
}

type Lens = (typeof lenses)[number];
type Facet = (typeof facets)[number];
type FactState = (typeof factStates)[number];

test.use({ trace: 'off', video: 'off', screenshot: 'off' });

interface WorkspaceSummary {
  id: string;
  slug: string;
  name: string;
  role?: string;
  role_template?: string | null;
  settings?: Record<string, unknown>;
}

interface CapabilityRow {
  id: string;
  name: string;
}

interface SystemRow {
  id: string;
  name: string;
  capability_id?: string | null;
  settings?: Record<string, unknown>;
}

interface PerspectiveFact {
  key: string;
  label: string;
  state: FactState;
  value: unknown | null;
  unit?: string | null;
  source?: string | null;
  as_of?: string | null;
  sample_count?: number | null;
}

interface PerspectiveBlock {
  id: string;
  title: string;
  facts: PerspectiveFact[];
}

interface SystemPerspective {
  schema_version: 1;
  snapshot_id: string;
  generated_at: string;
  window: string;
  identity: {
    workspace_id: string;
    capability_id: string | null;
    system_id: string;
    version_id: string | null;
    name: string;
  };
  header: Record<string, PerspectiveFact>;
  lens: Lens;
  facets: Record<Facet, { blocks: PerspectiveBlock[] }>;
}

interface BuildInfo {
  revision: string;
  service: 'backend' | 'frontend';
  revision_verified: boolean;
  version?: string;
}

interface ApiResult<T> {
  ok: boolean;
  status: number;
  body: T;
}

interface MissingFact {
  lens: Lens;
  facet: Facet;
  block: PerspectiveBlock;
  fact: PerspectiveFact & { state: 'not_measured' | 'not_configured' };
}

interface LocatedFact {
  lens: Lens;
  facet: Facet;
  block: PerspectiveBlock;
  fact: PerspectiveFact;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function marker(row: SystemRow): unknown {
  const experience = asRecord(asRecord(row.settings)?.['experience']);
  return experience?.['system_360_canary'];
}

function unwrap<T>(body: T[] | Record<string, T[]>, key: string): T[] {
  if (Array.isArray(body)) return body;
  return Array.isArray(body?.[key]) ? body[key] : [];
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

function normalizeText(value: string): string {
  return value.replace(/\s+/g, ' ').trim();
}

function formatPrimitive(value: unknown): string | null {
  if (typeof value === 'string') return value;
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return null;
}

function features(settings: Record<string, unknown> | undefined): Record<string, unknown> {
  return asRecord(settings?.['features']) ?? {};
}

function ciIdentity(): Record<string, string> {
  const values: Record<string, string> = {
    server_url: process.env['CI_SERVER_URL'] ?? '',
    project_id: process.env['CI_PROJECT_ID'] ?? '',
    pipeline_id: process.env['CI_PIPELINE_ID'] ?? '',
    job_id: process.env['CI_JOB_ID'] ?? '',
    job_url: process.env['CI_JOB_URL'] ?? '',
    commit_sha: process.env['CI_COMMIT_SHA'] ?? '',
    ref: process.env['CI_COMMIT_REF_NAME'] ?? '',
    ref_protected: process.env['CI_COMMIT_REF_PROTECTED'] ?? '',
  };
  if (process.env['CI'] && !protectedRunner) {
    for (const [key, value] of Object.entries(values)) {
      expect(value, `GitLab metadata ${key} is required for formal evidence`).toBeTruthy();
    }
    expect(values['ref_protected']).toBe('true');
  } else if (protectedRunner) {
    expect(values['commit_sha'], 'protected runner commit binding is required').toBe(expectedSha);
  }
  return values;
}

function writeJson(path: string | undefined, value: unknown): void {
  if (!path) {
    expect(process.env['CI'], 'formal CI runs must configure attestation output paths').not.toBeTruthy();
    return;
  }
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
}

function playwrightRuntime(): Record<string, unknown> {
  expect(playwrightRuntimeAttestationPath, 'SHA-bound Playwright runtime proof is required').toBeTruthy();
  const payload = JSON.parse(readFileSync(playwrightRuntimeAttestationPath as string, 'utf8')) as Record<string, unknown>;
  expect(payload['schema_version']).toBe(1);
  expect(payload['kind']).toBe('agentium_playwright_runtime');
  expect(payload['result']).toBe('passed');
  expect(payload['candidate_sha']).toBe(expectedSha);
  expect(payload['paths_serialized']).toBe(false);
  for (const key of ['package_lock_sha256', 'installed_lock_sha256', 'playwright_cli_sha256', 'chromium_executable_sha256']) {
    expect(String(payload[key] ?? '')).toMatch(/^[0-9a-f]{64}$/);
  }
  return payload;
}

async function login(page: Page): Promise<WorkspaceSummary[]> {
  expect(username, 'E2E_USERNAME is required for the Lot 6 canary').toBeTruthy();
  expect(password, 'E2E_PASSWORD is required for the Lot 6 canary').toBeTruthy();
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
  const memberships = (Array.isArray(result.workspaces) ? result.workspaces : []) as WorkspaceSummary[];
  expect(memberships.length, 'the canary principal needs at least one authorized workspace').toBeGreaterThan(0);
  return memberships;
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
  slug: string,
  path: string,
): Promise<ApiResult<T>> {
  return page.evaluate(
    async ({ workspace, apiPath }) => {
      const response = await fetch(`/api/v1${apiPath}`, {
        headers: {
          Authorization: localStorage.getItem('agentium_token') || '',
          'X-Workspace-Slug': workspace,
        },
      });
      const text = await response.text();
      let body: unknown = null;
      if (text) {
        try { body = JSON.parse(text); } catch { body = text; }
      }
      return { ok: response.ok, status: response.status, body };
    },
    { workspace: slug, apiPath: path },
  ) as Promise<ApiResult<T>>;
}

async function buildInfo(page: Page, path: string): Promise<BuildInfo> {
  const response = await page.request.get(`${path}?canary=${Date.now()}`, {
    headers: { Accept: 'application/json', 'Cache-Control': 'no-cache' },
  });
  expect(response.ok(), `${path} must be readable`).toBe(true);
  return response.json() as Promise<BuildInfo>;
}

async function selectFacet(page: Page, facet: Facet): Promise<void> {
  const label = facet[0].toUpperCase() + facet.slice(1);
  await page.getByRole('tab', { name: label, exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get('facet')).toBe(facet);
}

async function selectLens(page: Page, lens: Lens, systemId: string, facet: Facet): Promise<void> {
  const label = lens[0].toUpperCase() + lens.slice(1);
  const link = page.locator('app-side-rail a.ck-rail-item').filter({ hasText: new RegExp(label, 'i') });
  await expect(link).toHaveCount(1);
  await link.click();
  await expect.poll(() => {
    const url = new URL(page.url());
    return `${url.pathname}|${url.searchParams.get('lens')}|${url.searchParams.get('facet')}`;
  }).toBe(`/systems/${systemId}|${lens}|${facet}`);
  await expect(
    page.locator(`#ck-tabpanel-${facet} app-system-perspective section[data-system-id="${systemId}"][data-perspective-lens="${lens}"]`),
  ).toBeVisible();
}

async function chromeSignature(page: Page): Promise<Record<string, unknown>> {
  const tabs = page.getByRole('tablist', { name: 'System facets' }).getByRole('tab');
  return {
    header: normalizeText(await page.locator('app-system-view ck-object-header header').innerText()),
    breadcrumb: normalizeText(await page.locator('app-semantic-zoom-breadcrumb').innerText()),
    tabs: (await tabs.allTextContents()).map(normalizeText),
  };
}

function allFacts(payloads: Record<Lens, SystemPerspective>): Array<{
  lens: Lens;
  facet: Facet;
  block: PerspectiveBlock;
  fact: PerspectiveFact;
}> {
  const rows: Array<{ lens: Lens; facet: Facet; block: PerspectiveBlock; fact: PerspectiveFact }> = [];
  for (const lens of lenses) {
    for (const facet of facets) {
      for (const block of payloads[lens].facets[facet].blocks) {
        for (const fact of block.facts) rows.push({ lens, facet, block, fact });
      }
    }
  }
  return rows;
}

test.describe.serial('Lot 6 — authenticated System 360 canary', () => {
  test.skip(!enabled, 'Set E2E_LOT6_CANARY=1 to exercise the deployed Lot 6 canary');

  test.afterEach(async ({ page }) => logout(page));

  test('four honest projections preserve one System and deployed revision', async ({ page }, testInfo: TestInfo) => {
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
    const discoveries: Array<{ workspace: WorkspaceSummary; system: SystemRow }> = [];
    for (const workspace of memberships) {
      const result = await api<SystemRow[] | { systems: SystemRow[] }>(
        page,
        workspace.slug,
        '/systems?include_retired=true&limit=2147483647',
      );
      expect(result.ok, `Systems must be readable for authorized workspace ${workspace.id}`).toBe(true);
      for (const system of unwrap(result.body, 'systems')) {
        if (marker(system) === 'v1') discoveries.push({ workspace, system });
      }
    }
    expect(
      discoveries,
      'exactly one authorized workspace and System pair must carry the v1 canary marker',
    ).toHaveLength(1);
    const { workspace: primary, system } = discoveries[0];
    expect(primary.id).toBe(expectedShowcaseWorkspaceId);
    expect(primary.slug).toBe(expectedShowcaseWorkspaceSlug);
    const alternate = memberships.find((workspace) => workspace.id !== primary.id);
    expect(alternate, 'the canary principal needs a second workspace to prove atomic purge').toBeTruthy();
    await page.evaluate((slug) => localStorage.setItem('agentium_workspace_slug', slug), primary.slug);

    const workspaceResult = await api<WorkspaceSummary>(
      page,
      primary.slug,
      `/auth/workspaces/${encodeURIComponent(primary.slug)}`,
    );
    expect(workspaceResult.ok).toBe(true);
    expect(features(workspaceResult.body.settings)['cockpit_router_axes_v4']).toBe(true);
    expect(features(workspaceResult.body.settings)['system_360_projection_v1']).toBe(true);
    expect(system.capability_id, 'the marked System must belong to one Capability').toBeTruthy();

    const capabilitiesResult = await api<CapabilityRow[] | { capabilities: CapabilityRow[] }>(
      page,
      primary.slug,
      '/capabilities',
    );
    expect(capabilitiesResult.ok).toBe(true);
    const capability = unwrap(capabilitiesResult.body, 'capabilities')
      .find((row) => row.id === system.capability_id);
    expect(capability, 'the marked System Capability must resolve in the same workspace').toBeTruthy();

    const payloads = {} as Record<Lens, SystemPerspective>;
    for (const lens of lenses) {
      const result = await api<SystemPerspective>(
        page,
        primary.slug,
        `/systems/${encodeURIComponent(system.id)}/perspective?lens=${lens}&window=30d`,
      );
      expect(result.ok, `${lens} perspective failed (${result.status})`).toBe(true);
      payloads[lens] = result.body;
      expect(result.body.schema_version).toBe(1);
      expect(result.body.lens).toBe(lens);
      expect(result.body.window).toBe('30d');
      expect(result.body.identity.system_id).toBe(system.id);
      expect(result.body.identity.capability_id).toBe(system.capability_id);
      expect(Object.keys(result.body.facets).sort()).toEqual([...facets].sort());
      for (const facet of facets) {
        expect(result.body.facets[facet].blocks.length, `${lens}/${facet} needs real blocks`).toBeGreaterThan(0);
      }
    }

    const reference = payloads.build;
    for (const lens of lenses) {
      expect(payloads[lens].identity).toEqual(reference.identity);
      expect(payloads[lens].header).toEqual(reference.header);
      expect(payloads[lens].snapshot_id).toBe(reference.snapshot_id);
    }
    const projectionFingerprints = Object.fromEntries(
      lenses.map((lens) => [lens, fingerprint(payloads[lens].facets)]),
    ) as Record<Lens, string>;
    expect(new Set(Object.values(projectionFingerprints)).size).toBe(4);
    const overviewBlockSignatures = lenses.map((lens) =>
      payloads[lens].facets.overview.blocks.map((block) => block.id).sort().join('|'),
    );
    expect(new Set(overviewBlockSignatures).size).toBe(4);

    const facts = allFacts(payloads);
    for (const { fact } of facts) {
      expect(factStates).toContain(fact.state);
      if (fact.state !== 'available') expect(fact.value).toBeNull();
    }
    const missing = facts.find(
      (row): row is MissingFact => row.fact.state === 'not_measured' || row.fact.state === 'not_configured',
    );
    expect(missing, 'at least one honest missing-data state must be exposed').toBeTruthy();
    const restricted = facts.find((row) => row.fact.state === 'restricted');
    expect(restricted, 'at least one genuinely restricted field must be explicit').toBeTruthy();
    const uiFacts = Object.fromEntries(lenses.map((lens) => {
      const located = facts.find(
        (row) => row.lens === lens
          && row.fact.state === 'available'
          && formatPrimitive(row.fact.value) !== null,
      );
      expect(located, `${lens} needs one primitive API fact comparable with the UI`).toBeTruthy();
      return [lens, located as LocatedFact];
    })) as Record<Lens, LocatedFact>;

    const canonicalUrl = `/systems/${encodeURIComponent(system.id)}?lens=build&capabilityId=${encodeURIComponent(system.capability_id as string)}&facet=overview`;
    await page.goto(canonicalUrl);
    await expect(page.locator('app-system-view')).toBeVisible();
    await expect(page.locator('#ck-tabpanel-overview app-system-perspective [data-testid^="system360-build-"]').first()).toBeVisible();
    await expect(page.locator('app-semantic-zoom-breadcrumb')).toContainText(capability!.name);
    await expect(page.locator('app-semantic-zoom-breadcrumb')).toContainText(system.name);
    const invariantChrome = await chromeSignature(page);
    expect(invariantChrome['tabs']).toEqual(['Overview', 'Runs', 'Design', 'Context']);
    const canonicalPath = new URL(page.url()).pathname;

    await page.evaluate(() => {
      const state = window as typeof window & { __system360Invariant?: unknown };
      state.__system360Invariant = {
        header: document.querySelector('app-system-view ck-object-header header'),
        breadcrumb: document.querySelector('app-semantic-zoom-breadcrumb'),
        tabs: document.querySelector('app-system-view ck-tabs'),
      };
    });

    for (const lens of lenses) {
      if (lens !== 'build') await selectLens(page, lens, system.id, 'overview');
      const url = new URL(page.url());
      expect(url.pathname).toBe(canonicalPath);
      expect(url.searchParams.get('lens')).toBe(lens);
      expect(url.searchParams.get('facet')).toBe('overview');
      expect(url.searchParams.get('capabilityId')).toBe(system.capability_id);
      expect(await chromeSignature(page)).toEqual(invariantChrome);
      const expectedBlocks = payloads[lens].facets.overview.blocks.map((block) => block.id).sort();
      const renderedBlocks = await page
        .locator('#ck-tabpanel-overview app-system-perspective article[data-block-id]')
        .evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-block-id')).filter(Boolean).sort());
      expect(renderedBlocks).toEqual(expectedBlocks);
      expect(await page.evaluate(() => {
        const state = (window as typeof window & { __system360Invariant?: {
          header: Element | null;
          breadcrumb: Element | null;
          tabs: Element | null;
        } }).__system360Invariant;
        return Boolean(
          state
          && state.header === document.querySelector('app-system-view ck-object-header header')
          && state.breadcrumb === document.querySelector('app-semantic-zoom-breadcrumb')
          && state.tabs === document.querySelector('app-system-view ck-tabs'),
        );
      })).toBe(true);
    }

    await selectFacet(page, 'design');
    await selectLens(page, 'build', system.id, 'design');
    await page.reload();
    await expect(page.locator('#ck-tabpanel-design app-system-perspective section[data-perspective-lens="build"]')).toBeVisible();
    expect(new URL(page.url()).searchParams.get('facet')).toBe('design');
    await page.goBack();
    await expect.poll(() => new URL(page.url()).searchParams.get('lens')).toBe('govern');
    expect(new URL(page.url()).searchParams.get('facet')).toBe('design');
    await page.goForward();
    await expect.poll(() => new URL(page.url()).searchParams.get('lens')).toBe('build');
    expect(new URL(page.url()).searchParams.get('facet')).toBe('design');

    await page.goto(
      `/systems/${encodeURIComponent(system.id)}?lens=operate&capabilityId=${encodeURIComponent(system.capability_id as string)}&facet=context`,
    );
    await expect(page.locator('#ck-tabpanel-context app-system-perspective section[data-perspective-lens="operate"]')).toBeVisible();
    await page.reload();
    await expect(page.locator('#ck-tabpanel-context app-system-perspective section[data-perspective-lens="operate"]')).toBeVisible();

    let currentFacet: Facet = 'context';
    for (const lens of lenses) {
      const located = uiFacts[lens];
      await selectLens(page, lens, system.id, currentFacet);
      if (located.facet !== currentFacet) {
        await selectFacet(page, located.facet);
        currentFacet = located.facet;
      }
      const row = page.locator(
        `#ck-tabpanel-${located.facet} article[data-block-id="${located.block.id}"] [data-fact-key="${located.fact.key}"]`,
      );
      await expect(row.locator('.fact-value')).toHaveText(formatPrimitive(located.fact.value) as string);
    }

    await selectLens(page, missing!.lens, system.id, currentFacet);
    if (missing!.facet !== currentFacet) {
      await selectFacet(page, missing!.facet);
      currentFacet = missing!.facet;
    }
    const missingRow = page.locator(
      `#ck-tabpanel-${missing!.facet} article[data-block-id="${missing!.block.id}"] [data-fact-key="${missing!.fact.key}"]`,
    );
    await expect(missingRow.locator(`[data-state="${missing!.fact.state}"]`)).toBeVisible();

    await selectLens(page, restricted!.lens, system.id, currentFacet);
    if (restricted!.facet !== currentFacet) {
      await selectFacet(page, restricted!.facet);
      currentFacet = restricted!.facet;
    }
    const restrictedRow = page.locator(
      `#ck-tabpanel-${restricted!.facet} article[data-block-id="${restricted!.block.id}"] [data-fact-key="${restricted!.fact.key}"]`,
    );
    await expect(restrictedRow.locator('[data-state="restricted"]')).toBeVisible();

    if (process.env['E2E_SAFE_CONTENT_FREE'] !== '1') {
      const screenshot = testInfo.outputPath('lot6-system360-canary.png');
      await page.locator('app-system-view').screenshot({ path: screenshot, animations: 'disabled' });
      await testInfo.attach('lot6-system360-canary', { path: screenshot, contentType: 'image/png' });
    }

    const alternateRequest = page.waitForRequest((request) => {
      const url = new URL(request.url());
      return url.pathname.startsWith('/api/v1/')
        && request.headers()['x-workspace-slug'] === alternate!.slug;
    });
    await page.getByTestId('workspace-switcher-toggle').click();
    await page.locator('app-title-bar button').filter({ hasText: alternate!.name }).first().click();
    await alternateRequest;
    await expect.poll(() => page.evaluate(() => localStorage.getItem('agentium_workspace_slug'))).toBe(alternate!.slug);
    await expect.poll(() => new URL(page.url()).pathname).not.toContain(`/systems/${system.id}`);
    await expect(page.locator(`app-system-perspective [data-system-id="${system.id}"]`)).toHaveCount(0);
    expect(page.url()).not.toContain(system.id);

    const checks = {
      build_revision: true,
      unique_marker_discovery: true,
      four_distinct_projections: true,
      invariant_identity_header_breadcrumb_tabs: true,
      ui_value_matches_api_per_lens: true,
      deep_link_reload_history_and_facet: true,
      workspace_switch_purges_object: true,
      explicit_missing_state: true,
      explicit_restricted_state: true,
    };
    const ci = ciIdentity();
    const common = {
      schema_version: 1,
      commit_sha: expectedSha,
      outcome: 'passed',
      claims: { [claimId]: 'passed' },
      ci,
      checks,
      build_info: { backend: backendBuild, frontend: frontendBuild },
      playwright_runtime: playwrightRuntime(),
    };
    writeJson(runnerAttestationPath, {
      ...common,
      kind: 'runner',
      runner: 'playwright',
      suite: 'frontend-ng/e2e/tests/11-system360-canary.spec.ts',
    });
    writeJson(behaviorAttestationPath, {
      ...common,
      kind: 'behavior',
      workspace: { id: primary.id },
      discovered: {
        system_id: system.id,
        capability_id: system.capability_id,
        snapshot_id: reference.snapshot_id,
      },
      projection_sha256: projectionFingerprints,
      invariant_chrome_sha256: fingerprint(invariantChrome),
      missing_state: missing!.fact.state,
      restricted_state: restricted!.fact.state,
    });
  });
});
