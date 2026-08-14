import { expect, test } from '@playwright/test';

import {
  assertDeployedRevision,
  bindWorkspace,
  discoverExperienceWorkspace,
  evidencePathFor,
  expectedSha,
  experienceCanaryEnabled,
  login,
  logout,
  sha256,
  writeEvidence,
} from '../fixtures/experience-canary';

/**
 * US-8 — authenticated Studio create-hub / inventory canary.
 *
 * Discovers `settings.features.experience_v1` from the live principal's
 * workspaces. No tenant or app id is embedded. Skips when the flag is off.
 * Traces stay off because login uses a live principal.
 */

const CREATE_CTA = /Nouvelle application|New application/;
const APPS_HEADING = /Applications métier|Business applications/;

test.use({ trace: 'off', video: 'off', screenshot: 'off' });

test.describe('US-8 — Experience Studio canary', () => {
  test.skip(!experienceCanaryEnabled, 'Set E2E_EXPERIENCE_CANARY=1 to exercise /create');
  test.afterEach(async ({ page }) => logout(page));

  test('loads the create hub, inventory and new-app wizard', async ({ page }, testInfo) => {
    await assertDeployedRevision(page);
    const memberships = await login(page);
    const workspace = await discoverExperienceWorkspace(page, memberships);
    if (!workspace) {
      test.skip(true, 'experience_v1 is off on every authorized workspace');
      return;
    }

    await bindWorkspace(page, workspace.slug);

    await page.goto('/create');
    await expect(page.getByRole('main')).toBeVisible();
    await expect(page.locator('app-create-hub')).toBeVisible();
    await expect(page.locator('app-create-hub').getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByRole('link', { name: CREATE_CTA }).first()).toBeVisible();

    await page.goto('/create/apps');
    await expect(page.locator('app-business-apps-page')).toBeVisible();
    await expect(page.getByRole('heading', { name: APPS_HEADING })).toBeVisible();
    await expect(page.getByRole('link', { name: CREATE_CTA }).first()).toBeVisible();
    await expect(
      page.locator('app-business-apps-page table, app-business-apps-page app-empty-state'),
    ).toBeVisible();

    await page.goto('/create/apps/new');
    await expect(page.locator('app-experience-wizard')).toBeVisible();
    await expect(page.getByRole('heading', { name: CREATE_CTA })).toBeVisible();
    await expect(page.getByRole('radiogroup')).toBeVisible();

    const evidence = {
      schema_version: 1,
      kind: 'experience_studio_canary',
      claim: 'US-8-STUDIO-CREATE',
      outcome: 'passed',
      tested_revision: expectedSha || null,
      generated_at: new Date().toISOString(),
      target: { workspace_sha256: sha256(workspace.id) },
      checks: {
        experience_v1: true,
        create_hub: true,
        inventory: true,
        wizard: true,
        create_cta: true,
        main_landmark: true,
      },
    };
    writeEvidence(evidencePathFor('studio'), evidence);
    await testInfo.attach('experience-studio-canary', {
      body: JSON.stringify(evidence, null, 2),
      contentType: 'application/json',
    });
  });
});
