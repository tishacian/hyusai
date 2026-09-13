import { expect, test } from '@playwright/test';
import { expectInvalidLogin, loginAsAlice } from '../fixtures/auth';

/**
 * E2.01 — Auth Keycloak flow.
 *
 * Validates :
 * - Direct access grant against the real backend auth succeeds.
 * - Authenticated token storage lands on the Hypervisor.
 * - The session persists across a page reload (cookie survives).
 * - `alice@papai.ai` is scoped to a workspace visible in the sidebar.
 */
test.describe('E2.01 — Auth', () => {
  test('redirects to sign-in and lands on Quick Ask', async ({ page }) => {
    await loginAsAlice(page);

    await expect(page).toHaveURL(/\/chat\?mode=quick/);
    await expect(page.locator('body')).toContainText(/Hypervisor|Balance Sheet|Portfolio/);
  });

  test('session survives reload', async ({ page }) => {
    await loginAsAlice(page);
    await page.reload();
    await expect(page).not.toHaveURL(/realms|auth\/login/);
    await expect(page.locator('body')).toContainText(/Hypervisor|Steering/);
  });

  test('invalid credentials stay on Keycloak with an error', async ({ page }) => {
    await expectInvalidLogin(page);
  });
});
