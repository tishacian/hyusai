import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';

/**
 * Lot 2a — the shared state contract, on its first screen (evaluation preset).
 *
 * Opt-in, with no backend:
 *
 *   E2E_CHROME_V2_MOCKED=1 E2E_BASE_URL=http://127.0.0.1:4238
 *   npx playwright test e2e/tests/80-state-contract-mocked.spec.ts --trace=off
 *
 * The read replays the seven answers of the definition of done (200 with
 * data, 200 empty, 403, 500, 504, timed out, failed) and checks the state
 * shown by `data-testid`: only an empty 200 shows the empty state, and no
 * threshold is ever shown or sent that the server did not return. The write
 * checks that nothing reads as saved before the server confirms it.
 */

const enabled = process.env['E2E_CHROME_V2_MOCKED'] === '1';

test.use({ serviceWorkers: 'block', video: 'off', viewport: { width: 1440, height: 900 } });

const WORKSPACE = {
  id: 'ws-l2a',
  name: 'Lot 2a',
  slug: 'lot-2a',
  role: 'admin',
  role_template: 'workspace_admin',
  settings: { features: {} },
};

const USER = {
  id: 'user-l2a',
  email: 'grace@example.test',
  role: 'admin',
  is_active: true,
  mfa_enabled: false,
  first_name: 'Grace',
  last_name: 'Hopper',
  workspaces: [WORKSPACE],
};

const STORED = { enabled: true, composite_min: 65, hallucination_max: 0.2, sample_rate: 1, dimension_min: {} };
const PRESET = { defaults: STORED, workspace: { id: 'p1', name: 'default', config: STORED }, effective: STORED };

type Answer =
  | { status: number; body?: unknown }
  | { abort: 'timedout' | 'failed' };

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

function answer(route: Route, value: Answer): Promise<void> {
  if ('abort' in value) return route.abort(value.abort);
  return json(route, value.body ?? { detail: 'mocked' }, value.status);
}

async function install(page: Page, reads: Answer[], writes: Answer[] = []): Promise<{ puts: () => number }> {
  const baseURL = test.info().project.use.baseURL;
  if (!baseURL || !['localhost', '127.0.0.1'].includes(new URL(baseURL).hostname)) {
    throw new Error('State contract fixtures require a loopback E2E_BASE_URL');
  }
  let puts = 0;
  await page.route('**/*', (route) => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname)
    ? route.fallback() : route.abort('blockedbyclient'));
  await page.addInitScript(({ slug }) => {
    localStorage.setItem('agentium_token', 'Bearer mocked-l2a');
    localStorage.setItem('agentium_workspace_slug', slug);
    // The accessibility matrix switches language between visits; keep its choice.
    if (!localStorage.getItem('agentium_locale')) localStorage.setItem('agentium_locale', 'fr');
  }, { slug: WORKSPACE.slug });
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const apiPath = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    const method = request.method();
    if (apiPath === '/auth/validate' && method === 'POST') {
      return json(route, { valid: true, user_id: USER.id, email: USER.email, role: USER.role });
    }
    if (apiPath === '/auth/workspaces') return json(route, [WORKSPACE]);
    if (apiPath === `/auth/workspaces/${WORKSPACE.slug}`) return json(route, WORKSPACE);
    if (apiPath === '/auth/me') return json(route, USER);
    if (apiPath === '/help-content') return json(route, { version: 'local', personas: [], languages: [], items: [] });
    if (apiPath === '/evaluation/presets' && method === 'GET') {
      return answer(route, reads.length > 1 ? reads.shift()! : reads[0]);
    }
    if (apiPath === '/evaluation/presets' && method === 'PUT') {
      puts += 1;
      return answer(route, writes.length > 1 ? writes.shift()! : writes[0]);
    }
    if (method === 'GET') {
      if (apiPath.endsWith('s') || apiPath.includes('items')) return json(route, []);
      return json(route, {});
    }
    return json(route, { ok: true });
  });
  return { puts: () => puts };
}

async function expectNoInventedThresholds(page: Page): Promise<void> {
  const screen = page.locator('app-evaluation-preset');
  await expect(screen).not.toContainText('70 / 100');
  await expect(screen).not.toContainText('30%');
  await expect(page.getByTestId('preset-save')).toHaveCount(0);
}

test.describe('Lot 2a — shared state contract on the evaluation preset', () => {
  test.skip(!enabled, 'Set E2E_CHROME_V2_MOCKED=1 to run the mocked state contract');

  test('200 with data shows the stored thresholds and no state block', async ({ page }) => {
    await install(page, [{ status: 200, body: PRESET }]);
    await page.goto('/presets/evaluation');
    await expect(page.locator('app-evaluation-preset')).toContainText('65 / 100');
    await expect(page.locator('[data-testid^="load-state-"]')).toHaveCount(0);
    await expect(page.getByTestId('preset-synced')).toBeVisible();
  });

  test('only an empty 200 shows the empty state', async ({ page }) => {
    await install(page, [{ status: 200, body: {} }]);
    await page.goto('/presets/evaluation');
    await expect(page.getByTestId('load-state-empty')).toBeVisible();
    await expectNoInventedThresholds(page);
  });

  test('403 says access denied, without Retry', async ({ page }) => {
    await install(page, [{ status: 403, body: { detail: 'Forbidden' } }]);
    await page.goto('/presets/evaluation');
    await expect(page.getByTestId('load-state-denied')).toContainText('Accès refusé');
    await expect(page.getByTestId('load-state-retry')).toHaveCount(0);
    await expectNoInventedThresholds(page);
  });

  const failures: Array<[string, Answer]> = [
    ['500', { status: 500 }],
    ['504', { status: 504 }],
    ['timed out', { abort: 'timedout' }],
    ['failed', { abort: 'failed' }],
  ];
  for (const [label, failure] of failures) {
    test(`a ${label} read says it failed and offers Retry, never an empty or default form`, async ({ page }) => {
      const { puts } = await install(page, [failure, { status: 200, body: PRESET }]);
      await page.goto('/presets/evaluation');
      const state = page.getByTestId('load-state-error');
      await expect(state).toContainText('Lecture impossible');
      await expect(page.getByTestId('load-state-empty')).toHaveCount(0);
      await expectNoInventedThresholds(page);
      await page.getByTestId('load-state-retry').click();
      await expect(page.locator('app-evaluation-preset')).toContainText('65 / 100');
      expect(puts()).toBe(0);
    });
  }

  test('a refused save stays unsaved and says why', async ({ page }) => {
    await install(page, [{ status: 200, body: PRESET }], [{ status: 409, body: { detail: { code: 'conflict' } } }]);
    await page.goto('/presets/evaluation');
    await page.locator('app-evaluation-preset input[type="checkbox"]').uncheck();
    await page.getByTestId('preset-save').click();
    await expect(page.getByTestId('write-outcome-failed')).toContainText('ne sont pas enregistrés');
    await expect(page.getByTestId('preset-unsaved')).toBeVisible();
    await expect(page.getByTestId('preset-synced')).toHaveCount(0);
  });

  test('a 500 on save stays unsaved', async ({ page }) => {
    await install(page, [{ status: 200, body: PRESET }], [{ status: 500 }]);
    await page.goto('/presets/evaluation');
    await page.locator('app-evaluation-preset input[type="checkbox"]').uncheck();
    await page.getByTestId('preset-save').click();
    await expect(page.getByTestId('write-outcome-failed')).toBeVisible();
    await expect(page.getByTestId('preset-unsaved')).toBeVisible();
  });

  test('a lost answer is unknown: Check reads back instead of sending again', async ({ page }) => {
    const saved = { ...STORED, enabled: false };
    const { puts } = await install(
      page,
      [{ status: 200, body: PRESET }, { status: 200, body: { ...PRESET, effective: saved } }],
      [{ abort: 'timedout' }],
    );
    await page.goto('/presets/evaluation');
    await page.locator('app-evaluation-preset input[type="checkbox"]').uncheck();
    await page.getByTestId('preset-save').click();
    await expect(page.getByTestId('write-outcome-unknown')).toContainText('Résultat inconnu');
    await expect(page.getByTestId('preset-save')).toBeDisabled();
    await page.getByTestId('write-outcome-verify').click();
    await expect(page.getByTestId('write-outcome-confirmed')).toBeVisible();
    await expect(page.getByTestId('preset-synced')).toBeVisible();
    expect(puts()).toBe(1);
  });

  test('a confirmed save says so only after the server answered', async ({ page }) => {
    const saved = { ...STORED, enabled: false };
    await install(page, [{ status: 200, body: PRESET }], [{ status: 200, body: { id: 'p1', name: 'default', config: saved, updated_at: null } }]);
    await page.goto('/presets/evaluation');
    await page.locator('app-evaluation-preset input[type="checkbox"]').uncheck();
    await page.getByTestId('preset-save').click();
    await expect(page.getByTestId('write-outcome-confirmed')).toContainText('Seuils enregistrés');
    await expect(page.getByTestId('preset-synced')).toBeVisible();
    const results = await new AxeBuilder({ page })
      .include('app-evaluation-preset')
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
      .analyze();
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
    expect(serious, serious.map((v) => v.id).join(', ')).toEqual([]);
  });

  // The shared matrix (`runAccessibilityMatrix`) also scans the app shell, whose
  // status bar has its own finding; this screen is checked on its own here.
  for (const [label, reads, ready] of [
    ['the stored thresholds', [{ status: 200, body: PRESET }], 'preset-save'],
    ['a failed read', [{ status: 500 }], 'load-state-error'],
  ] as Array<[string, Answer[], string]>) {
    test(`${label} pass WCAG AA in both themes, both languages, and reflow at 320 px`, async ({ page }) => {
      test.setTimeout(120_000);
      await install(page, reads);
      await page.emulateMedia({ reducedMotion: 'reduce' });
      const failures: string[] = [];
      for (const locale of ['fr', 'en'] as const) {
        for (const theme of ['light', 'dark'] as const) {
          for (const width of [1440, 456, 320]) {
            await page.setViewportSize({ width, height: 720 });
            await page.addInitScript(({ locale, theme }) => {
              localStorage.setItem('agentium_locale', locale);
              localStorage.setItem('agentium_theme', theme);
            }, { locale, theme });
            await page.goto('/presets/evaluation');
            await expect(page.getByTestId(ready)).toBeVisible();
            const tag = `${locale}-${theme}-${width}`;
            const overflow = await page.locator('app-evaluation-preset').evaluate((root) => {
              const box = root.getBoundingClientRect();
              const clipped = [...root.querySelectorAll<HTMLElement>('button, a, input, label, h1, h3, p')]
                .filter((el) => el.getBoundingClientRect().right > box.right + 1)
                .map((el) => el.outerHTML.slice(0, 60));
              return clipped;
            });
            for (const el of overflow) failures.push(`${tag}: overflows ${el}`);
            const axe = await new AxeBuilder({ page })
              .include('app-evaluation-preset')
              .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
              .analyze();
            for (const v of axe.violations) failures.push(`${tag}: axe ${v.id} (${v.impact}) on ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`);
          }
        }
      }
      expect(failures).toEqual([]);
    });
  }
});
