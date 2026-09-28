import { expect, test, type Page, type Route } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';

/**
 * Hypervisor V2 — mocked visual proof against A5 (page) and A6 (hero band).
 *
 * No local backend. Opt-in:
 *
 *   E2E_HYPERVISOR_V2_VISUAL=1 E2E_BASE_URL=http://localhost:4200
 *   npx playwright test e2e/tests/21-hypervisor-v2-mocked-visual.spec.ts
 *
 * Serve the production bundle first: `node e2e/serve-dist.mjs`
 */

const visualEnabled = process.env['E2E_HYPERVISOR_V2_VISUAL'] === '1';
const RESULTS = path.join(__dirname, '..', 'results', 'hypervisor-v2');

const FROM = '2026-08-09';
const TO = '2026-09-07';
const PEAK_INDEX = 16;
/** gen_a6 daily totals, +1 on the first four weekdays so the stack is 1 284 h. */
const RHYTHM = [
  41, 45, 39, 46, 41, 12, 9, 50, 58, 61, 54, 47, 10, 8, 56, 63, 71, 60, 49, 11, 7, 59, 66, 68, 62, 52, 13, 9, 56, 61,
];

const HOURS = { capture: 584, helpdesk: 412, pr: 288 } as const;
const RUNS = { capture: 612, helpdesk: 1236, pr: 96, risk: 212, diagnostic: 148, veille: 38 } as const;
const COSTS = { capture: 1402, helpdesk: 1696, pr: 1144 } as const;
const VALUES = { capture: 23360, helpdesk: 16400, pr: 16164 } as const;
const OUTCOMES = { capture: 612, helpdesk: 1236, pr: 96, risk: 212, diagnostic: 9, veille: 38 } as const;

type FixtureKind = 'dense' | 'sparse';
type ThemeKind = 'dark' | 'light';
const FACETS = ['synthese', 'registre', 'decisions', 'bases'] as const;

function datesBetween(from: string, to: string): string[] {
  const dates: string[] = [];
  const cursor = new Date(`${from}T00:00:00Z`);
  const last = new Date(`${to}T00:00:00Z`);
  while (cursor.getTime() <= last.getTime()) {
    dates.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return dates;
}

function splitTotal(total: number, weights: readonly number[]): number[] {
  const mass = weights.reduce((sum, value) => sum + value, 0) || 1;
  const raw = weights.map((weight) => (weight / mass) * total);
  const out = raw.map((value) => Math.round(value));
  let drift = out.reduce((sum, value) => sum + value, 0) - total;
  const order = raw.map((_, index) => index).sort((a, b) => raw[b]! - raw[a]!);
  let step = 0;
  while (drift !== 0 && step < order.length * 8) {
    const index = order[step % order.length]!;
    if (drift > 0 && out[index]! > 0) {
      out[index]! -= 1;
      drift -= 1;
    } else if (drift < 0) {
      out[index]! += 1;
      drift += 1;
    }
    step += 1;
  }
  return out;
}

function allocate(total: number, weights: readonly number[], pin: { index: number; value: number }): number[] {
  const rest = Math.max(0, total - pin.value);
  const restWeights = weights.map((weight, index) => (index === pin.index ? 0 : weight));
  const out = splitTotal(rest, restWeights);
  out[pin.index] = pin.value;
  return out;
}

function fact(state: 'available' | 'not_measured' | 'not_configured', value: number | null, unit?: string) {
  return unit ? { state, value, unit } : { state, value };
}

function available(value: number, unit?: string) {
  return fact('available', value, unit);
}

function emptyBucket(date: string, unit: string) {
  return {
    date,
    runs: available(0),
    outcomes: available(0, unit),
    cost: fact('not_measured', null),
    hours: available(0),
    value_declared: available(0),
  };
}

function basis(
  status: 'measured' | 'declared' | 'none',
  unit: string,
  extras: { hours?: number; value?: number } = {},
) {
  return {
    unit,
    hours_per_unit: extras.hours ?? (status === 'none' ? null : 1),
    value_per_unit: extras.value ?? (status === 'none' ? null : 40),
    currency: status === 'none' ? null : 'EUR',
    declared_by: status === 'none' ? null : 'ada@example.com',
    declared_at: status === 'none' ? null : '2026-08-01T00:00:00Z',
    status,
    note: null,
  };
}

const DATES = datesBetween(FROM, TO);

function stackedHours() {
  return {
    capture: allocate(HOURS.capture, RHYTHM, { index: PEAK_INDEX, value: 32 }),
    helpdesk: allocate(HOURS.helpdesk, RHYTHM, { index: PEAK_INDEX, value: 23 }),
    pr: allocate(HOURS.pr, RHYTHM, { index: PEAK_INDEX, value: 16 }),
  };
}

function stackedMetric(total: number) {
  return splitTotal(total, RHYTHM);
}

function denseSystems() {
  const hours = stackedHours();
  const captureRuns = allocate(RUNS.capture, RHYTHM, { index: PEAK_INDEX, value: 48 });
  const helpdeskRuns = allocate(RUNS.helpdesk, RHYTHM, { index: PEAK_INDEX, value: 58 });
  const prRuns = allocate(RUNS.pr, RHYTHM, { index: PEAK_INDEX, value: 12 });
  const captureCost = stackedMetric(COSTS.capture);
  const helpdeskCost = stackedMetric(COSTS.helpdesk);
  const prCost = stackedMetric(COSTS.pr);
  const captureValue = stackedMetric(VALUES.capture);
  const helpdeskValue = stackedMetric(VALUES.helpdesk);
  const prValue = stackedMetric(VALUES.pr);
  const riskRuns = stackedMetric(RUNS.risk);
  const diagnosticRuns = stackedMetric(RUNS.diagnostic);
  const veilleRuns = stackedMetric(RUNS.veille);
  const diagnosticOut = Array.from({ length: DATES.length }, () => 0);
  diagnosticOut[2] = 4;
  diagnosticOut[10] = 3;
  diagnosticOut[20] = 2;

  const hourSystem = (
    id: string,
    name: string,
    cap: string,
    unit: string,
    status: 'measured' | 'declared',
    rate: number,
    h: number[],
    runs: number[],
    cost: number[],
    value: number[],
  ) => ({
    system_id: id,
    capability_id: cap,
    name,
    output_unit: unit,
    value_basis: basis(status, unit, { hours: 1, value: rate }),
    days_since_last_run: available(1),
    buckets: DATES.map((date, index) => ({
      date,
      runs: available(runs[index] ?? 0),
      outcomes: available(runs[index] ?? 0, unit),
      cost: (cost[index] ?? 0) > 0 ? available(cost[index] ?? 0) : fact('not_measured', null),
      hours: available(h[index] ?? 0),
      value_declared: available(value[index] ?? 0),
    })),
  });

  const outsideSystem = (
    id: string,
    name: string,
    cap: string,
    unit: string,
    runs: number[],
    outcomes: number[],
    daysSince: number,
  ) => ({
    system_id: id,
    capability_id: cap,
    name,
    output_unit: unit,
    value_basis: basis('none', unit),
    days_since_last_run: available(daysSince),
    buckets: DATES.map((date, index) => ({
      date,
      runs: available(runs[index] ?? 0),
      outcomes: available(outcomes[index] ?? 0, unit),
      cost: fact('not_measured', null),
      hours: fact('not_configured', null),
      value_declared: fact('not_configured', null),
    })),
  });

  return [
    hourSystem('sys-capture', 'Capture Invoices', 'cap-capture', 'facture', 'measured', 40, hours.capture, captureRuns, captureCost, captureValue),
    hourSystem('sys-helpdesk', 'Service Helpdesk', 'cap-helpdesk', 'ticket', 'declared', 40, hours.helpdesk, helpdeskRuns, helpdeskCost, helpdeskValue),
    hourSystem('sys-pr', 'PR-to-PO', 'cap-pr', 'commande', 'declared', 56, hours.pr, prRuns, prCost, prValue),
    outsideSystem('sys-risk', 'Contract Risk', 'cap-native', 'contrats', riskRuns, riskRuns, 3),
    outsideSystem('sys-diag', 'Diagnostic', 'cap-native', 'incidents', diagnosticRuns, diagnosticOut, 4),
    outsideSystem('sys-veille', 'Veille', 'cap-native', 'briefs', veilleRuns, veilleRuns, 14),
  ];
}

function sparseSystems() {
  const active = '2026-08-10';
  const inside = {
    system_id: 'sys-capture',
    capability_id: 'cap-capture',
    name: 'Capture Invoices',
    output_unit: 'facture',
    value_basis: basis('declared', 'facture', { hours: 1, value: 40 }),
    days_since_last_run: available(28),
    buckets: DATES.map((date) =>
      date === active
        ? {
            date,
            runs: available(3),
            outcomes: available(3, 'facture'),
            cost: available(48),
            hours: available(2.5),
            value_declared: available(100),
          }
        : emptyBucket(date, 'facture'),
    ),
  };
  const outsiders: Array<[string, string, string, string, number]> = [
    ['sys-helpdesk', 'Service Helpdesk', 'cap-helpdesk', 'tickets', 4],
    ['sys-pr', 'PR-to-PO', 'cap-pr', 'commandes', 2],
    ['sys-risk', 'Contract Risk', 'cap-native', 'contrats', 8],
    ['sys-diag', 'Diagnostic', 'cap-native', 'incidents', 1],
    ['sys-veille', 'Veille', 'cap-native', 'briefs', 3],
    ['sys-tender', 'Tender Response', 'cap-native', 'briefs', 0],
  ];
  return [
    inside,
    ...outsiders.map(([id, name, cap, unit, units]) => ({
      system_id: id,
      capability_id: cap,
      name,
      output_unit: unit,
      value_basis: basis('none', unit),
      days_since_last_run: available(id === 'sys-veille' ? 21 : 4),
      buckets: DATES.map((date, index) => ({
        date,
        runs: units > 0 && index === 3 ? available(units) : fact('not_measured', null),
        outcomes: units > 0 && index === 3 ? available(units, unit) : fact('not_measured', null),
        cost: fact('not_measured', null),
        hours: fact('not_configured', null),
        value_declared: fact('not_configured', null),
      })),
    })),
  ];
}

function seriesPayload(kind: FixtureKind) {
  return {
    window: '30d',
    from: `${FROM}T00:00:00Z`,
    to: `${TO}T00:00:00Z`,
    authorization_scope: {
      resource: 'run',
      action: 'read',
      aggregation: 'portfolio',
      counts_include_only_readable_runs: true,
    },
    systems: kind === 'dense' ? denseSystems() : sparseSystems(),
  };
}

const STRATA = {
  comprendre: ['monument', 'provenance', 'cadran', 'sankey', 'rivers', 'hors_denominateur'],
  detailler: ['registre'],
  decider: ['signal', 'decisions'],
};

function viewsPayload() {
  return {
    can_edit: true,
    views: [
      {
        id: 'direction',
        label: 'Direction',
        denominator: 'hours',
        period: '30d',
        strata: STRATA,
        register_columns: ['unit', 'spark', 'cost', 'basis', 'value'],
        sort: 'value',
      },
      {
        id: 'operations',
        label: 'Opérations',
        denominator: 'runs',
        period: '30d',
        strata: {
          comprendre: ['monument', 'cadran', 'rivers', 'signal'],
          detailler: ['registre'],
          decider: [],
        },
        register_columns: ['unit', 'spark'],
        sort: 'days_since_last_run',
      },
      {
        id: 'conformite',
        label: 'Conformité',
        denominator: 'runs',
        period: '30d',
        strata: {
          comprendre: ['unites', 'couverture', 'decisions'],
          detailler: ['registre'],
          decider: [],
        },
        register_columns: ['unit', 'basis'],
        sort: 'name',
      },
    ],
  };
}

function capabilities() {
  return [
    { id: 'cap-capture', slug: 'capture-invoices', name: 'Capture Invoices', output_unit: 'facture', workspace_scope: 'workspace' },
    { id: 'cap-helpdesk', slug: 'service-helpdesk', name: 'Service Helpdesk', output_unit: 'ticket', workspace_scope: 'workspace' },
    { id: 'cap-pr', slug: 'pr-to-po', name: 'PR-to-PO', output_unit: 'commande', workspace_scope: 'workspace' },
    { id: 'cap-native', slug: 'native-units', name: 'Unités natives', output_unit: 'unité', workspace_scope: 'workspace' },
  ];
}

function valueBases(kind: FixtureKind) {
  const items = [
    {
      capability_id: 'cap-capture',
      slug: 'capture-invoices',
      name: 'Capture Invoices',
      output_unit: 'facture',
      value_basis: basis(kind === 'dense' ? 'measured' : 'declared', 'facture', { hours: 1, value: 40 }),
      systems: [{ system_id: 'sys-capture', name: 'Capture Invoices' }],
    },
    {
      capability_id: 'cap-helpdesk',
      slug: 'service-helpdesk',
      name: 'Service Helpdesk',
      output_unit: 'ticket',
      value_basis: kind === 'dense' ? basis('declared', 'ticket', { hours: 1, value: 40 }) : basis('none', 'ticket'),
      systems: [{ system_id: 'sys-helpdesk', name: 'Service Helpdesk' }],
    },
    {
      capability_id: 'cap-pr',
      slug: 'pr-to-po',
      name: 'PR-to-PO',
      output_unit: 'commande',
      value_basis: kind === 'dense' ? basis('declared', 'commande', { hours: 1, value: 56 }) : basis('none', 'commande'),
      systems: [{ system_id: 'sys-pr', name: 'PR-to-PO' }],
    },
    {
      capability_id: 'cap-native',
      slug: 'native-units',
      name: 'Unités natives',
      output_unit: 'unité',
      value_basis: basis('none', 'unité'),
      systems: [
        { system_id: 'sys-risk', name: 'Contract Risk' },
        { system_id: 'sys-diag', name: 'Diagnostic' },
        { system_id: 'sys-veille', name: 'Veille' },
      ],
    },
  ];
  return { items };
}

function decisions(kind: FixtureKind) {
  if (kind !== 'dense') return { items: [], total: 0, limit: 20, offset: 0 };
  return {
    items: [
      {
        id: 'dec-1',
        scope: 'system',
        target_id: 'sys-capture',
        kind: 'renew',
        status: 'proposed',
        title: 'Reconduire Capture Invoices',
        created_at: '2026-09-04T10:00:00Z',
      },
      {
        id: 'dec-2',
        scope: 'system',
        target_id: 'sys-veille',
        kind: 'pause',
        status: 'proposed',
        title: 'Revoir Veille réglementaire',
        created_at: '2026-09-03T09:00:00Z',
      },
    ],
    total: 2,
    limit: 20,
    offset: 0,
  };
}

function recommendations(kind: FixtureKind) {
  if (kind !== 'dense') return { items: [] };
  return {
    items: [
      {
        id: 'rec-1',
        scope: 'system',
        target_id: 'sys-capture',
        title: 'Reconduire Capture Invoices',
        rationale: {},
        impact_estimate: {},
        created_at: '2026-09-04T09:00:00Z',
      },
      {
        id: 'rec-2',
        scope: 'system',
        target_id: 'sys-veille',
        title: 'Augmenter la cadence de Veille',
        rationale: {},
        impact_estimate: {},
        created_at: '2026-09-02T09:00:00Z',
      },
      {
        id: 'rec-3',
        scope: 'system',
        target_id: 'sys-veille',
        title: 'Augmenter la cadence de Veille',
        rationale: {},
        impact_estimate: {},
        created_at: '2026-09-01T09:00:00Z',
      },
    ],
  };
}

function balanceSheet(kind: FixtureKind) {
  return {
    period: 'rolling_30d',
    portfolio: { scope: 'portfolio', period: 'rolling_30d', total_cost: kind === 'dense' ? 4242 : 48 },
    capabilities: [],
    signals: kind === 'dense'
      ? [{ id: 'sig-veille', tone: 'warn', kind: 'stale', system_id: 'sys-veille', label: 'Veille silencieuse depuis 14 jours' }]
      : [],
  };
}

const WORKSPACE = {
  id: 'ws-showcase',
  name: 'Agentium Showcase',
  slug: 'agentium-showcase',
  role: 'admin',
  role_template: 'workspace_admin',
  member_count: 4,
  created_at: '2026-01-01T00:00:00Z',
  is_active: true,
  mode: 'portfolio',
  settings: {
    features: { hypervisor_v2: true },
  },
};

const USER = {
  id: 'user-hv2-visual',
  username: 'ada',
  email: 'ada@example.test',
  role: 'admin',
  is_active: true,
  mfa_enabled: false,
  first_name: 'Ada',
  last_name: 'Lovelace',
  workspaces: [{ id: WORKSPACE.id, name: WORKSPACE.name, slug: WORKSPACE.slug, role: WORKSPACE.role }],
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

async function installMocks(page: Page, kind: FixtureKind, theme: ThemeKind): Promise<void> {
  await page.addInitScript(
    ({ themeMode, slug }) => {
      localStorage.setItem('agentium_token', 'Bearer mocked-hv2-visual');
      localStorage.setItem('agentium_workspace_slug', slug);
      localStorage.setItem('agentium_theme', themeMode);
      localStorage.setItem('agentium_locale', 'fr');
    },
    { themeMode: theme, slug: WORKSPACE.slug },
  );

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const apiPath = url.pathname.replace(/^\/api\/v1/, '');
    const method = request.method();

    if (apiPath === '/auth/validate' && method === 'POST') {
      return json(route, { valid: true, user_id: USER.id, email: USER.email, role: USER.role });
    }
    if (apiPath === '/auth/workspaces') return json(route, [WORKSPACE]);
    if (apiPath === `/auth/workspaces/${WORKSPACE.slug}`) return json(route, WORKSPACE);
    if (apiPath === '/auth/me') return json(route, USER);
    if (apiPath === '/iam/matrix') {
      return json(route, {
        workspace: { id: WORKSPACE.id, slug: WORKSPACE.slug, name: WORKSPACE.name },
        subject_user_id: USER.id,
        role_template: 'workspace_admin',
        custom_labels: [],
        role_flags: {},
        enforcement: true,
        permissions: [],
      });
    }
    if (apiPath.startsWith('/hypervisor/series')) return json(route, seriesPayload(kind));
    if (apiPath === '/hypervisor/views') return json(route, viewsPayload());
    if (apiPath === '/hypervisor/value-bases') return json(route, valueBases(kind));
    if (apiPath.startsWith('/hypervisor/balance-sheet')) return json(route, balanceSheet(kind));
    if (apiPath === '/hypervisor/recommendations') return json(route, recommendations(kind));
    if (apiPath.startsWith('/hypervisor/decisions')) return json(route, decisions(kind));
    if (apiPath === '/capabilities') return json(route, capabilities());
    if (apiPath === '/systems') return json(route, []);
    if (apiPath === '/contexts') return json(route, { contexts: [] });
    // L13b live Impact blocks — neutral Mission Room payloads (no client labels).
    if (apiPath === '/mission-room/timeline') {
      return json(route, {
        agenda: [{
          id: 'evt-1',
          title: 'Revue portefeuille',
          time: '09:00',
          date: '2026-09-28',
          location: 'Salle A',
          status: 'confirmed',
          metadata: {
            agenda_items: [{
              id: 'pt-1',
              title: 'Priorité semaine',
              origin: 'human',
              options: [{ id: 'go', label: 'Valider', recommended: true }],
            }],
          },
        }],
        messages: [],
        summary: '',
      });
    }
    if (apiPath === '/mission-room/news') {
      return json(route, {
        signals: [{ id: 'sig-1', title: 'Signal press', source_category: 'verified', sentiment: 'neutral' }],
        executive_alerts: [{ id: 'al-1', title: 'Alerte exécutive', risk_level: 'high', zone: 'Nord' }],
        sources: [],
      });
    }
    if (apiPath === '/mission-room/map') {
      return json(route, {
        map: { country: '', view_box: '', projection: '', accuracy: '' },
        zones: [{ id: 'z-nord', name: 'Nord', level: 2, centroid: { x: 0, y: 0 }, polygon: '', signals: [], recommendations: [], sources: [] }],
        sources: [],
      });
    }
    if (apiPath === '/mission-room/monitor') {
      return json(route, {
        zones: [{ id: 'z-nord', name: 'Nord', level: 'high', signals: ['Surveillance'] }],
        visual_observations: [],
        news_signals: [],
        sources: [],
      });
    }
    if (apiPath === '/mission-room/macro-indicators') {
      return json(route, {
        indicators: [{ key: 'throughput', label: 'Débit', current: 1284, unit: 'h', source: 'series' }],
        source: 'series',
      });
    }

    if (method === 'GET') {
      if (apiPath.endsWith('s') || apiPath.includes('items')) return json(route, []);
      return json(route, {});
    }
    return json(route, { ok: true });
  });
}

async function openHypervisor(page: Page): Promise<void> {
  await page.goto('/hypervisor');
  await expect(page.locator('app-hypervisor-v2')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('hypervisor-v2-hero')).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
}

/** The cockpit shell is a fixed 100dvh grid; grow the viewport so the ledger is not clipped. */
async function captureFullLedger(page: Page, dest: string): Promise<void> {
  const height = await page.locator('app-hypervisor-v2').evaluate((el) => {
    const main = el.closest('#main-content');
    const measured = Math.max(el.scrollHeight, main instanceof HTMLElement ? main.scrollHeight : 0);
    return Math.min(Math.max(measured + 96, 1100), 4200);
  });
  await page.setViewportSize({ width: 1680, height });
  await page.screenshot({ path: dest, animations: 'disabled' });
}

async function selectFacet(page: Page, facet: (typeof FACETS)[number]): Promise<void> {
  if (facet === 'synthese') {
    const tab = page.locator('#ck-tab-synthese');
    if ((await tab.getAttribute('aria-selected')) !== 'true') await tab.click();
    await expect(tab).toHaveAttribute('aria-selected', 'true');
    return;
  }
  await page.locator(`#ck-tab-${facet}`).click();
  await expect(page.locator(`#ck-tab-${facet}`)).toHaveAttribute('aria-selected', 'true');
  await expect.poll(() => new URL(page.url()).searchParams.get('facet')).toBe(facet);
}

test.use({
  viewport: { width: 1680, height: 1100 },
  locale: 'fr-FR',
  colorScheme: 'dark',
});

test.describe('Hypervisor V2 — mocked visual', () => {
  test.skip(!visualEnabled, 'Set E2E_HYPERVISOR_V2_VISUAL=1 to capture the mocked visual proof');
  test.setTimeout(4 * 60 * 1_000);

  test('dense and sparse, dark and light, four facets', async ({ browser }) => {
    await mkdir(RESULTS, { recursive: true });
    const shots: Record<string, string> = {};

    for (const kind of ['dense', 'sparse'] as const) {
      for (const theme of ['dark', 'light'] as const) {
        const context = await browser.newContext({
          viewport: { width: 1680, height: 1100 },
          locale: 'fr-FR',
          colorScheme: theme,
        });
        const page = await context.newPage();
        await installMocks(page, kind, theme);
        await openHypervisor(page);

        if (kind === 'dense') {
          await expect(page.locator('[data-testid="hypervisor-v2-hero"] .hv2-monument')).toContainText(/1\s*284/);
          await expect(page.locator('[data-testid="hypervisor-v2-hero"] .hv2-peak-value')).toContainText(/71/);
        } else {
          await expect(page.locator('[data-testid="hypervisor-v2-hero"] .hv2-monument')).toContainText(/2[,.]5/);
        }

        for (const facet of FACETS) {
          await page.setViewportSize({ width: 1680, height: 1100 });
          await selectFacet(page, facet);
          if (facet === 'synthese') {
            await expect(page.getByTestId('hypervisor-v2-register')).toBeVisible();
            await expect(page.locator('app-hypervisor-v2.hv2-enter')).toHaveCount(0, { timeout: 4_000 });
          }
          if (facet === 'bases') {
            await expect(page.getByTestId('hypervisor-v2-value-bases')).toBeVisible();
          }
          const dest = path.join(RESULTS, `${kind}-${theme}-${facet}.png`);
          await captureFullLedger(page, dest);
          shots[`${kind}-${theme}-${facet}`] = dest;
        }

        if (kind === 'dense') {
          await page.setViewportSize({ width: 1680, height: 1100 });
          await selectFacet(page, 'synthese');
          await expect(page.locator('app-hypervisor-v2.hv2-enter')).toHaveCount(0, { timeout: 4_000 });
          await captureHoverProof(page, theme, shots);
          await page.getByTestId('hypervisor-v2-view-operations').click();
          await expect(page.locator('[data-testid="hypervisor-v2-hero"] .hv2-monument-unit')).toContainText(/runs/i);
          const operations = path.join(RESULTS, `dense-${theme}-operations.png`);
          await captureFullLedger(page, operations);
          shots[`dense-${theme}-operations`] = operations;
          await page.getByTestId('hypervisor-v2-view-conformite').click();
          await expect(page.getByTestId('hypervisor-v2-unites')).toBeVisible();
          await expect(page.getByTestId('hypervisor-v2-unites').locator('.hv2-monument')).toHaveCount(0);
          await expect(page.getByTestId('hypervisor-v2-unites').locator('.hv2-unites-row')).not.toHaveCount(0);
          const conformite = path.join(RESULTS, `dense-${theme}-conformite.png`);
          await captureFullLedger(page, conformite);
          shots[`dense-${theme}-conformite`] = conformite;
        }
        await context.close();
      }
    }

    const reduced = await browser.newContext({
      viewport: { width: 1680, height: 1100 },
      locale: 'fr-FR',
      colorScheme: 'dark',
      reducedMotion: 'reduce',
    });
    const reducedPage = await reduced.newPage();
    await reducedPage.emulateMedia({ reducedMotion: 'reduce' });
    await installMocks(reducedPage, 'dense', 'dark');
    await openHypervisor(reducedPage);
    await expect(reducedPage.locator('[data-testid="hypervisor-v2-hero"] .hv2-monument')).toContainText(/1\s*284/);
    await expect(reducedPage.locator('app-hypervisor-v2.hv2-enter')).toHaveCount(0);
    await expect(reducedPage.locator('[style*="hv2FadeUp"], [style*="ckSpokeIn"], [style*="ckRibbonIn"], [style*="ckAreaIn"]')).toHaveCount(0);
    await reduced.close();

    expect(Object.keys(shots).length).toBeGreaterThanOrEqual(16);
  });

  test('L13b Impact agenda view binds live Mission Room blocks', async ({ browser }) => {
    test.skip(!visualEnabled, 'Set E2E_HYPERVISOR_V2_VISUAL=1 to run');
    const context = await browser.newContext({
      viewport: { width: 1680, height: 1100 },
      locale: 'fr-FR',
      colorScheme: 'dark',
    });
    const page = await context.newPage();
    await installMocks(page, 'dense', 'dark');
    await page.goto('/hypervisor?view=agenda');
    await expect(page.locator('app-hypervisor-v2')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('impact-block-echeancier')).toBeVisible();
    await expect(page.getByText('Revue portefeuille')).toBeVisible();
    await expect(page.getByTestId('impact-block-echeancier-empty')).toHaveCount(0);
    await context.close();
  });
});

async function captureHoverProof(
  page: Page,
  theme: ThemeKind,
  shots: Record<string, string>,
): Promise<void> {
  await page.getByTestId('ck-radial-peak').hover();
  const radialTip = page.locator('ck-chart-radial-days [data-testid="ck-chart-tip"]');
  await expect(radialTip).toBeVisible();
  await expect(radialTip).toContainText(/71/);
  await expect(radialTip).toContainText(/25|août|Aug/i);
  const radial = path.join(RESULTS, `dense-${theme}-synthese-hover-radial.png`);
  await page.screenshot({ path: radial, animations: 'disabled' });
  shots[`dense-${theme}-synthese-hover-radial`] = radial;

  await page.locator('ck-chart-sankey-flow [data-system="sys-capture"]').first().hover();
  const sankeyTip = page.locator('ck-chart-sankey-flow [data-testid="ck-chart-tip"]');
  await expect(sankeyTip).toBeVisible();
  await expect(sankeyTip).toContainText(/Capture Invoices/);
  const sankey = path.join(RESULTS, `dense-${theme}-synthese-hover-sankey.png`);
  await page.screenshot({ path: sankey, animations: 'disabled' });
  shots[`dense-${theme}-synthese-hover-sankey`] = sankey;

  const rivers = page.getByTestId('hypervisor-v2-stratum-comprendre');
  await rivers.getByTestId('ck-stream-day-15').hover();
  const streamTip = rivers.locator('ck-chart-stream [data-testid="ck-chart-tip"]');
  await expect(rivers.locator('ck-chart-stream .ck-crosshair')).toHaveCount(1);
  await expect(streamTip).toBeVisible();
  const stream = path.join(RESULTS, `dense-${theme}-synthese-hover-stream.png`);
  await page.screenshot({ path: stream, animations: 'disabled' });
  shots[`dense-${theme}-synthese-hover-stream`] = stream;

  await page.locator('[data-testid="hypervisor-v2-register"] [data-system-id="sys-capture"]').hover();
  await expect(page.locator('ck-chart-sankey-flow [data-system="sys-capture"].is-lit').first()).toBeVisible();
}
