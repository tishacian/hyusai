import { Page, expect } from '@playwright/test';

/**
 * Helpers for driving the Keycloak login flow from a Playwright test.
 *
 * Keycloak rendering is theme-sensitive (the realm uses the custom
 * "agentium" theme since rafale post-D7) so selectors target the
 * **semantic** attributes (`input#username`, `input#password`, the
 * submit button's type=submit) rather than CSS classes which change
 * with every theme tweak.
 */

export const DEFAULT_ALICE = {
  username: process.env['E2E_USERNAME'] ?? 'alice@acme.test',
  password: process.env['E2E_PASSWORD'] ?? 'alice-demo',
};

export const DEFAULT_WORKSPACE_SLUG = process.env['E2E_WORKSPACE_SLUG'] ?? 'acme';

export async function loginAsAlice(page: Page): Promise<void> {
  await page.goto('/auth/signin');
  const login = await page.evaluate(async ({ username, password, workspaceSlug }) => {
    const res = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: username,
        password,
        remember_me: false,
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok || !body.token) {
      return { ok: false, status: res.status, body };
    }
    localStorage.setItem('agentium_token', `Bearer ${body.token}`);
    if (body.refresh_token) {
      localStorage.setItem('agentium_refresh_token', body.refresh_token);
    }
    localStorage.setItem('agentium_workspace_slug', workspaceSlug);
    return { ok: true, status: res.status };
  }, { ...DEFAULT_ALICE, workspaceSlug: DEFAULT_WORKSPACE_SLUG });
  expect(login.ok, `login failed: ${JSON.stringify(login)}`).toBe(true);

  await page.goto('/chat?mode=quick');

  await expect(page.locator('body')).toContainText(/Ask|Chat|Demander/, {
    timeout: 15_000,
  });
}

export async function expectInvalidLogin(page: Page): Promise<void> {
  await page.goto('/auth/signin');
  const login = await page.evaluate(async ({ username }) => {
    const res = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: username,
        password: 'not-the-password',
        remember_me: false,
      }),
    });
    return { status: res.status };
  }, DEFAULT_ALICE);
  expect(login.status).toBe(401);
}

export async function logout(page: Page): Promise<void> {
  await page.goto('/account');
  const logoutButton = page.getByRole('button', { name: /logout|sign out/i });
  if (await logoutButton.isVisible().catch(() => false)) {
    await logoutButton.click();
    await page.waitForURL(/realms|auth/, { timeout: 20_000 });
  }
}
