import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';

/**
 * Plan lot 4 — where to start in Créer on a blank workspace (US03, US07,
 * US08, US09), fully mocked. Loopback only:
 *
 *   E2E_CHROME_V2_MOCKED=1 E2E_BASE_URL=http://127.0.0.1:4341 \
 *   npx playwright test e2e/tests/73-blank-start-mocked.spec.ts --trace=off
 */

const enabled = process.env['E2E_CHROME_V2_MOCKED'] === '1';
const SHOT_DIR = process.env['E2E_SHOT_DIR'] ?? 'test-results/lot4-start-shots';

test.use({ serviceWorkers: 'block', video: 'off', viewport: { width: 1440, height: 900 } });

const WORKSPACE = {
  id: 'ws-blank',
  name: 'Procédures',
  slug: 'blank-lot4',
  role: 'admin',
  role_template: 'workspace_admin',
  member_count: 1,
  settings: { family: 'generic', features: { experience_v1: true } },
  mode: 'executive',
};

const EXAMPLE = {
  id: 'internal_procedures_assistant',
  version: '1',
  name: 'Internal procedures assistant',
  objective: 'Answer questions about internal procedures from the workspace documents.',
  requires: ['completion_model', 'collection'],
  provenance: { publisher: 'Agentium', source: 'builtin', example_id: 'internal_procedures_assistant', version: '1' },
  envelope: { kind: 'agentium.system.export', schema_version: 1, system: { name: 'Internal procedures assistant' } },
};

const PREVIEW = {
  name: EXAMPLE.name,
  objective: EXAMPLE.objective,
  nodes: [
    { id: 'trigger', label: 'Question', kind: 'source', skill_slug: null },
    { id: 'answer', label: 'Sourced answer', kind: 'task', skill_slug: 'llm_rag_answer_v1' },
    { id: 'output', label: 'Answer', kind: 'sink', skill_slug: null },
  ],
  edge_count: 2,
  resolved_skills: [],
  unresolved_skills: ['llm_rag_answer_v1'],
  source: { example_id: EXAMPLE.id, example_version: '1' },
  valid: true,
  issues: [],
};

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

type Handler = (route: Route) => Promise<void>;

interface Mock {
  skills?: Handler;
  collections?: Handler;
  systems?: Handler;
  createSystem?: Handler;
  examples?: Handler;
  preview?: Handler;
  importSystem?: Handler;
}

async function install(page: Page, mock: Mock = {}, locale: 'fr' | 'en' = 'fr', theme: 'dark' | 'light' = 'dark'): Promise<string[]> {
  const baseURL = test.info().project.use.baseURL;
  if (!baseURL || !['localhost', '127.0.0.1'].includes(new URL(baseURL).hostname)) {
    throw new Error('Lot 4 start fixtures require a loopback E2E_BASE_URL');
  }
  const writes: string[] = [];
  await page.route('**/*', (route) => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname)
    ? route.fallback() : route.abort('blockedbyclient'));
  await page.addInitScript(({ slug, locale, theme }) => {
    localStorage.setItem('agentium_token', 'Bearer mocked-lot4');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_locale', locale);
    localStorage.setItem('agentium_theme', theme);
  }, { slug: WORKSPACE.slug, locale, theme });
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    const method = request.method();
    // Creations only: telemetry and preference writes are not what is checked.
    if (method !== 'GET' && /^\/(systems|experiences|documents)/.test(path)) writes.push(`${method} ${path}`);
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'u', email: 'ada@example.test', role: 'user' });
    if (path === '/auth/me') return json(route, { id: 'u', email: 'ada@example.test', workspaces: [] });
    if (path === '/auth/workspaces') return json(route, [WORKSPACE]);
    if (path === `/auth/workspaces/${WORKSPACE.slug}`) return json(route, WORKSPACE);
    if (path === '/skills') return (mock.skills ?? ((r) => json(r, [])))(route);
    if (path === '/documents/collections') return (mock.collections ?? ((r) => json(r, { collections: [], items: [] })))(route);
    if (path === '/systems/examples') return (mock.examples ?? ((r) => json(r, { examples: [EXAMPLE] })))(route);
    if (path === '/systems/import/preview') return (mock.preview ?? ((r) => json(r, PREVIEW)))(route);
    if (path === '/systems/import') return (mock.importSystem ?? ((r) => json(r, { id: 'sys-imported' })))(route);
    if (path === '/systems' && method === 'POST') return (mock.createSystem ?? ((r) => json(r, { id: 'sys-new' }, 201)))(route);
    if (path === '/systems') return (mock.systems ?? ((r) => json(r, [])))(route);
    if (path === '/experiences') return json(route, { experiences: [] });
    if (path === '/help-content') return json(route, { version: 'local', personas: [], languages: [], items: [] });
    if (method === 'GET') return json(route, path.endsWith('s') ? [] : {});
    return json(route, { ok: true });
  });
  return writes;
}

async function expectNoSeriousAxe(page: Page, selector: string): Promise<void> {
  const results = await new AxeBuilder({ page })
    .include(selector)
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze();
  const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
  expect(serious, serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`).join('\n')).toEqual([]);
}

test.describe('Lot 4 — where to start', () => {
  test.skip(!enabled, 'Set E2E_CHROME_V2_MOCKED=1 to run the mocked lot 4 checks');

  for (const theme of ['dark', 'light'] as const) {
    test(`blank workspace: an explicit choice, nothing imported, and the real inventory (${theme})`, async ({ page }) => {
      const writes = await install(page, {}, 'fr', theme);
      await page.goto('/create');
      await expect(page.getByTestId('start-point')).toBeVisible();
      await expect(page.getByTestId('start-zero')).not.toBeChecked();
      await expect(page.getByTestId('start-example-choice')).not.toBeChecked();
      await expect(page.getByTestId('start-zero-form')).toHaveCount(0);
      const inventory = page.getByTestId('start-prerequisites');
      await expect(inventory.getByTestId('prereq-work')).toHaveAttribute('data-state', 'ok');
      await expect(inventory.getByTestId('prereq-model')).toHaveAttribute('data-state', 'missing');
      await expect(inventory.getByTestId('prereq-collection')).toHaveAttribute('data-state', 'missing');
      await expect(inventory.getByTestId('prereq-system')).toHaveAttribute('data-state', 'missing');
      await expect(inventory.getByTestId('prereq-publish')).toHaveAttribute('data-state', 'ok');
      await expect(inventory.getByTestId('prereq-collection').getByRole('link')).toHaveAttribute('href', /\/knowledge/);
      await expectNoSeriousAxe(page, '[data-testid="start-point"]');
      await page.screenshot({ path: `${SHOT_DIR}/blank-start-${theme}.png`, fullPage: true });
      expect(writes).toEqual([]);
    });
  }

  for (const failure of ['500', '403', '504', 'timedout', 'failed'] as const) {
    test(`a failed inventory read (${failure}) shows "unknown" with Retry, never "missing"`, async ({ page }) => {
      let healthy = false;
      await install(page, {
        collections: (route) => {
          if (healthy) return json(route, { items: [{ slug: 'procedures' }] });
          return failure === 'timedout' || failure === 'failed' ? route.abort(failure) : json(route, {}, Number(failure));
        },
      });
      await page.goto('/create');
      const item = page.getByTestId('prereq-collection');
      await expect(item).toHaveAttribute('data-state', 'error');
      healthy = true;
      await item.getByRole('button').click();
      await expect(item).toHaveAttribute('data-state', 'ok');
    });
  }

  test('from scratch without a completion model: named, linked, nothing created', async ({ page }) => {
    const writes = await install(page);
    await page.goto('/create');
    await page.getByTestId('start-zero').check();
    await page.getByTestId('start-zero-create').click();
    const error = page.getByTestId('start-zero-error');
    await expect(error).toHaveAttribute('data-kind', 'no_model');
    await expect(error.getByTestId('start-zero-model-link')).toHaveAttribute('href', /\/resources/);
    expect(writes).toEqual([]);
  });

  test('from scratch refused by the server reads differently from a missing model', async ({ page }) => {
    await install(page, {
      skills: (route) => json(route, [{ id: 'sk', slug: 'workspace_llm_v1', name: 'LLM' }]),
      createSystem: (route) => json(route, { detail: 'denied' }, 403),
    }, 'en');
    await page.goto('/create');
    await page.getByTestId('start-zero').check();
    await page.getByTestId('start-zero-create').click();
    await expect(page.getByTestId('start-zero-error')).toHaveAttribute('data-kind', 'refused');
    await expect(page.getByTestId('start-zero-error')).toContainText('Your role does not allow creating a System');
  });

  test('from scratch with no answer is "unknown", not "failed"', async ({ page }) => {
    await install(page, {
      skills: (route) => json(route, [{ id: 'sk', slug: 'workspace_llm_v1', name: 'LLM' }]),
      createSystem: (route) => route.abort('timedout'),
    });
    await page.goto('/create');
    await page.getByTestId('start-zero').check();
    await page.getByTestId('start-zero-create').click();
    await expect(page.getByTestId('start-zero-error')).toHaveAttribute('data-kind', 'unverifiable');
  });

  test('an example shows its origin, objects and missing dependencies before anything is created', async ({ page }) => {
    const writes = await install(page, {}, 'en');
    await page.goto('/create');
    await page.getByTestId('start-example-choice').check();
    await page.getByTestId('start-example-internal_procedures_assistant').check();
    await expect(page.getByTestId('start-example-provenance')).toContainText('Built-in example, published by Agentium, version 1');
    await expect(page.getByTestId('start-example-preview')).toContainText('Sourced answer');
    await expect(page.getByTestId('start-example-unresolved')).toContainText('llm_rag_answer_v1');
    expect(writes).toEqual(['POST /systems/import/preview']);
    await expectNoSeriousAxe(page, '[data-testid="start-point"]');
    await page.screenshot({ path: `${SHOT_DIR}/example-preview.png`, fullPage: true });
    await page.getByTestId('start-example-import').click();
    await expect(page).toHaveURL(/sys-imported/);
    expect(writes).toEqual(['POST /systems/import/preview', 'POST /systems/import']);
  });

  test('an example import refused by the server says so and creates nothing', async ({ page }) => {
    await install(page, { importSystem: (route) => json(route, { detail: 'denied' }, 403) });
    await page.goto('/create');
    await page.getByTestId('start-example-choice').check();
    await page.getByTestId('start-example-internal_procedures_assistant').check();
    await page.getByTestId('start-example-import').click();
    await expect(page.getByTestId('start-example-import-error')).toContainText('Votre rôle ne permet pas');
    await expect(page).toHaveURL(/\/create$/);
  });

  test('a failed example list offers Retry, an empty one says so', async ({ page }) => {
    let rows: unknown = null;
    await install(page, { examples: (route) => (rows === null ? json(route, {}, 500) : json(route, { examples: rows })) });
    await page.goto('/create');
    await page.getByTestId('start-example-choice').check();
    await expect(page.getByTestId('start-example-list-error')).toBeVisible();
    rows = [];
    await page.getByTestId('start-example-list-error').getByRole('button').click();
    await expect(page.getByTestId('start-example-empty')).toBeVisible();
  });
});
