import { expect, test, type Page, type TestInfo } from '@playwright/test';

import {
  projectSeries,
  type HypervisorSeriesResponse,
  type SeriesFact,
} from '../../src/app/features/hypervisor/v2/hypervisor-v2-series';

/**
 * Hypervisor V2 — authenticated canary for the instrumented ledger.
 *
 * Temporarily enables `settings.features.hypervisor_v2` the same way Lot 3
 * flips a workspace flag, then restores the original settings. Opt-in:
 *
 *   E2E_HYPERVISOR_V2_CANARY=1 E2E_USERNAME=... E2E_PASSWORD=...
 *
 * Defaults to the Showcase slug (`E2E_SHOWCASE_WORKSPACE_SLUG` or
 * `E2E_LOT3_SHOWCASE_SLUG`). Traces stay off because login uses a live
 * principal.
 */

const canaryEnabled = process.env['E2E_HYPERVISOR_V2_CANARY'] === '1';
const username = process.env['E2E_USERNAME'];
const password = process.env['E2E_PASSWORD'];
const showcaseSlug =
  process.env['E2E_SHOWCASE_WORKSPACE_SLUG']
  ?? process.env['E2E_LOT3_SHOWCASE_SLUG']
  ?? 'agentium-showcase';

const FACETS = ['synthese', 'registre', 'couts', 'bases', 'decisions', 'journal'] as const;
/** `<ck-tabs>` paints at most five tabs; the rest live under the More menu. */
const VISIBLE_FACETS = 5;
const ADMIN_ROLES = new Set([
  'owner',
  'admin',
  'workspace_owner',
  'workspace_admin',
]);
const MISSING_FACT = new Set(['not_measured', 'not_configured']);
const ZERO_FACT = /^0([.,]0+)?$/;
const FACT_STATE_LABEL =
  /NON MESURÉ|NOT MEASURED|NON CONFIGURÉ|NOT CONFIGURED|INDISPONIBLE|UNAVAILABLE|ACCÈS RESTREINT|RESTRICTED/i;

test.use({ trace: 'off', video: 'off', screenshot: 'off' });

interface WorkspaceSummary {
  id: string;
  slug: string;
  name: string;
  role?: string;
  role_template?: string | null;
  settings?: Record<string, unknown>;
}

interface ValueBasis {
  status?: string | null;
  currency?: string | null;
  hours_per_unit?: number | null;
  value_per_unit?: number | null;
}

interface ValueBasisItem {
  capability_id: string;
  name: string;
  value_basis?: ValueBasis | null;
}

interface ApiResult<T> {
  ok: boolean;
  status: number;
  body: T;
}

async function login(page: Page, workspaceSlug: string): Promise<WorkspaceSummary[]> {
  expect(username, 'E2E_USERNAME is required for the Hypervisor V2 canary').toBeTruthy();
  expect(password, 'E2E_PASSWORD is required for the Hypervisor V2 canary').toBeTruthy();
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

function features(settings: Record<string, unknown> | undefined): Record<string, unknown> {
  const value = settings?.['features'];
  return value && typeof value === 'object' && !Array.isArray(value)
    ? { ...(value as Record<string, unknown>) }
    : {};
}

function isAdmin(workspace: WorkspaceSummary): boolean {
  return ADMIN_ROLES.has(workspace.role_template || workspace.role || '');
}

function isDeclaredBasis(item: ValueBasisItem): boolean {
  return item.value_basis?.status === 'declared' || item.value_basis?.status === 'measured';
}

function isUnconfiguredBasis(item: ValueBasisItem): boolean {
  return !item.value_basis || item.value_basis.status === 'none';
}

async function setHypervisorV2(
  page: Page,
  slug: string,
  settings: Record<string, unknown>,
  enabled: boolean,
): Promise<void> {
  const result = await api<WorkspaceSummary>(page, slug, `/auth/workspaces/${encodeURIComponent(slug)}`, {
    method: 'PATCH',
    body: {
      settings: {
        ...settings,
        features: {
          ...features(settings),
          hypervisor_v2: enabled,
        },
      },
    },
  });
  expect(result.ok, `failed to set hypervisor_v2=${enabled} (${result.status})`).toBe(true);
}

async function openHypervisor(page: Page, slug: string): Promise<void> {
  await page.evaluate((value) => localStorage.setItem('agentium_workspace_slug', value), slug);
  await page.goto('/hypervisor');
  await page.reload();
}

function assertMissingFact(text: string, fact: SeriesFact, label: string): void {
  if (!MISSING_FACT.has(fact.state)) return;
  const trimmed = text.replace(/\s+/g, ' ').trim();
  expect(trimmed, `${label} (${fact.state}) must not render as 0`).not.toMatch(ZERO_FACT);
  expect(trimmed, `${label} (${fact.state}) must show its state`).toMatch(FACT_STATE_LABEL);
}

async function assertHonesty(
  page: Page,
  series: HypervisorSeriesResponse,
): Promise<void> {
  const root = page.locator('app-hypervisor-v2');
  const copy = await root.innerText();
  expect(copy, 'V2 must not render a $ currency symbol').not.toMatch(/\$/);
  expect(copy, 'V2 must not render the word ROI').not.toMatch(/ROI/i);

  const view = projectSeries(series, 'hours');
  assertMissingFact(
    (await page.locator('[data-testid="hypervisor-v2-hero"] .hv2-monument').innerText()).trim(),
    view.monument,
    'hero monument',
  );

  const hero = page.locator('[data-testid="hypervisor-v2-hero"]');
  assertMissingFact((await hero.locator('[data-fact="cost"]').innerText()).trim(), view.costTotal, 'hero cost');
  assertMissingFact((await hero.locator('[data-fact="value"]').innerText()).trim(), view.valueTotal, 'hero value');
  assertMissingFact((await hero.locator('[data-fact="ratio"]').innerText()).trim(), view.ratio, 'hero ratio');

  const register = page.getByTestId('hypervisor-v2-register');
  await expect(register, 'synthese register testid must be unique').toHaveCount(1);
  const headers = await register.locator('thead th').allTextContents();
  const costIdx = headers.findIndex((header) => /co[uû]t|cost/i.test(header));
  const valueIdx = headers.findIndex((header) => /^valeur$|^value$/i.test(header.trim()));
  expect(costIdx, 'register cost column').toBeGreaterThan(-1);
  expect(valueIdx, 'register value column').toBeGreaterThan(-1);

  for (const row of view.register) {
    const tr = register.locator('tbody tr', { hasText: row.name }).first();
    await expect(tr).toBeVisible();
    assertMissingFact((await tr.locator('td').nth(costIdx).innerText()).trim(), row.cost, `${row.name} cost`);
    assertMissingFact(
      (await tr.locator('td').nth(valueIdx).innerText()).trim(),
      row.valueDeclared,
      `${row.name} value`,
    );
  }
}

test.describe.serial('Hypervisor V2 — instrumented ledger canary', () => {
  test.skip(!canaryEnabled, 'Set E2E_HYPERVISOR_V2_CANARY=1 to exercise the Hypervisor V2 canary');
  test.setTimeout(3 * 60 * 1_000);

  test.afterEach(async ({ page }) => logout(page));

  test('flag off keeps V1; flag on serves the tonal ledger, facets, honesty', async ({ page }, testInfo: TestInfo) => {
    const memberships = await login(page, showcaseSlug);
    const membership = memberships.find((workspace) => workspace.slug === showcaseSlug);
    expect(membership, `the canary principal must belong to ${showcaseSlug}`).toBeTruthy();
    expect(
      isAdmin(membership as WorkspaceSummary),
      'the Hypervisor V2 canary requires workspace admin rights for reversible flag setup',
    ).toBe(true);

    const original = await api<WorkspaceSummary>(
      page,
      showcaseSlug,
      `/auth/workspaces/${encodeURIComponent(showcaseSlug)}`,
    );
    expect(original.ok).toBe(true);
    const originalSettings = { ...(original.body.settings ?? {}) };

    const basesResult = await api<{ items?: ValueBasisItem[] } | ValueBasisItem[]>(
      page,
      showcaseSlug,
      '/hypervisor/value-bases',
    );
    expect(basesResult.ok, `GET /hypervisor/value-bases failed (${basesResult.status})`).toBe(true);
    const bases = Array.isArray(basesResult.body) ? basesResult.body : basesResult.body.items ?? [];
    expect(bases.some(isDeclaredBasis), 'Showcase must keep at least one declared value basis').toBe(true);
    expect(bases.some(isUnconfiguredBasis), 'Showcase must keep at least one not_configured value basis').toBe(true);

    const seriesResult = await api<HypervisorSeriesResponse>(
      page,
      showcaseSlug,
      '/hypervisor/series?window=90d',
    );
    expect(seriesResult.ok, `GET /hypervisor/series failed (${seriesResult.status})`).toBe(true);
    expect(seriesResult.body.systems.length, 'Showcase series must list Systems').toBeGreaterThan(0);
    const projected = projectSeries(seriesResult.body, 'hours');
    const outside = projected.outside.find((row) => row.capabilityId);
    expect(outside, 'Showcase must expose a hors-dénominateur System with a Capability').toBeTruthy();

    try {
      await setHypervisorV2(page, showcaseSlug, originalSettings, false);
      await openHypervisor(page, showcaseSlug);
      await expect(page.locator('app-hypervisor')).toBeVisible();
      await expect(page.locator('app-hypervisor-v2')).toHaveCount(0);
      await expect(page.getByTestId('hypervisor-v2-hero')).toHaveCount(0);

      await setHypervisorV2(page, showcaseSlug, originalSettings, true);
      await openHypervisor(page, showcaseSlug);
      await expect(page.locator('app-hypervisor-v2')).toBeVisible();
      await expect(page.locator('app-hypervisor')).toHaveCount(0);
      await expect(page.getByTestId('hypervisor-v2-hero')).toBeVisible();

      const facets = page.getByTestId('hypervisor-v2-facets');
      await expect(facets).toBeVisible();
      for (const facet of FACETS.slice(0, VISIBLE_FACETS)) {
        await expect(page.locator(`#ck-tab-${facet}`)).toBeVisible();
      }
      const more = facets.getByRole('button', { name: /^(Plus|More)$/i });
      await expect(more, 'Journal lives under the ck-tabs More menu').toBeVisible();
      await more.click();
      await expect(page.getByRole('menuitem', { name: /Journal/i })).toBeVisible();
      await page.keyboard.press('Escape');

      await expect(page.getByTestId('hypervisor-v2-stratum-comprendre')).toBeVisible();
      await expect(page.getByTestId('hypervisor-v2-stratum-detailler')).toBeVisible();
      await expect(page.getByTestId('hypervisor-v2-stratum-decider')).toBeVisible();

      const register = page.getByTestId('hypervisor-v2-register');
      await expect(register, 'synthese register testid must be unique').toHaveCount(1);
      await expect(register).toBeVisible();
      for (const system of seriesResult.body.systems) {
        await expect(register).toContainText(system.name);
      }

      const hors = page.getByTestId('hypervisor-v2-hors-denominateur');
      await expect(hors).toBeVisible();
      await assertHonesty(page, seriesResult.body);

      await page.locator('#ck-tab-registre').click();
      await expect.poll(() => new URL(page.url()).searchParams.get('facet')).toBe('registre');
      await expect(page.locator('#ck-tab-registre')).toHaveAttribute('aria-selected', 'true');

      await page.locator('#ck-tab-synthese').click();
      await expect.poll(() => new URL(page.url()).searchParams.get('facet')).toBe('synthese');
      await expect(page.locator('#ck-tab-synthese')).toHaveAttribute('aria-selected', 'true');
      await expect(hors.getByRole('link').first()).toBeVisible();
      await hors.getByRole('link').first().click();

      const landed = new URL(page.url());
      const landedCapabilityId = landed.searchParams.get('capabilityId');
      expect(landed.searchParams.get('facet')).toBe('bases');
      expect(landedCapabilityId, 'hors-dénominateur must deep-link a capabilityId').toBeTruthy();
      expect(
        projected.outside.some((row) => row.capabilityId === landedCapabilityId),
        'deep-link capabilityId must belong to a hors-dénominateur System',
      ).toBe(true);

      const table = page.getByTestId('hypervisor-v2-value-bases');
      await expect(table).toBeVisible();
      await expect(table).toContainText(/Déclarée|Declared/);
      await expect(table).toContainText(/Aucune|None|NON CONFIGURÉ|NOT CONFIGURED/);
      const tableCopy = await table.innerText();
      expect(tableCopy, 'value-bases must not render a $ currency symbol').not.toMatch(/\$/);
      expect(tableCopy, 'value-bases must not render the word ROI').not.toMatch(/ROI/i);

      await page.locator('#ck-tab-synthese').click();
      await page.getByTestId('hypervisor-v2-view-operations').click();
      await expect(page.locator('[data-testid="hypervisor-v2-hero"] .hv2-monument-unit')).toContainText(/runs/i);
      await expect(page.getByTestId('hypervisor-v2-hero-signal')).toBeVisible();
      await expect(page.getByTestId('hypervisor-v2-stratum-decider')).toHaveCount(0);

      await page.getByTestId('hypervisor-v2-view-conformite').click();
      await expect(page.getByTestId('hypervisor-v2-unites')).toBeVisible();
      await expect(page.getByTestId('hypervisor-v2-couverture')).toBeVisible();

      const screenshot = testInfo.outputPath('hypervisor-v2-canary.png');
      await page.screenshot({ path: screenshot, animations: 'disabled' });
      await testInfo.attach('hypervisor-v2-canary', { path: screenshot, contentType: 'image/png' });
    } finally {
      const restored = await api<WorkspaceSummary>(
        page,
        showcaseSlug,
        `/auth/workspaces/${encodeURIComponent(showcaseSlug)}`,
        { method: 'PATCH', body: { settings: originalSettings } },
      );
      expect(restored.ok, `failed to restore workspace settings (${restored.status})`).toBe(true);
    }
  });
});
