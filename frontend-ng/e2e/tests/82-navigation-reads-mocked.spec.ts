import { expect, test, type Page, type Route } from '@playwright/test';

const workspace = { id: 'ws-nav', slug: 'navigation-reads', name: 'Navigation', role: 'admin', role_template: 'workspace_admin', settings: { features: { experience_v1: true } } };
const user = { id: 'reader', email: 'reader@example.com', is_active: true, role: 'admin', first_name: 'Reader', workspaces: [workspace] };
const app = { experience: { id: 'invoice-app', slug: 'invoice-app', name: 'Invoice validation', pattern: 'queue' }, channel: 'live', release: { id: 'release-1', identity_snapshot: { name: 'Invoice validation' } } };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

async function install(page: Page, locale: 'fr' | 'en', authenticated = true) {
  if (!['localhost', '127.0.0.1'].includes(new URL(String(test.info().project.use.baseURL)).hostname)) throw new Error('Local fixtures only');
  let sessionsFail = true;
  let recoveryFail = true;
  let paletteFail = true;
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort('blockedbyclient'));
  await page.addInitScript(({ locale, slug, authenticated }) => {
    if (authenticated) localStorage.setItem('agentium_token', 'Bearer mocked-navigation');
    else localStorage.removeItem('agentium_token');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_locale', locale);
  }, { locale, slug: workspace.slug, authenticated });
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/auth/validate') return authenticated ? json(route, { valid: true, user_id: user.id, email: user.email, role: user.role }) : json(route, { valid: false }, 401);
    if (path === '/auth/me') return authenticated ? json(route, user) : json(route, { detail: 'Unauthenticated' }, 401); // MFA is intentionally unknown, not false.
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === `/auth/workspaces/${workspace.slug}`) return json(route, workspace);
    if (path === '/auth/sessions') return json(route, sessionsFail ? { detail: { code: 'sessions_unavailable' } } : [], sessionsFail ? 502 : 200);
    if (path === '/auth/password-reset') return json(route, recoveryFail ? { detail: { code: 'password_reset_unavailable' } } : { message: 'If the account exists, instructions have been sent.' }, recoveryFail ? 502 : 200);
    if (path === '/work') return json(route, { experiences: [app] });
    if (path === '/navigation/search') return json(route, { results: [], has_more: false });
    if (path === '/systems') return json(route, paletteFail ? { detail: 'unavailable' } : [], paletteFail ? 500 : 200);
    if (path === '/help-content') return json(route, { version: 'local', personas: [], languages: [], items: [] });
    return json(route, path.endsWith('s') ? [] : {});
  });
  return { recoverSessions: () => { sessionsFail = false; }, recoverPassword: () => { recoveryFail = false; }, recoverPalette: () => { paletteFail = false; } };
}

for (const locale of ['fr', 'en'] as const) {
  test(`MFA unknown cannot be changed and sessions failure can be retried (${locale})`, async ({ page }) => {
    const fixtures = await install(page, locale);
    await page.goto('/account/security');
    const security = page.locator('app-account-security');
    await expect(security.getByTestId('mfa-unknown')).toBeVisible();
    await expect(security.getByRole('button')).toHaveCount(1); // Retry only.
    await page.goto('/account/sessions');
    const sessions = page.locator('app-account-sessions');
    await expect(sessions.getByTestId('load-state-error')).toBeVisible();
    await expect(sessions.getByTestId('load-state-empty')).toHaveCount(0);
    fixtures.recoverSessions();
    await sessions.getByTestId('load-state-retry').click();
    await expect(sessions.getByTestId('load-state-empty')).toBeVisible();
  });

  test(`password recovery never claims success after an unavailable server (${locale})`, async ({ page }) => {
    const fixtures = await install(page, locale, false);
    await page.goto('/auth/password-reset');
    await page.locator('input[type=email]').fill('reader@example.com');
    await page.locator('button[type=submit]').click();
    await expect(page.getByTestId('load-state-error')).toBeVisible();
    fixtures.recoverPassword();
    await page.getByTestId('load-state-retry').click();
    await expect(page.getByTestId('load-state-error')).toHaveCount(0);
    await expect(page.locator('input[type=email]')).toHaveCount(0);
  });

  test(`palette distinguishes failures and filtered applications, and restores keyboard focus (${locale})`, async ({ page }) => {
    const fixtures = await install(page, locale);
    await page.goto('/account/sessions');
    const opener = page.locator('app-account-sessions button').first();
    await opener.focus();
    await page.keyboard.press('Control+k');
    const palette = page.locator('app-command-palette');
    await expect(palette.getByTestId('load-state-error')).toBeVisible();
    fixtures.recoverPalette();
    await palette.getByTestId('load-state-retry').click();
    await expect(palette.getByTestId('load-state-error')).toHaveCount(0);
    const input = palette.locator('input[type=search]');
    await input.fill('Invoice validation');
    await expect(palette.locator('[role=option][data-kind=application]')).toContainText('Invoice validation');
    await expect(palette.locator('[role=option][data-kind=application]')).toContainText('Navigation');
    await palette.locator('select').selectOption('system');
    await expect(palette.getByTestId('palette-filtered-out')).toContainText(locale === 'fr' ? 'filtre' : 'filter');
    await expect(palette.locator('[role=status][aria-atomic=true]')).toContainText(locale === 'fr' ? 'filtre' : 'filter');
    await page.keyboard.press('Escape');
    await expect(palette.getByRole('dialog')).toHaveCount(0);
    await expect(opener).toBeFocused();
  });
}
