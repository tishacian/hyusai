import { expect, test, type Route, type TestInfo } from '@playwright/test';

/**
 * Tranche C — local, fully mocked measurement of the Flow Builder palette.
 *
 * Local-only and read-only: every `/api/v1/**` request is intercepted, so this
 * spec can never touch a shared environment. It exists because the density and
 * layout claims about the palette are claims about compiled component CSS in a
 * real viewport, which is exactly what a source review cannot check.
 *
 * The fixture is the shape of the production catalog: 85 registry rows, 28 of
 * them visible to this workspace, the rest excluded with a stated reason.
 */

const WORKSPACE_SLUG = 'palette-density';
const WORKSPACE_ID = 'workspace-palette-density';
const TOKEN = 'Bearer local-palette-density-token';

const CATEGORIES = [
  'LLM',
  'Retrieval',
  'Connections',
  'Ingestion',
  'Voice',
  'Governance',
  'Analysis',
  'Decision Support',
  'Automation',
];
const CAPABILITY_SLUGS = [
  'ticket_triage',
  'knowledge_ops',
  'document_intake',
  'quality_review',
  'operator_assist',
  'reporting',
];
const TOTAL_SKILLS = 85;
const VISIBLE_SKILLS = 28;

interface SkillRow {
  id: string;
  slug: string;
  name: string;
  description: string;
  category: string;
  runtime_status: string;
  metrics: { calls?: number };
  visibility: { visible: boolean; reason: string; capabilities: string[] };
}

function catalog(): { skills: SkillRow[]; filtered: number } {
  const skills: SkillRow[] = [];
  for (let index = 0; index < TOTAL_SKILLS; index += 1) {
    const visible = index < VISIBLE_SKILLS;
    const category = CATEGORIES[index % CATEGORIES.length];
    skills.push({
      id: `skill-${index}`,
      slug: `catalog_operation_${String(index).padStart(2, '0')}_v1`,
      name: `${category} operation ${String(index).padStart(2, '0')}`,
      description: `Performs the ${category.toLowerCase()} step number ${index} of a flow`,
      category,
      runtime_status: index % 7 === 0 ? 'stub' : 'bound',
      // Sparse on purpose: a young workspace has invocations on a handful of
      // skills, which is what the usage shortcut has to survive.
      metrics: visible && index % 9 === 0 ? { calls: 12 - index } : {},
      visibility: visible
        ? {
            visible: true,
            reason: 'capability',
            capabilities: [CAPABILITY_SLUGS[index % CAPABILITY_SLUGS.length]],
          }
        : { visible: false, reason: 'no_visible_capability', capabilities: [] },
    });
  }
  return { skills, filtered: TOTAL_SKILLS - VISIBLE_SKILLS };
}

const workspace = {
  id: WORKSPACE_ID,
  name: 'Palette density workspace',
  slug: WORKSPACE_SLUG,
  role: 'admin',
  role_template: 'workspace_admin',
  member_count: 1,
  created_at: '2026-08-08T08:00:00Z',
  is_active: true,
  mode: 'builder',
  settings: {},
  effective_features: {},
  app_entitlements: [],
};

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

function localOnly(testInfo: TestInfo): boolean {
  const configured = testInfo.project.use.baseURL;
  if (typeof configured !== 'string') return false;
  try {
    const url = new URL(configured);
    return url.hostname === 'localhost' || url.hostname === '127.0.0.1';
  } catch {
    return false;
  }
}

test.use({ serviceWorkers: 'block', video: 'off', viewport: { width: 1440, height: 900 } });

test('the palette opens on capabilities, one line per entry, and stays inside its cell', async (
  { page },
  testInfo,
) => {
  test.skip(
    !localOnly(testInfo),
    'This mocked palette measurement is local-only; set E2E_BASE_URL=http://localhost:4200.',
  );

  const fixture = catalog();
  let skillRequests = 0;
  let includedFiltered = 0;

  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') return route.fallback();
    return route.abort('blockedbyclient');
  });

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, '');

    if (path === '/auth/validate') {
      return json(route, {
        valid: true,
        user_id: 'user-palette',
        email: 'palette@example.test',
        role: 'admin',
      });
    }
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === '/auth/me') {
      return json(route, {
        id: 'user-palette',
        username: 'palette',
        email: 'palette@example.test',
        role: 'admin',
        is_active: true,
        mfa_enabled: false,
        workspaces: [workspace],
      });
    }
    if (path === '/skills') {
      skillRequests += 1;
      if (url.searchParams.get('include_filtered') === 'true') includedFiltered += 1;
      return json(route, {
        skills: fixture.skills,
        catalog: {
          total: TOTAL_SKILLS,
          visible: VISIBLE_SKILLS,
          filtered: fixture.filtered,
          filtered_reasons: { no_visible_capability: fixture.filtered },
        },
      });
    }
    if (path === '/capabilities') {
      return json(route, {
        capabilities: CAPABILITY_SLUGS.map((slug, index) => ({
          id: `cap-${index}`,
          slug,
          name: slug.replace(/_/g, ' ').replace(/^./, (letter) => letter.toUpperCase()),
          description: `Business capability ${slug}`,
          tier: 'universal',
          skill_ids: [],
        })),
      });
    }
    if (path === '/help-content') {
      return json(route, { version: 'local', personas: [], languages: [], items: [] });
    }
    // Anything else the shell loads in the background is irrelevant to a
    // geometry measurement: answer empty rather than fail the page.
    if (request.method() === 'GET') return json(route, {});
    return json(route, {}, 202);
  });

  await page.addInitScript(({ token, workspaceSlug }) => {
    localStorage.setItem('agentium_token', token);
    localStorage.setItem('agentium_workspace_slug', workspaceSlug);
  }, { token: TOKEN, workspaceSlug: WORKSPACE_SLUG });

  await page.goto('/orchestration');
  const palette = page.locator('app-flow-palette');
  await expect(palette).toBeVisible();
  await expect(palette.getByRole('heading', { name: /Add node/ })).toBeVisible();

  // Shared chrome loads its own unfiltered `/skills`; the palette is the one
  // consumer that asks for the rows this workspace cannot see.
  expect(skillRequests).toBeGreaterThan(0);
  expect(includedFiltered).toBeGreaterThan(0);

  // ---- density -----------------------------------------------------------
  const rows = palette.locator('.ck-flow-palette__row');
  // Direct children only: the ranked list and the capability list, never the
  // rows an escape hatch or an expanded section nests below them.
  const listRows = palette.locator('.ck-flow-palette__body > .ck-flow-palette__row');
  const rowCount = await listRows.count();
  const rowHeight = (await rows.first().boundingBox())!.height;
  const geometry = await palette.locator('.ck-flow-palette__body').evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }));
  const builder = await page.locator('.flow-builder').evaluate((element) => ({
    height: element.getBoundingClientRect().height,
    scrollHeight: element.scrollHeight,
  }));
  const canvas = (await page.locator('.flow-builder__canvas').boundingBox())!;

  // One line per entry. The previous row spent 8px of padding around a 28px
  // icon tile plus a second text line, which no viewport can compress.
  expect(rowHeight).toBeLessThanOrEqual(26);
  // The default surface is Capabilities plus the usage shortcut, never the
  // 85-row registry.
  expect(rowCount).toBeLessThanOrEqual(CAPABILITY_SLUGS.length + 6);
  expect(geometry.scrollHeight).toBeLessThanOrEqual(geometry.clientHeight + 1);

  // Tranche A invariant: the palette lives inside its grid cell and can never
  // grow the builder past the viewport, whatever the catalog size.
  expect(builder.scrollHeight).toBeLessThanOrEqual(Math.ceil(builder.height) + 1);
  expect(canvas.height).toBeGreaterThanOrEqual(260);

  await palette.screenshot({ path: testInfo.outputPath('palette-capabilities.png') });

  // ---- contextual insertion ----------------------------------------------
  // Selecting a node turns the palette into "what connects here". The risk
  // this carries is hiding what an author was looking for, so the escape
  // hatch is asserted in the same breath as the narrowing.
  await page.locator('app-flow-node').filter({ hasText: 'Objective' }).first().click();
  await expect(palette.getByRole('heading', { name: /Connects here/ })).toBeVisible();
  const banner = palette.locator('.ck-flow-palette__context');
  await expect(banner).toContainText('Objective');
  await expect(banner).toContainText('goal');
  await expect(banner).toContainText('string');
  const contextRows = await listRows.count();
  expect(contextRows).toBeGreaterThan(0);
  expect(contextRows).toBeLessThanOrEqual(12);
  await palette.screenshot({ path: testInfo.outputPath('palette-contextual.png') });

  await banner.getByRole('button', { name: 'Show all' }).click();
  await expect(palette.getByRole('heading', { name: /Add node/ })).toBeVisible();
  await expect(banner).toHaveCount(0);

  // ---- search ------------------------------------------------------------
  const search = palette.getByRole('searchbox');
  await search.fill('operation');
  await expect(palette.getByRole('heading', { name: /Matches/ })).toBeVisible();
  const rankedCount = await listRows.count();
  expect(rankedCount).toBeLessThanOrEqual(12);
  await expect(palette.locator('.ck-flow-palette__more')).toBeVisible();
  await palette.screenshot({ path: testInfo.outputPath('palette-search.png') });

  // A dead end explains itself instead of rendering nothing.
  await search.fill('catalog_operation_84');
  await expect(palette.locator('.ck-flow-palette__empty')).toContainText('Nothing available matches');
  await expect(palette.locator('.ck-flow-palette__hatch-why')).toContainText('not available in this workspace');
  await search.fill('');

  // ---- advanced ----------------------------------------------------------
  await palette.locator('.ck-flow-palette__advanced').click();
  await expect(palette.getByRole('heading', { name: /All skills/ })).toBeVisible();
  const sectionToggles = palette.locator('.ck-flow-palette__section-toggle');
  const sectionCount = await sectionToggles.count();
  expect(sectionCount).toBe(CATEGORIES.length);
  for (let index = 0; index < sectionCount; index += 1) {
    await expect(sectionToggles.nth(index)).toHaveAttribute('aria-expanded', 'false');
  }

  const collapsedAdvanced = await palette
    .locator('.ck-flow-palette__body')
    .evaluate((element) => element.scrollHeight);
  for (let index = 0; index < sectionCount; index += 1) {
    await sectionToggles.nth(index).click();
    await expect(sectionToggles.nth(index)).toHaveAttribute('aria-expanded', 'true');
  }
  const expandedAdvanced = await palette
    .locator('.ck-flow-palette__body')
    .evaluate((element) => element.scrollHeight);
  const visibleRows = await rows.count();
  expect(visibleRows).toBe(VISIBLE_SKILLS);

  // The escape hatch is one click, and it names the lever.
  await palette.locator('.ck-flow-palette__hatch-toggle').click();
  await expect(palette.locator('.ck-flow-palette__hatch-why')).toContainText(
    'no capability enabled here carries it',
  );
  await expect(palette.locator('.ck-flow-palette__row.is-unavailable').first()).toBeDisabled();
  await palette.screenshot({ path: testInfo.outputPath('palette-escape-hatch.png') });

  const geometryReport = JSON.stringify({
    rowHeight,
    defaultSurfaceRows: rowCount,
    defaultSurfaceScrolls: geometry.scrollHeight > geometry.clientHeight,
    paletteViewport: geometry.clientHeight,
    collapsedAdvanced,
    expandedAdvanced,
    canvasHeight: canvas.height,
    builderHeight: builder.height,
  });
  // The numbers are the point of this spec: annotated for the JUnit report
  // (`embedAnnotationsAsProperties`) and printed for a local run.
  testInfo.annotations.push({ type: 'palette-geometry', description: geometryReport });
  console.log(`palette-geometry ${geometryReport}`);
});
