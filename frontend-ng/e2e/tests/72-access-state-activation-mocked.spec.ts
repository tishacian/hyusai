import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';

/**
 * Plan lot 4 — closed destinations (PL02) and the Work and Studio setting
 * (PL01), fully mocked. No backend, loopback only:
 *
 *   E2E_CHROME_V2_MOCKED=1 E2E_BASE_URL=http://127.0.0.1:4238 \
 *   npx playwright test e2e/tests/72-access-state-activation-mocked.spec.ts --trace=off
 */

const enabled = process.env['E2E_CHROME_V2_MOCKED'] === '1';
const SHOT_DIR = process.env['E2E_SHOT_DIR'] ?? 'test-results/lot4-access-shots';

test.use({ serviceWorkers: 'block', video: 'off', viewport: { width: 1440, height: 900 } });

type Workspace = Record<string, unknown> & { slug: string };

function workspace(overrides: Partial<Workspace> = {}): Workspace {
  return {
    id: 'ws-lot4',
    name: 'Procédures',
    slug: 'procedures-lot4',
    role: 'admin',
    role_template: 'workspace_admin',
    member_count: 5,
    settings: { family: 'generic', features: {} },
    mode: 'executive',
    ...overrides,
  };
}

const USER = { id: 'user-lot4', email: 'ada@example.test', role: 'user', is_active: true, mfa_enabled: false };

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

interface Mock {
  workspaces: (route: Route) => Promise<void>;
  activation?: (route: Route) => Promise<void>;
  experiences?: (route: Route) => Promise<void>;
}

async function install(page: Page, mock: Mock, locale: 'fr' | 'en' = 'fr', theme: 'dark' | 'light' = 'dark'): Promise<void> {
  const baseURL = test.info().project.use.baseURL;
  if (!baseURL || !['localhost', '127.0.0.1'].includes(new URL(baseURL).hostname)) {
    throw new Error('Lot 4 access fixtures require a loopback E2E_BASE_URL');
  }
  await page.route('**/*', (route) => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname)
    ? route.fallback() : route.abort('blockedbyclient'));
  await page.addInitScript(({ slug, locale, theme }) => {
    localStorage.setItem('agentium_token', 'Bearer mocked-lot4');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_locale', locale);
    localStorage.setItem('agentium_theme', theme);
  }, { slug: workspace().slug, locale, theme });
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: USER.id, email: USER.email, role: USER.role });
    if (path === '/auth/me') return json(route, { ...USER, workspaces: [] });
    if (path === '/auth/workspaces') return mock.workspaces(route);
    if (path === `/auth/workspaces/${workspace().slug}/features/experience` && mock.activation) return mock.activation(route);
    if (path.startsWith('/experiences/') && mock.experiences) return mock.experiences(route);
    if (path === `/auth/workspaces/${workspace().slug}`) return json(route, workspace());
    if (path === '/help-content') return json(route, { version: 'local', personas: [], languages: [], items: [] });
    if (request.method() === 'GET') return json(route, path.endsWith('s') ? [] : {});
    return json(route, { ok: true });
  });
}

async function expectNoSeriousAxe(page: Page, selector: string): Promise<void> {
  const results = await new AxeBuilder({ page })
    .include(selector)
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze();
  const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
  expect(serious, serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`).join('\n')).toEqual([]);
}

test.describe('Lot 4 — closed destinations', () => {
  test.skip(!enabled, 'Set E2E_CHROME_V2_MOCKED=1 to run the mocked lot 4 checks');

  for (const theme of ['dark', 'light'] as const) {
    test(`Work off: the page says so and who can turn it on, without redirecting (${theme})`, async ({ page }) => {
      await install(page, { workspaces: (route) => json(route, [workspace({ role: 'member', role_template: 'workspace_viewer' })]) }, 'fr', theme);
      await page.goto('/work');
      const state = page.getByTestId('access-state');
      await expect(state).toHaveAttribute('data-reason', 'disabled');
      await expect(page).toHaveURL(/\/unavailable\?reason=disabled/);
      await expect(page.getByRole('heading', { level: 1 })).toHaveText('Work n’est pas activé dans ce workspace');
      await expect(page.getByTestId('access-state-who')).toContainText('un administrateur ou le propriétaire');
      await expect(page.getByTestId('access-state-settings')).toHaveCount(0);
      await expectNoSeriousAxe(page, '[data-testid="access-state"]');
      await page.screenshot({ path: `${SHOT_DIR}/work-disabled-${theme}.png`, fullPage: true });
    });
  }

  test('an administrator sees the way to the setting', async ({ page }) => {
    await install(page, { workspaces: (route) => json(route, [workspace()]) });
    await page.goto('/create');
    await expect(page.getByTestId('access-state')).toHaveAttribute('data-reason', 'disabled');
    await expect(page.getByTestId('access-state-settings')).toHaveAttribute('href', '/workspace/procedures-lot4/settings');
  });

  test('a viewer opening the Studio gets "role insufficient" with the current role', async ({ page }) => {
    const viewer = workspace({ role: 'member', role_template: 'workspace_viewer', settings: { features: { experience_v1: true } } });
    await install(page, { workspaces: (route) => json(route, [viewer]) }, 'en');
    await page.goto('/create/apps');
    await expect(page.getByTestId('access-state')).toHaveAttribute('data-reason', 'forbidden');
    await expect(page.getByTestId('access-state-role')).toHaveText('Your current role: Viewer.');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Your role does not give access to this page');
  });

  for (const failure of ['500', '504', 'timedout', 'failed'] as const) {
    test(`workspaces read ${failure}: access not verifiable, Retry, no redirect`, async ({ page }) => {
      let healthy = false;
      await install(page, {
        workspaces: (route) => {
          if (healthy) return json(route, [workspace({ settings: { features: { experience_v1: true } } })]);
          if (failure === 'timedout' || failure === 'failed') return route.abort(failure);
          return json(route, { detail: 'down' }, Number(failure));
        },
      });
      await page.goto('/work');
      await expect(page.getByTestId('access-state')).toHaveAttribute('data-reason', 'unverifiable');
      await expect(page.getByTestId('access-state-retry')).toBeVisible();
      await page.getByTestId('access-state-retry').click();
      await expect(page.getByTestId('access-state-retry-failed')).toBeVisible();
      healthy = true;
      await page.getByTestId('access-state-retry').click();
      await expect(page).toHaveURL(/\/work(?:[?#].*)?$/);
    });
  }

  test('an unknown address and a hidden application both read as not found', async ({ page }) => {
    const member = workspace({ role: 'member', role_template: 'workspace_contributor', settings: { features: { experience_v1: true } } });
    await install(page, {
      workspaces: (route) => json(route, [member]),
      experiences: (route) => json(route, { detail: 'Experience not found.' }, 403),
    }, 'en');
    await page.goto('/no-such-page');
    await expect(page.getByTestId('access-state')).toHaveAttribute('data-reason', 'not_found');
    await expect(page.getByText('/no-such-page')).toBeVisible();
    await page.goto('/create/apps/hidden-app');
    await expect(page.getByTestId('access-state')).toHaveAttribute('data-reason', 'not_found');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Not found');
  });
});

test.describe('Lot 4 — Work and Studio setting', () => {
  test.skip(!enabled, 'Set E2E_CHROME_V2_MOCKED=1 to run the mocked lot 4 checks');

  const ACTIVATION = (on: boolean) => ({ enabled: on, studio_enabled: on, members: { total: 5, studio_editors: 2, studio_reviewers: 1 } });

  test('the effect is shown before confirming and the state shown afterwards is the server one', async ({ page }) => {
    const puts: unknown[] = [];
    let current = false;
    await install(page, {
      workspaces: (route) => json(route, [workspace({ settings: { features: { experience_v1: current } } })]),
      activation: async (route) => {
        if (route.request().method() === 'PUT') {
          puts.push(route.request().postDataJSON());
          current = true;
          return json(route, ACTIVATION(true));
        }
        return json(route, ACTIVATION(current));
      },
    });
    await page.goto('/workspace/procedures-lot4/settings');
    const section = page.getByTestId('experience-activation');
    await expect(section.getByTestId('experience-activation-state')).toHaveAttribute('data-enabled', 'false');
    await expect(section.getByTestId('experience-activation-effect')).toContainText('Membres qui pourront créer des applications dans le Studio : 2.');
    await section.getByTestId('experience-activation-toggle').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toContainText('Membres qui verront Work : 5. Créateurs dans le Studio : 2. Relecteurs : 1.');
    await expectNoSeriousAxe(page, '[data-testid="experience-activation"]');
    await dialog.getByRole('button', { name: 'Activer Work et Studio' }).click();
    await expect(section.getByTestId('experience-activation-saved')).toBeVisible();
    await expect(section.getByTestId('experience-activation-state')).toHaveAttribute('data-enabled', 'true');
    expect(puts).toEqual([{ enabled: true, expected_enabled: false }]);
    await page.screenshot({ path: `${SHOT_DIR}/activation-saved.png`, fullPage: true });
  });

  test('a value changed by another administrator is refused, then read again', async ({ page }) => {
    let reads = 0;
    await install(page, {
      workspaces: (route) => json(route, [workspace()]),
      activation: async (route) => {
        if (route.request().method() === 'PUT') {
          return json(route, { detail: { code: 'WORKSPACE_FEATURE_CONFLICT', current_enabled: true } }, 409);
        }
        reads += 1;
        return json(route, ACTIVATION(reads > 1));
      },
    });
    await page.goto('/workspace/procedures-lot4/settings');
    await page.getByTestId('experience-activation-toggle').click();
    await page.getByRole('alertdialog').getByRole('button', { name: 'Activer Work et Studio' }).click();
    await expect(page.getByTestId('experience-activation-conflict')).toBeVisible();
    await expect(page.getByTestId('experience-activation-saved')).toHaveCount(0);
    await expect(page.getByTestId('experience-activation-state')).toHaveAttribute('data-enabled', 'true');
  });

  for (const failure of ['timedout', 'failed', '504'] as const) {
    test(`a write that ends in ${failure} is "unknown, check", never a success`, async ({ page }) => {
      await install(page, {
        workspaces: (route) => json(route, [workspace()]),
        activation: async (route) => {
          if (route.request().method() === 'PUT') {
            return failure === '504' ? json(route, {}, 504) : route.abort(failure);
          }
          return json(route, ACTIVATION(false));
        },
      });
      await page.goto('/workspace/procedures-lot4/settings');
      await page.getByTestId('experience-activation-toggle').click();
      await page.getByRole('alertdialog').getByRole('button', { name: 'Activer Work et Studio' }).click();
      await expect(page.getByTestId('experience-activation-unknown')).toBeVisible();
      await expect(page.getByTestId('experience-activation-saved')).toHaveCount(0);
      await expect(page.getByTestId('experience-activation-toggle')).toBeDisabled();
      await page.getByTestId('experience-activation-unknown').getByRole('button').click();
      await expect(page.getByTestId('experience-activation-toggle')).toBeEnabled();
    });
  }

  for (const status of [403, 500] as const) {
    test(`a read that fails with ${status} locks the setting instead of showing "off"`, async ({ page }) => {
      await install(page, {
        workspaces: (route) => json(route, [workspace()]),
        activation: (route) => json(route, { detail: 'nope' }, status),
      });
      await page.goto('/workspace/procedures-lot4/settings');
      await expect(page.getByTestId('experience-activation-read-error')).toBeVisible();
      await expect(page.getByTestId('experience-activation-state')).toHaveCount(0);
      await expect(page.getByTestId('experience-activation-toggle')).toHaveCount(0);
    });
  }
});
