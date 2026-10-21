import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';

/**
 * Plan lot 4 — an addressable wizard whose progress lives on the server
 * (US32, and the "Link Systems" detour to publish a System), fully mocked.
 * Loopback only, on the lot 4 port:
 *
 *   E2E_CHROME_V2_MOCKED=1 E2E_BASE_URL=http://127.0.0.1:4341 \
 *   npx playwright test e2e/tests/74-wizard-resume-mocked.spec.ts --trace=off
 */

const enabled = process.env['E2E_CHROME_V2_MOCKED'] === '1';
const SHOT_DIR = process.env['E2E_SHOT_DIR'] ?? 'test-results/lot4-wizard-shots';

test.use({ serviceWorkers: 'block', video: 'off', viewport: { width: 1440, height: 900 } });

const WORKSPACE = {
  id: 'ws-wizard',
  name: 'Procédures',
  slug: 'wizard-lot4',
  role: 'admin',
  role_template: 'workspace_admin',
  member_count: 2,
  settings: { family: 'generic', features: { experience_v1: true } },
  mode: 'executive',
};

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

interface Server {
  experience: Record<string, unknown> | null;
  wizard: Record<string, unknown> | null;
  wizardWrites: number;
  refuseSlug: string | null;
  failWizardRead: boolean;
}

async function install(page: Page, server: Server, locale: 'fr' | 'en' = 'fr'): Promise<void> {
  const baseURL = test.info().project.use.baseURL;
  if (!baseURL || !['localhost', '127.0.0.1'].includes(new URL(baseURL).hostname)) {
    throw new Error('Lot 4 wizard fixtures require a loopback E2E_BASE_URL');
  }
  await page.route('**/*', (route) => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname)
    ? route.fallback() : route.abort('blockedbyclient'));
  await page.addInitScript(({ slug, locale }) => {
    localStorage.setItem('agentium_token', 'Bearer mocked-lot4');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_locale', locale);
    localStorage.setItem('agentium_theme', 'dark');
  }, { slug: WORKSPACE.slug, locale });
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    const method = request.method();
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'u', email: 'ada@example.test', role: 'user' });
    if (path === '/auth/me') return json(route, { id: 'u', email: 'ada@example.test', workspaces: [] });
    if (path === '/auth/workspaces') return json(route, [WORKSPACE]);
    if (path === `/auth/workspaces/${WORKSPACE.slug}`) return json(route, WORKSPACE);
    if (path === '/system-bindings') return json(route, { bindings: [] });
    if (path === '/systems' && method === 'GET') return json(route, []);
    if (path === '/experiences' && method === 'GET') {
      const rows = server.experience ? [{ ...server.experience, wizard_step: server.wizard ? server.wizard['step'] : null }] : [];
      return json(route, { experiences: rows });
    }
    if (path === '/experiences' && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>;
      if (server.refuseSlug && body['slug'] === server.refuseSlug) {
        server.refuseSlug = null;
        return json(route, { detail: { code: 'EXPERIENCE_SLUG_INVALID', message: 'slug must be a lowercase URL identifier.' } }, 422);
      }
      server.experience = {
        id: 'exp-1', name: body['name'], slug: body['slug'], pattern: body['pattern'], description: body['description'],
        emblem: body['emblem'], languages: body['languages'], theme: body['theme'], access_policy: {},
        updated_at: '2026-10-20T10:00:00', draft: { revision: 1, binding_keys: [], pages: { pages: [] } }, deployments: [],
      };
      return json(route, server.experience, 201);
    }
    if (path === '/experiences/exp-1/draft' && method === 'PUT') {
      return json(route, { experience_id: 'exp-1', revision: 2, binding_keys: [], pages: { pages: [] } });
    }
    if (path === '/experiences/exp-1/wizard') {
      if (method === 'PUT') {
        server.wizardWrites += 1;
        const body = request.postDataJSON() as Record<string, unknown>;
        server.wizard = { experience_id: 'exp-1', ...body };
        return json(route, { wizard: server.wizard });
      }
      if (server.failWizardRead) return json(route, {}, 503);
      return json(route, { wizard: server.wizard });
    }
    if (path === '/experiences/exp-1') return server.experience ? json(route, server.experience) : json(route, { detail: 'not found' }, 404);
    if (path.startsWith('/experiences/')) return json(route, { detail: { code: 'EXPERIENCE_NOT_FOUND' } }, 404);
    if (path === '/help-content') return json(route, { version: 'local', personas: [], languages: [], items: [] });
    if (method === 'GET') return json(route, path.endsWith('s') ? [] : {});
    return json(route, { ok: true });
  });
}

function fresh(): Server {
  return { experience: null, wizard: null, wizardWrites: 0, refuseSlug: null, failWizardRead: false };
}

test.describe('Lot 4 — addressable wizard', () => {
  test.skip(!enabled, 'Set E2E_CHROME_V2_MOCKED=1 to run the mocked lot 4 checks');

  test('step 2 is in the address and a reload comes back to it with everything chosen', async ({ page }) => {
    const server = fresh();
    await install(page, server);
    await page.goto('/create/apps/new');
    await page.locator('#xp-wiz-name').fill('Assistant procédures');
    await expect(page.getByTestId('wizard-slug')).toHaveValue('assistant-procedures');
    await page.getByRole('radio', { name: /Tableau de bord|Dashboard/ }).click();
    await expect(page.getByText('N’ouvre ni question libre ni dépôt de fichier : lecture seule.')).toBeVisible();
    await page.getByRole('button', { name: /Créer le brouillon et continuer|Create the draft and continue/ }).click();
    await expect(page).toHaveURL(/\/create\/apps\/new\?draft=exp-1&step=bind/);
    await expect(page.getByTestId('wizard-progress')).toHaveAttribute('data-state', 'saved');
    expect(server.wizard?.['step']).toBe(2);
    await expect(page.getByTestId('wizard-no-system')).toBeVisible();
    await page.screenshot({ path: `${SHOT_DIR}/wizard-no-system.png`, fullPage: true });

    await page.reload();
    await expect(page.getByTestId('wizard-no-system')).toBeVisible();
    await expect(page).toHaveURL(/draft=exp-1&step=bind/);
    await page.getByRole('button', { name: /Retour|Back/ }).click();
    await expect(page.locator('#xp-wiz-name')).toHaveValue('Assistant procédures');
    await expect(page.getByRole('radio', { name: /Tableau de bord|Dashboard/ })).toHaveAttribute('aria-checked', 'true');
  });

  test('"Create the System" keeps the way back, from Créer and from the applications list', async ({ page }) => {
    const server = fresh();
    server.experience = {
      id: 'exp-1', name: 'Assistant', slug: 'assistant', pattern: 'form_result', languages: ['fr'], theme: {},
      access_policy: {}, updated_at: '2026-10-20T10:00:00', draft: { revision: 2, binding_keys: [], pages: { pages: [] } }, deployments: [],
    };
    server.wizard = { experience_id: 'exp-1', step: 2, staged_bindings: [], audience: { roles: [], groups: [], whole_workspace: false } };
    await install(page, server, 'en');
    await page.goto('/create/apps/new?draft=exp-1&step=bind');
    await page.getByTestId('wizard-create-system').click();
    await expect(page).toHaveURL(/\/create\?returnTo=/);
    const back = page.getByTestId('hub-return-to-wizard').getByRole('link');
    await expect(back).toHaveAttribute('href', '/create/apps/new?draft=exp-1&step=bind');
    await expect(page.getByTestId('hub-resume-wizard')).toHaveAttribute('href', '/create/apps/new?draft=exp-1&step=bind');
    await back.click();
    await expect(page.getByTestId('wizard-no-system')).toBeVisible();
    await page.goto('/create/apps');
    await expect(page.getByTestId('apps-resume-wizard')).toHaveAttribute('href', '/create/apps/new?draft=exp-1&step=bind');
  });

  test('an address the server refuses is explained under the field', async ({ page }) => {
    const server = fresh();
    server.refuseSlug = 'assistant';
    await install(page, server, 'en');
    await page.goto('/create/apps/new');
    await page.locator('#xp-wiz-name').fill('Assistant');
    await page.getByRole('button', { name: /Create the draft and continue/ }).click();
    const error = page.getByTestId('wizard-slug-error');
    await expect(error).toHaveAttribute('data-kind', 'invalid');
    await expect(page.getByTestId('wizard-slug')).toHaveAttribute('aria-invalid', 'true');
    await expect(page.getByTestId('wizard-slug')).toHaveAttribute('aria-describedby', 'xp-wiz-slug-error');
    await page.getByTestId('wizard-slug').fill('Bad Address');
    await expect(error).toContainText('Address refused');
    await page.getByTestId('wizard-slug').fill('assistant-2');
    await expect(page.getByTestId('wizard-slug-error')).toHaveCount(0);
    const results = await new AxeBuilder({ page }).include('.xp-wizard').withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
    expect(serious.map((v) => v.id)).toEqual([]);
  });

  test('a failed resume read offers Retry and keeps the step', async ({ page }) => {
    const server = fresh();
    server.experience = {
      id: 'exp-1', name: 'Assistant', slug: 'assistant', pattern: 'form_result', languages: ['en'], theme: {},
      access_policy: {}, updated_at: '2026-10-20T10:00:00', draft: { revision: 2, binding_keys: [], pages: { pages: [] } }, deployments: [],
    };
    server.wizard = { experience_id: 'exp-1', step: 3, staged_bindings: [], audience: { roles: [], groups: [], whole_workspace: true } };
    server.failWizardRead = true;
    await install(page, server, 'en');
    await page.goto('/create/apps/new?draft=exp-1&step=access');
    await expect(page.getByTestId('wizard-resume-error')).toBeVisible();
    server.failWizardRead = false;
    await page.getByTestId('wizard-resume-error').getByRole('button').click();
    await expect(page).toHaveURL(/step=access/);
    await expect(page.getByTestId('wizard-progress')).toHaveAttribute('data-state', 'saved');
  });

  test('an unknown application in the address reads as not found', async ({ page }) => {
    await install(page, fresh(), 'en');
    await page.goto('/create/apps/new?draft=missing&step=bind');
    await expect(page.getByTestId('access-state')).toHaveAttribute('data-reason', 'not_found');
  });

  test('the step list does not scroll at 320 px', async ({ page }) => {
    await install(page, fresh(), 'en');
    await page.setViewportSize({ width: 320, height: 720 });
    await page.goto('/create/apps/new');
    const steps = page.locator('.xp-steps');
    await expect(steps).toBeVisible();
    expect(await steps.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
    const results = await new AxeBuilder({ page }).include('.xp-steps').withRules(['scrollable-region-focusable']).analyze();
    expect(results.violations).toEqual([]);
  });
});
