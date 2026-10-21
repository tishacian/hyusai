import { expect, test, type Page, type Route } from '@playwright/test';

/**
 * Lot 2a — human decisions and member roles, fully mocked.
 *
 *   E2E_CHROME_V2_MOCKED=1 E2E_BASE_URL=http://127.0.0.1:4252
 *   npx playwright test e2e/tests/81-decisions-and-roles-mocked.spec.ts --trace=off
 *
 * A decision answered 500, 403, 504 or lost on the network shows its real
 * outcome, never "refused"; a lost one locks the buttons until it is checked;
 * a double click sends one decision; a reader without `run.approve` sees
 * "Read only" before any button. A role change sends nothing from the
 * select, names the person and both roles, and a concurrent change (409)
 * overwrites nothing.
 */

const enabled = process.env['E2E_CHROME_V2_MOCKED'] === '1';
test.use({ serviceWorkers: 'block', video: 'off', viewport: { width: 1440, height: 900 } });

const WORKSPACE = { id: 'ws-decide', slug: 'decide', name: 'Decide', role: 'admin', role_template: 'workspace_admin', settings: { features: { experience_v1: true } } };
const USER = { id: 'user-admin', email: 'grace@example.test', role: 'user', is_active: true, first_name: 'Grace', last_name: 'Hopper', workspaces: [WORKSPACE] };
const RUN_ID = 'run-decide', DECISION_ID = 'decision-decide', APP = 'approvals';

type Answer = { status: number; body?: unknown } | { abort: 'failed' | 'timedout' };

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

function pausedRun(hitl: Record<string, unknown> = {}) {
  return {
    id: RUN_ID, system_id: 'sys-decide', status: 'hitl_pending', flow_sha256: 'a'.repeat(64), input_ref: {}, output_ref: {},
    skill_invocations: [], checkpoints: [],
    hitl: { node_id: 'approve', prompt: 'Send the summary to the supplier?', decision_id: DECISION_ID, decision_status: 'proposed', can_decide: true, ...hitl },
  };
}

async function boot(page: Page, routes: (path: string, method: string, route: Route) => Promise<void> | void | false): Promise<void> {
  const baseURL = test.info().project.use.baseURL;
  if (!baseURL || !['localhost', '127.0.0.1'].includes(new URL(baseURL).hostname)) throw new Error('Mocked fixtures require a loopback E2E_BASE_URL');
  await page.route('**/*', (route) => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort('blockedbyclient'));
  await page.addInitScript(({ slug }) => {
    localStorage.setItem('agentium_token', 'Bearer mocked-decide');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_locale', 'en');
  }, { slug: WORKSPACE.slug });
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    const method = request.method();
    if (path === '/auth/validate') return json(route, { valid: true, user_id: USER.id, email: USER.email, role: USER.role });
    if (path === '/auth/me') return json(route, USER);
    if (path === '/auth/workspaces') return json(route, [WORKSPACE]);
    if (path === `/auth/workspaces/${WORKSPACE.slug}`) return json(route, WORKSPACE);
    if (path === '/help-content') return json(route, { version: 'local', personas: [], languages: [], items: [] });
    // A route handler returns false when it did not answer.
    if (await routes(path, method, route) !== false) return;
    if (route.request().method() === 'GET') return json(route, path.endsWith('s') ? [] : {});
    return json(route, { ok: true });
  });
}

async function openDecision(page: Page, options: { hitl?: Record<string, unknown>; answers?: Answer[] } = {}) {
  const posts: unknown[] = [];
  let waiting = true;
  await boot(page, async (path, method, route) => {
    if (path === `/work/${APP}`) {
      await json(route, { experience: { id: 'exp-approvals', slug: APP, name: 'Approvals', pattern: 'approval', languages: ['fr', 'en'] }, channel: 'live',
        release: { id: 'release', release_number: 1, renderer_version: 'certified-components-0.2.0', bindings_snapshot: [{ system_id: 'sys-decide' }], pages: { pages: [{ id: 'home', title: 'Approvals', components: [] }] }, languages: ['fr', 'en'] } });
      return;
    }
    if (path === `/work/${APP}/validations`) { await json(route, { runs: waiting ? [pausedRun(options.hitl)] : [] }); return; }
    if (path === `/runs/${RUN_ID}` && method === 'GET') { await json(route, waiting ? pausedRun(options.hitl) : { ...pausedRun(), status: 'completed', hitl: undefined }); return; }
    if (path === `/runs/${RUN_ID}/hitl` && method === 'POST') {
      posts.push(route.request().postDataJSON());
      const answer = options.answers?.shift() ?? { status: 200, body: { ...pausedRun(), status: 'running' } };
      if ('abort' in answer) { await route.abort(answer.abort); return; }
      if (answer.status === 200) waiting = false;
      await json(route, answer.body ?? { detail: 'mocked' }, answer.status);
      return;
    }
    return false;
  });
  await page.goto(`/work/${APP}/validations`);
  await page.getByRole('button', { name: 'Review request', exact: true }).click();
  return { posts, approve: page.locator('.xp-work-hitl-actions button').first() };
}

test.describe('Lot 2a — human decisions', () => {
  test.skip(!enabled, 'Set E2E_CHROME_V2_MOCKED=1 to run the mocked decisions');

  const cases: Array<[string, Answer, RegExp, boolean]> = [
    ['500', { status: 500 }, /server answered with an error \(500\)/, false],
    ['403', { status: 403, body: { detail: 'Forbidden' } }, /your role does not let you decide/, false],
    ['504', { status: 504 }, /Result unknown/, true],
    ['a network cut', { abort: 'failed' }, /Result unknown/, true],
  ];
  for (const [label, answer, text, locked] of cases) {
    test(`a decision answered with ${label} shows its real outcome, never a refusal`, async ({ page }) => {
      const { posts, approve } = await openDecision(page, { answers: [answer] });
      await approve.click();
      const notice = page.getByTestId('work-decision-notice');
      await expect(notice).toContainText(text);
      await expect(page.locator('body')).not.toContainText(/refused by the server/i);
      if (locked) {
        await expect(approve).toBeDisabled();
        await expect(page.getByTestId('work-decision-verify')).toBeVisible();
      } else {
        await expect(approve).toBeEnabled();
      }
      expect(posts).toHaveLength(1);
    });
  }

  test('a lost answer is checked before deciding again, and the check reopens the decision', async ({ page }) => {
    const { posts, approve } = await openDecision(page, { answers: [{ abort: 'failed' }] });
    await approve.click();
    await expect(approve).toBeDisabled();
    await page.getByTestId('work-decision-verify').click();
    await expect(page.getByTestId('work-decision-notice')).toContainText('no decision is recorded');
    await expect(approve).toBeEnabled();
    await approve.click();
    await expect(page.getByTestId('work-decision-receipt')).toContainText('Decision recorded: accepted');
    expect(posts).toHaveLength(2);
  });

  test('a double click sends one decision', async ({ page }) => {
    const { posts, approve } = await openDecision(page);
    await approve.dblclick();
    await expect(page.getByTestId('work-decision-receipt')).toBeVisible();
    expect(posts).toHaveLength(1);
  });

  test('a reader without the right to approve sees "Read only" and why before any button', async ({ page }) => {
    const { posts } = await openDecision(page, { hitl: { can_decide: false, decide_reason: 'not_authorized' } });
    const notice = page.getByTestId('decision-read-only');
    await expect(notice).toContainText('Read only');
    await expect(notice).toContainText('Access to the application is not enough');
    await expect(page.locator('.xp-work-hitl-actions')).toHaveCount(0);
    expect(posts).toHaveLength(0);
  });
});

test.describe('Lot 2a — member roles', () => {
  test.skip(!enabled, 'Set E2E_CHROME_V2_MOCKED=1 to run the mocked member roles');

  const member = (role_template: string) => ({ user_id: 'user-ada', username: 'ada', email: 'ada@example.test', role: 'member', role_template, joined_at: '2026-10-01T10:00:00', is_current_user: false, app_entitlements: [] });
  const me = { user_id: USER.id, username: 'grace', email: USER.email, role: 'admin', role_template: 'workspace_admin', joined_at: '2026-01-01T10:00:00', is_current_user: true, app_entitlements: [] };

  async function openMembers(page: Page, patch: Answer, after: string) {
    const patches: unknown[] = [];
    let role = 'workspace_contributor';
    await boot(page, async (path, method, route) => {
      if (path === `/auth/workspaces/${WORKSPACE.slug}/members` && method === 'GET') { await json(route, [me, member(role)]); return; }
      if (path === `/auth/workspaces/${WORKSPACE.slug}/members/user-ada` && method === 'PATCH') {
        patches.push(route.request().postDataJSON());
        if ('abort' in patch) { await route.abort(patch.abort); return; }
        role = after;
        await json(route, patch.body ?? { status: 'ok' }, patch.status);
        return;
      }
      return false;
    });
    await page.goto(`/workspace/${WORKSPACE.slug}/members`);
    return { patches, select: page.getByTestId('workspace-member-role-template') };
  }

  test('the select sends nothing; the confirmation names the person and both roles; the role shown is read back', async ({ page }) => {
    const { patches, select } = await openMembers(page, { status: 200 }, 'workspace_reviewer');
    await select.selectOption('workspace_reviewer');
    await expect(page.getByRole('alertdialog')).toContainText('ada@example.test will go from Contributor to Reviewer');
    expect(patches).toHaveLength(0);
    await expect(select).toHaveValue('workspace_contributor');
    await page.getByRole('alertdialog').getByRole('button', { name: 'Change the role' }).click();
    await expect.poll(() => patches).toEqual([{ role_template: 'workspace_reviewer', expected_role_template: 'workspace_contributor' }]);
    await expect(select).toHaveValue('workspace_reviewer');
  });

  test('a concurrent change answers 409 and overwrites nothing', async ({ page }) => {
    const { patches, select } = await openMembers(page, { status: 409, body: { detail: { code: 'member_role_changed', current_role_template: 'workspace_admin' } } }, 'workspace_admin');
    await select.selectOption('workspace_reviewer');
    await page.getByRole('alertdialog').getByRole('button', { name: 'Change the role' }).click();
    await expect(page.getByText(/changed in the meantime: nothing was overwritten/)).toBeVisible();
    await expect(select).toHaveValue('workspace_admin');
    expect(patches).toHaveLength(1);
  });

  test('a failed member list is never shown as "no members"', async ({ page }) => {
    await boot(page, async (path, method, route) => {
      if (path === `/auth/workspaces/${WORKSPACE.slug}/members` && method === 'GET') { await json(route, { detail: 'boom' }, 500); return; }
      return false;
    });
    let reads = 0;
    page.on('request', (r) => { if (r.url().endsWith(`/auth/workspaces/${WORKSPACE.slug}/members`)) reads += 1; });
    await page.goto(`/workspace/${WORKSPACE.slug}/members`);
    await expect(page.getByTestId('load-state-error')).toContainText('Could not load');
    await expect(page.getByText(/no members|Aucun membre/i)).toHaveCount(0);
  });
});
