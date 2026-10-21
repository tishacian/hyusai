import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test, type Browser, type Page } from '@playwright/test';
import { appFetch, expectOk } from '../fixtures/api';

/**
 * Plan lot 4 — test 71: from a blank workspace to an application opened in
 * Work by a second account (report scenario 1, "internal procedures
 * assistant", pp. 30-31). No seed, no fixture business data, no example file:
 * a new workspace is created during the test and deleted at the end.
 *
 * It runs ONLY against a test stack (local or recette) with three provisioned
 * accounts, and refuses to start otherwise, because Playwright's default base
 * URL is production (playwright.config.ts) and this test creates a workspace.
 *
 *   E2E_BASE_URL=https://recette.example  E2E_BLANK_WORKSPACE=1 \
 *   E2E_CREATOR_USERNAME=…  E2E_CREATOR_PASSWORD=… \
 *   E2E_COLLABORATOR_USERNAME=…  E2E_COLLABORATOR_PASSWORD=… \
 *   E2E_OUTSIDER_USERNAME=…  E2E_OUTSIDER_PASSWORD=… \
 *   [E2E_BLANK_CORPUS=procedures-b]  npx playwright test e2e/tests/71-blank-workspace-to-work.spec.ts
 *
 * The answer is checked by identifiers (Run id, cited document), never by
 * the generated wording. Steps on screens owned by other lots (publishing a
 * Flow) go through the same API those screens call.
 */

const PRODUCTION_HOSTS = ['agentium.papai.ai'];
const baseUrl = process.env['E2E_BASE_URL'] ?? '';
const optIn = process.env['E2E_BLANK_WORKSPACE'] === '1';
const corpusName = process.env['E2E_BLANK_CORPUS'] ?? 'procedures-a';
const corpusDir = join(__dirname, '..', 'fixtures', 'corpus', corpusName);

interface Account { username: string; password: string }
function account(prefix: string): Account | null {
  const username = process.env[`E2E_${prefix}_USERNAME`];
  const password = process.env[`E2E_${prefix}_PASSWORD`];
  return username && password ? { username, password } : null;
}
const creator = account('CREATOR');
const collaborator = account('COLLABORATOR');
const outsider = account('OUTSIDER');

function refusal(): string | null {
  if (!optIn) return 'Set E2E_BLANK_WORKSPACE=1 to run the blank-workspace test on a test stack';
  if (!baseUrl) return 'E2E_BASE_URL is required: without it Playwright targets production';
  if (PRODUCTION_HOSTS.includes(new URL(baseUrl).hostname)) return 'This test creates a workspace: never against production';
  if (!creator || !collaborator || !outsider) return 'Three provisioned accounts are required (CREATOR, COLLABORATOR, OUTSIDER)';
  return null;
}

async function login(page: Page, who: Account, workspaceSlug?: string): Promise<void> {
  await page.goto('/auth/signin');
  const result = await page.evaluate(async ({ email, secret, slug }) => {
    const response = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password: secret, remember_me: false }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || !body.token) return { ok: false, status: response.status };
    localStorage.setItem('agentium_token', `Bearer ${body.token}`);
    if (body.refresh_token) localStorage.setItem('agentium_refresh_token', body.refresh_token);
    if (slug) localStorage.setItem('agentium_workspace_slug', slug);
    return { ok: true, status: response.status };
  }, { email: who.username, secret: who.password, slug: workspaceSlug ?? null });
  expect(result.ok, `login ${who.username}: ${JSON.stringify(result)}`).toBe(true);
}

async function asAccount<T>(browser: Browser, who: Account, slug: string, body: (page: Page) => Promise<T>): Promise<T> {
  const context = await browser.newContext({ baseURL: baseUrl });
  const page = await context.newPage();
  try {
    await login(page, who, slug);
    return await body(page);
  } finally {
    await context.close();
  }
}

interface Scenario { question: string; expected_document: string; off_topic: string }

test.describe.serial('Lot 4 — test 71: blank workspace to Work', () => {
  const reason = refusal();
  test.skip(!!reason, reason ?? '');

  const stamp = Date.now().toString(36);
  const workspaceName = `Recette départ vierge ${stamp}`;
  let slug = '';
  const scenario = JSON.parse(readFileSync(join(corpusDir, 'scenario.json'), 'utf8')) as Scenario;
  let appSlug = '';

  test.afterAll(async ({ browser }) => {
    if (!slug || !creator) return;
    await asAccount(browser, creator, slug, async (page) => {
      const deleted = await appFetch(page, `/api/v1/auth/workspaces/${slug}`, {
        method: 'DELETE',
        data: { confirm_name: workspaceName },
      });
      expect([200, 204]).toContain(deleted.status);
    });
  });

  test('1. a blank workspace is created and Work is turned on from the settings', async ({ page }) => {
    await login(page, creator!);
    const created = await expectOk<{ slug: string; settings: Record<string, unknown> }>(page, '/api/v1/auth/workspaces', {
      method: 'POST',
      data: { name: workspaceName },
    });
    slug = created.slug;
    expect((created.settings['features'] as Record<string, unknown> | undefined)?.['experience_v1']).toBeUndefined();
    await page.evaluate((value) => localStorage.setItem('agentium_workspace_slug', value), slug);

    // Before activation, Work explains itself instead of redirecting.
    await page.goto('/work');
    await expect(page.getByTestId('access-state')).toHaveAttribute('data-reason', 'disabled');

    await page.goto(`/workspace/${slug}/settings`);
    const setting = page.getByTestId('experience-activation');
    await expect(setting.getByTestId('experience-activation-effect')).toBeVisible();
    await setting.getByTestId('experience-activation-toggle').click();
    await page.getByRole('alertdialog').getByRole('button').last().click();
    await expect(setting.getByTestId('experience-activation-state')).toHaveAttribute('data-enabled', 'true');

    for (const [who, role] of [[collaborator!, 'workspace_viewer']] as const) {
      await expectOk(page, `/api/v1/auth/workspaces/${slug}/members`, {
        method: 'POST',
        data: { email: who.username, role_template: role },
      });
    }
  });

  test('2. three neutral documents are imported through the interface', async ({ page }) => {
    await login(page, creator!, slug);
    await page.goto('/knowledge');
    const files = readdirSync(corpusDir).filter((name) => name.endsWith('.md')).map((name) => join(corpusDir, name));
    expect(files).toHaveLength(3);
    await page.locator('input[type="file"]').first().setInputFiles(files);
    await expect.poll(async () => {
      const documents = await appFetch<{ documents?: Array<{ filename?: string; status?: string }> } | Array<{ filename?: string; status?: string }>>(page, '/api/v1/documents');
      const rows = Array.isArray(documents.body) ? documents.body : documents.body?.documents ?? [];
      return rows.filter((row) => row.status === 'indexed' || row.status === 'ready' || row.status === 'completed').length;
    }, { timeout: 180_000, intervals: [2_000] }).toBe(3);
  });

  test('3. the example is chosen on purpose, previewed, imported and published', async ({ page }) => {
    await login(page, creator!, slug);
    await page.goto('/create');
    await expect(page.getByTestId('prereq-work')).toHaveAttribute('data-state', 'ok');
    await expect(page.getByTestId('prereq-collection')).toHaveAttribute('data-state', 'ok');
    await page.getByTestId('start-example-choice').check();
    await page.getByTestId('start-example-internal_procedures_assistant').check();
    await expect(page.getByTestId('start-example-provenance')).toBeVisible();
    await expect(page.getByTestId('start-example-unresolved')).toHaveCount(0);
    await page.getByTestId('start-example-import').click();
    await expect(page).toHaveURL(/\/systems\/[^/]+\/flow/);
    const systemId = page.url().match(/\/systems\/([^/]+)\/flow/)![1]!;

    // Publishing the Flow belongs to the Flow screens (lot 5): same API they call.
    const state = await expectOk<{ draft?: { revision: number } | null; published_version_id?: string | null }>(
      page, `/api/v1/systems/${systemId}/flow-state`);
    await expectOk(page, `/api/v1/systems/${systemId}/flow/publish`, {
      method: 'POST',
      data: {
        expected_draft_revision: state.draft?.revision ?? 1,
        expected_published_version_id: state.published_version_id ?? null,
        message: 'Recette départ vierge',
      },
    });
  });

  test('4. the application is created in the wizard, released and deployed to the collaborator', async ({ page }) => {
    await login(page, creator!, slug);
    await page.goto('/create/apps/new');
    await page.locator('#xp-wiz-name').fill('Assistant procédures');
    await page.getByRole('radio').first().click();
    await page.locator('.xp-foot .xp-btn-primary').click();
    await expect(page).toHaveURL(/step=bind/);
    await page.locator('.xp-entry button').first().click();
    await page.locator('.xp-foot .xp-btn-primary').click();
    await expect(page).toHaveURL(/step=access/);
    await page.locator('input[type="checkbox"][value="workspace_viewer"], label:has-text("Lecteur") input, label:has-text("Viewer") input').first().check();
    await page.locator('.xp-foot .xp-btn-primary').click();
    await expect(page).toHaveURL(/\/create\/apps\/[^/?]+$/);
    appSlug = (await expectOk<{ experiences: Array<{ slug: string }> }>(page, '/api/v1/experiences')).experiences[0]!.slug;

    await page.getByRole('button', { name: /^(Publier|Publish)$/ }).click();
    const dialog = page.getByRole('dialog');
    await dialog.locator('#xp-pub-notes').fill('Recette départ vierge');
    await dialog.locator('.xp-foot .xp-btn-primary').click();
    await dialog.locator('input[name="xp-publish-channel"][value="live"]').check();
    await dialog.locator('.xp-foot .xp-btn-primary').click();
    const receipt = dialog.getByTestId('deploy-receipt');
    await expect(receipt).toBeVisible({ timeout: 30_000 });
    await expect(receipt.getByTestId('deploy-receipt-channel')).toHaveText(/En service|Live/);
    await expect(receipt.getByTestId('deploy-receipt-open')).toHaveAttribute('href', `/work/${appSlug}`);
  });

  test('5. the collaborator gets the cited passage, and an abstention outside the corpus', async ({ browser }) => {
    await asAccount(browser, collaborator!, slug, async (page) => {
      for (const [question, expectCitation] of [[scenario.question, true], [scenario.off_topic, false]] as const) {
        await page.goto(`/work/${appSlug}`);
        await page.getByRole('textbox').first().fill(question);
        const started = page.waitForResponse((response) =>
          response.request().method() === 'POST' && /\/work\/[^/]+\/bindings\/[^/]+\/runs$/.test(new URL(response.url()).pathname));
        await page.getByRole('button', { name: /Envoyer|Send|Submit/ }).first().click();
        const runId = ((await (await started).json()) as { id: string }).id;
        expect(runId).toBeTruthy();
        const run = await expect.poll(async () => {
          const read = await appFetch<{ status: string; output_ref?: { citations?: Array<Record<string, unknown>> } }>(page, `/api/v1/runs/${runId}`);
          return read.status === 200 ? read.body.status : `http-${read.status}`;
        }, { timeout: 120_000, intervals: [2_000] }).toBe('completed').then(() =>
          appFetch<{ output_ref?: { citations?: Array<Record<string, unknown>> } }>(page, `/api/v1/runs/${runId}`));
        const citations = run.body.output_ref?.citations ?? [];
        if (expectCitation) {
          expect(JSON.stringify(citations)).toContain(scenario.expected_document);
        } else {
          expect(citations).toEqual([]);
        }
      }
    });
  });

  test('6. an account without access is refused, and the refusal says so', async ({ browser }) => {
    await asAccount(browser, outsider!, slug, async (page) => {
      const listed = await appFetch<Array<{ slug: string }>>(page, '/api/v1/auth/workspaces');
      expect((listed.body ?? []).some((row) => row.slug === slug)).toBe(false);
      const work = await appFetch(page, `/api/v1/work/${appSlug}`, { headers: { 'X-Workspace-Slug': slug } });
      expect([403, 404]).toContain(work.status);
    });
  });
});
