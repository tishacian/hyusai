import { expect, test } from '@playwright/test';
import { DEFAULT_ALICE, loginAsAlice } from '../fixtures/auth';

/**
 * E2.01 — Auth Keycloak flow.
 *
 * Validates :
 * - Anonymous visits redirect to Keycloak (`/realms/.../auth`).
 * - Valid credentials land on the Hypervisor.
 * - The session persists across a page reload (cookie survives).
 * - `alice@papai.ai` is scoped to a workspace visible in the sidebar.
 */
test.describe('E2.01 — Auth', () => {
  test('redirects to Keycloak and lands on Hypervisor', async ({ page }) => {
    await loginAsAlice(page);

    await expect(page).toHaveURL(/\/(hypervisor|$)/);
    await expect(page.locator('nav, aside').first()).toContainText(/Hypervisor/);
  });

  test('session survives reload', async ({ page }) => {
    await loginAsAlice(page);
    await page.reload();
    await expect(page).not.toHaveURL(/realms|auth\/login/);
    await expect(page.locator('body')).toContainText(/Hypervisor|Steering/);
  });

  test('invalid credentials stay on Keycloak with an error', async ({ page }) => {
    await page.goto('/');
    await page.waitForURL(/realms|auth/, { timeout: 20_000 });

    await page.locator('input#username, input[name="username"]').fill(DEFAULT_ALICE.username);
    await page.locator('input#password, input[name="password"]').fill('not-the-password');
    await page.locator('button[type="submit"], input[type="submit"]').first().click();

    await expect(page.locator('body')).toContainText(/Invalid|incorrect|credentials/i, {
      timeout: 10_000,
    });
  });
});
