import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';

/**
 * Plan lot 4 — the Studio editor offers only what the bound version exposes
 * (US33), previews a page on one identified test result (US34) and ends a
 * deployment on a receipt (US35). Fully mocked, loopback only:
 *
 *   E2E_CHROME_V2_MOCKED=1 E2E_BASE_URL=http://127.0.0.1:4341 \
 *   npx playwright test e2e/tests/75-studio-contract-receipt-mocked.spec.ts --trace=off
 */

const enabled = process.env['E2E_CHROME_V2_MOCKED'] === '1';
const SHOT_DIR = process.env['E2E_SHOT_DIR'] ?? 'test-results/lot4-studio-shots';

test.use({ serviceWorkers: 'block', video: 'off', viewport: { width: 1600, height: 1000 } });

const WORKSPACE = {
  id: 'ws-studio', slug: 'studio-lot4', name: 'Procédures', role: 'owner', role_template: 'workspace_owner',
  settings: { features: { experience_v1: true } },
};
const BINDING = {
  binding_key: 'procedures.ask', system_id: 'sys-proc', published_flow_version_id: 'version-2-abcdef',
  ingress_id: 'ask', confirmation_policy: 'confirm', on_unavailable: 'unavailable',
};
const PAGES = {
  pages: [{
    id: 'home', title: 'Accueil', components: [
      { type: 'form', id: 'ask', props: { title: 'Question', bindingKey: 'procedures.ask', schema: { type: 'object', properties: { question: { type: 'string', title: 'Question' } } } } },
      { type: 'text', id: 'answer', props: { dataBinding: { source: 'run-output', componentId: 'ask', selector: 'answer' } } },
      { type: 'table', id: 'sources', props: { dataBinding: { source: 'run-output', componentId: 'ask', selector: 'old_sources' } } },
    ],
  }],
};
const EXPERIENCE = {
  id: 'exp-1', slug: 'procedures', name: 'Assistant procédures', pattern: 'form_result', languages: ['fr', 'en'],
  theme: {}, access_policy: { roles: ['workspace_viewer'], groups: [] }, created_by: 'ada', updated_at: '2026-10-20T10:00:00',
};
const RUN = {
  id: 'run-test-123456', system_id: 'sys-proc', status: 'hitl_pending', started_at: '2026-10-20T09:00:00',
  execution_surface: 'published_manual', flow_version_id: 'version-2-abcdef',
  output_ref: { answer: 'Remplir le formulaire B puis le faire signer.', citations: [{ doc: 'procedure.pdf' }] },
  invocations: [],
};

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

interface Options { runs?: (route: Route) => Promise<void>; deploy?: (route: Route) => Promise<void> }

async function install(page: Page, options: Options = {}, locale: 'fr' | 'en' = 'fr'): Promise<string[]> {
  const baseURL = test.info().project.use.baseURL;
  if (!baseURL || !['localhost', '127.0.0.1'].includes(new URL(baseURL).hostname)) {
    throw new Error('Lot 4 studio fixtures require a loopback E2E_BASE_URL');
  }
  const writes: string[] = [];
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
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, '');
    const method = request.method();
    if (method !== 'GET' && path.startsWith('/experiences')) writes.push(`${method} ${path}`);
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'u', email: 'ada@example.test', role: 'admin' });
    if (path === '/auth/me') return json(route, { id: 'u', email: 'ada@example.test', workspaces: [WORKSPACE] });
    if (path === '/auth/workspaces') return json(route, [WORKSPACE]);
    if (path === `/auth/workspaces/${WORKSPACE.slug}`) return json(route, WORKSPACE);
    if (path === '/experiences/exp-1') {
      return json(route, { ...EXPERIENCE, draft: { pages: PAGES, binding_keys: ['procedures.ask'], revision: 4, content_sha256: 'a'.repeat(64) }, deployments: [] });
    }
    if (path === '/experiences/exp-1/ready-check') {
      return json(route, { ready: true, blockers: [], warnings: [], bindings_sha256: 'b'.repeat(64), bindings: [{ ...BINDING, flow_sha256: 'c'.repeat(64) }] });
    }
    if (path === '/experiences/exp-1/releases' && method === 'POST') {
      return json(route, { id: 'rel-3', experience_id: 'exp-1', release_number: 3, pages: PAGES, bindings_snapshot: [BINDING], access_snapshot: EXPERIENCE.access_policy, languages: ['fr', 'en'], theme: {}, notes: 'n', created_at: '2026-10-20T10:05:00' }, 201);
    }
    if (path === '/experiences/exp-1/releases') {
      return json(route, { releases: [{ id: 'rel-3', experience_id: 'exp-1', release_number: 3, pages: PAGES, bindings_snapshot: [BINDING], access_snapshot: EXPERIENCE.access_policy, languages: ['fr', 'en'], theme: {}, notes: 'n', created_at: '2026-10-20T10:05:00' }] });
    }
    if (path === '/experiences/exp-1/deployments' && method === 'POST') {
      if (options.deploy) return options.deploy(route);
      const body = request.postDataJSON() as Record<string, unknown>;
      return json(route, { id: 'dep-1', experience_id: 'exp-1', channel: body['channel'], release_id: body['release_id'], audience: body['audience'] ?? {}, updated_by: 'ada@example.test', updated_at: '2026-10-20T10:06:00' }, 201);
    }
    if (path === '/experiences/exp-1/draft/revisions') return json(route, { revisions: [] });
    if (path === '/experiences') return json(route, { experiences: [EXPERIENCE] });
    if (path === '/system-bindings') return json(route, { bindings: [BINDING] });
    if (path === '/system-bindings/drift') return json(route, { bindings: [] });
    if (path === '/systems') return json(route, [{ id: 'sys-proc', name: 'Procédures internes', status: 'active', published_flow_version_id: 'version-2-abcdef' }]);
    if (path === '/systems/sys-proc/ingresses') {
      return json(route, {
        system_id: 'sys-proc', published_flow_version_id: 'version-2-abcdef', flow_sha256: 'c'.repeat(64),
        output_schema: { type: 'object', properties: { answer: { type: 'string' }, citations: { type: 'array', items: { type: 'object' } } } },
        ingresses: [{ ingress_id: 'ask', kind: 'manual', input_schema: { type: 'object', properties: { question: { type: 'string', title: 'Question' } } } }],
      });
    }
    if (path === '/runs' && url.searchParams.get('system_id') === 'sys-proc') {
      return options.runs ? options.runs(route) : json(route, [RUN]);
    }
    if (path === `/runs/${RUN.id}`) return json(route, RUN);
    if (path === '/help-content') return json(route, { version: 'local', personas: [], languages: [], items: [] });
    if (method === 'GET') return json(route, path.endsWith('s') ? [] : {});
    return json(route, { ok: true });
  });
  return writes;
}

test.describe('Lot 4 — Studio contract, test preview and receipt', () => {
  test.skip(!enabled, 'Set E2E_CHROME_V2_MOCKED=1 to run the mocked lot 4 checks');

  test('an action names its System, version and expected inputs', async ({ page }) => {
    await install(page);
    await page.goto('/create/apps/exp-1');
    await page.locator('.xp-tree button.is-child').nth(0).click();
    await page.getByRole('tab', { name: /^Action$/ }).click();
    const contract = page.getByTestId('action-contract');
    await expect(contract.getByTestId('action-contract-system')).toHaveText('Procédures internes');
    await expect(contract.getByTestId('action-contract-version')).toContainText('version publiée version-');
    await expect(contract.getByTestId('action-contract-inputs')).toContainText('Question');
  });

  test('a saved output the bound version does not expose is flagged, not offered', async ({ page }) => {
    await install(page);
    await page.goto('/create/apps/exp-1');
    await page.locator('.xp-tree button.is-child').nth(2).click();
    await page.getByRole('tab', { name: /^Action$/ }).click();
    await expect(page.getByTestId('data-selector-absent')).toContainText('old_sources');
    const absent = page.locator('option', { hasText: 'absente de la version liée' });
    await expect(absent).toHaveJSProperty('disabled', true);
  });

  test('the page is previewed on a named test result that is not presented as accepted', async ({ page }) => {
    await install(page);
    await page.goto('/create/apps/exp-1');
    const panel = page.getByTestId('test-preview');
    await panel.getByTestId('test-preview-run').selectOption(RUN.id);
    await expect(panel.getByTestId('test-preview-origin')).toContainText(RUN.id);
    await expect(panel.getByTestId('test-preview-standing')).toHaveAttribute('data-standing', 'review');
    await expect(panel.getByTestId('test-preview-review')).toBeVisible();
    await expect(panel.getByTestId('test-preview-check-answer')).toHaveAttribute('data-state', 'present');
    await expect(panel.getByTestId('test-preview-check-sources')).toHaveAttribute('data-state', 'missing');
    await page.screenshot({ path: `${SHOT_DIR}/test-preview.png`, fullPage: true });
    await panel.getByTestId('test-preview-check-sources').getByRole('button').click();
    await expect(page.getByTestId('data-selector-absent')).toBeVisible();
  });

  for (const failure of ['500', 'timedout'] as const) {
    test(`a failed run list (${failure}) is an error with Retry, not "no run"`, async ({ page }) => {
      let healthy = false;
      await install(page, {
        runs: (route) => healthy ? json(route, []) : failure === 'timedout' ? route.abort('timedout') : json(route, {}, 500),
      });
      await page.goto('/create/apps/exp-1');
      await expect(page.getByTestId('test-preview-runs-error')).toBeVisible();
      await expect(page.getByTestId('test-preview-no-run')).toHaveCount(0);
      healthy = true;
      await page.getByTestId('test-preview-runs-error').getByRole('button').click();
      await expect(page.getByTestId('test-preview-no-run')).toBeVisible();
    });
  }

  test('a pilot deployment ends on a receipt with Release, channel, audience and Open in Work', async ({ page }) => {
    const writes = await install(page, {}, 'en');
    await page.goto('/create/apps/exp-1');
    await page.getByRole('tab', { name: 'Journal' }).click();
    await page.locator('.xp-journal-row').filter({ hasText: 'R3' }).getByRole('button').click();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('radio', { name: /Pilot/ }).check();
    await dialog.getByRole('button', { name: 'Deploy', exact: true }).click();
    const receipt = dialog.getByTestId('deploy-receipt');
    await expect(receipt).toBeVisible();
    await expect(receipt.getByTestId('deploy-receipt-release')).toHaveText('Release 3');
    await expect(receipt.getByTestId('deploy-receipt-channel')).toHaveText('Pilot');
    await expect(receipt.getByTestId('deploy-receipt-audience')).toContainText('Viewer');
    await expect(receipt).toContainText('ada@example.test');
    await expect(receipt.getByTestId('deploy-receipt-open')).toHaveAttribute('href', '/work/procedures');
    const results = await new AxeBuilder({ page }).include('[data-testid="deploy-receipt"]').withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
    expect(results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => v.id)).toEqual([]);
    await page.screenshot({ path: `${SHOT_DIR}/deploy-receipt.png`, fullPage: true });
    expect(writes).toEqual(['POST /experiences/exp-1/deployments']);
  });

  test('a failed deployment shows no receipt', async ({ page }) => {
    await install(page, { deploy: (route) => json(route, { detail: { code: 'EXPERIENCE_DEPLOYMENT_CONFLICT' } }, 409) }, 'en');
    await page.goto('/create/apps/exp-1');
    await page.getByRole('tab', { name: 'Journal' }).click();
    await page.locator('.xp-journal-row').filter({ hasText: 'R3' }).getByRole('button').click();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('radio', { name: /Pilot/ }).check();
    await dialog.getByRole('button', { name: 'Deploy', exact: true }).click();
    await expect(dialog.locator('.xp-error')).toBeVisible();
    await expect(dialog.getByTestId('deploy-receipt')).toHaveCount(0);
  });
});
