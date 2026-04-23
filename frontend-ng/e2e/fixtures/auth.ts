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
  username: process.env['E2E_USERNAME'] ?? 'alice@papai.ai',
  password: process.env['E2E_PASSWORD'] ?? 'Agentium2026!',
};

export async function loginAsAlice(page: Page): Promise<void> {
  await page.goto('/');

  // Auth guard redirects to Keycloak when no session cookie is set.
  await page.waitForURL(/\/realms\/.+\/protocol\/openid-connect\/auth/, {
    timeout: 20_000,
  });

  await page.locator('input#username, input[name="username"]').fill(DEFAULT_ALICE.username);
  await page.locator('input#password, input[name="password"]').fill(DEFAULT_ALICE.password);
  await page.locator('button[type="submit"], input[type="submit"]').first().click();

  // Back on the app domain after the OIDC round-trip.
  await page.waitForURL(/agentium\.papai\.ai|localhost/, { timeout: 30_000 });

  await expect(page.locator('body')).toContainText(/Hypervisor|Steering|Chat/, {
    timeout: 15_000,
  });
}

export async function logout(page: Page): Promise<void> {
  await page.goto('/account');
  const logoutButton = page.getByRole('button', { name: /logout|sign out/i });
  if (await logoutButton.isVisible().catch(() => false)) {
    await logoutButton.click();
    await page.waitForURL(/realms|auth/, { timeout: 20_000 });
  }
}
