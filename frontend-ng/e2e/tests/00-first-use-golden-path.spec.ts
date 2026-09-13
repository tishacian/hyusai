import { expect, test } from '@playwright/test';
import { loginAsAlice } from '../fixtures/auth';
import { writeTinyPdf } from '../fixtures/pdf';

const enabled = process.env['E2E_GOLDEN_PATH'] === '1';
const provider = process.env['E2E_GOLDEN_PROVIDER'] ?? '';
const model = process.env['E2E_GOLDEN_MODEL'] ?? '';
const apiKey = process.env['E2E_GOLDEN_API_KEY'] ?? '';
const endpoint = process.env['E2E_GOLDEN_ENDPOINT'] ?? '';
const deployment = process.env['E2E_GOLDEN_DEPLOYMENT'] ?? '';
const maxFirstAnswerMs = Number(process.env['E2E_GOLDEN_MAX_FIRST_ANSWER_MS'] ?? '45000');

test.describe('P0.6 — first-use golden path', () => {
  test.skip(!enabled, 'Set E2E_GOLDEN_PATH=1 against an isolated clean workspace.');
  test.skip(!provider || !model, 'E2E_GOLDEN_PROVIDER and E2E_GOLDEN_MODEL are required.');

  for (const locale of ['en', 'fr'] as const) {
    test(`${locale}: connect → add knowledge → ask → source → recover`, async ({ page }, testInfo) => {
      await loginAsAlice(page);
      await page.evaluate((nextLocale) => localStorage.setItem('agentium_locale', nextLocale), locale);

      await page.goto('/settings');
      await page.locator('select[name="routeProvider"]').selectOption(provider);
      await page.locator('input[name="routeModel"]').fill(model);
      const keyInput = page.locator('input[name="routeApiKey"]');
      if (await keyInput.isVisible().catch(() => false)) await keyInput.fill(apiKey);
      const endpointInput = page.locator('input[name="routeEndpoint"]');
      if (await endpointInput.isVisible().catch(() => false)) await endpointInput.fill(endpoint);
      const deploymentInput = page.locator('input[name="routeDeployment"]');
      if (await deploymentInput.isVisible().catch(() => false)) await deploymentInput.fill(deployment);

      const setupResponse = page.waitForResponse((response) =>
        response.url().includes('/api/v1/models/setup') && response.request().method() === 'PUT',
      );
      await page
        .locator('form')
        .filter({ has: page.locator('select[name="routeProvider"]') })
        .getByRole('button')
        .click();
      expect((await setupResponse).ok(), 'model setup must probe successfully before it is saved').toBe(true);

      await page.goto('/knowledge');
      const fixtureName = `agentium-golden-${locale}.pdf`;
      const documentPath = writeTinyPdf(testInfo, fixtureName, [
        'Agentium first-use evidence.',
        'The verified answer is: the golden path opens a cited source and recovers from a retryable failure.',
      ]);
      await page.locator('input[type="file"]').first().setInputFiles(documentPath);
      await expect(page.locator('body')).toContainText(/ready|prêt/i, { timeout: 30_000 });

      await page.goto('/chat?mode=quick');
      const composer = page
        .locator('textarea, input[type="text"][placeholder*="Ask"], input[type="text"][placeholder*="question"]')
        .first();
      await composer.fill('What does the first-use evidence say the golden path does?');
      const startedAt = Date.now();
      await composer.press('Enter');
      const citation = page.locator('[data-cite-chip], button:has-text("[1]")').first();
      await expect(citation).toBeVisible({ timeout: maxFirstAnswerMs });
      expect(Date.now() - startedAt, 'time to first cited answer exceeded the release budget')
        .toBeLessThanOrEqual(maxFirstAnswerMs);

      await citation.click();
      const sourcesButton = page.getByRole('button', { name: /Sources|Sources utilisées/i }).first();
      if (await sourcesButton.isVisible().catch(() => false)) await sourcesButton.click();
      await expect(page.locator('body')).toContainText(fixtureName);

      let forced = false;
      await page.route('**/api/v1/chat/stream**', async (route) => {
        if (!forced) {
          forced = true;
          await route.abort('connectionfailed');
          return;
        }
        await route.continue();
      });
      await composer.fill('Repeat the verified answer.');
      await composer.press('Enter');
      const retry = page.getByRole('button', { name: /Try again|Réessayer/i }).last();
      await expect(retry).toBeVisible({ timeout: 15_000 });
      await retry.click();
      await expect(page.locator('[data-cite-chip], button:has-text("[1]")').last()).toBeVisible({
        timeout: maxFirstAnswerMs,
      });
    });
  }
});
