import { expect, test, type Locator, type Page } from '@playwright/test';

import {
  api,
  assertDeployedRevision,
  bindWorkspace,
  discoverExperienceWorkspace,
  evidencePathFor,
  expectedSha,
  experienceCanaryEnabled,
  launchableExperiences,
  login,
  logout,
  sha256,
  writeEvidence,
  type ExperienceRow,
} from '../fixtures/experience-canary';

/**
 * US-8 — authenticated /work launcher canary.
 *
 * Discovers `settings.features.experience_v1` from the live principal's
 * workspaces. No tenant, app or row id is embedded. Skips (does not fail)
 * when the flag is off or no Pilot/In-service app is visible. Traces stay
 * off because login uses a live principal.
 */

const ENGINE_JARGON = /\b(Flows?|Skills?|Runs?)\b/;

test.use({ trace: 'off', video: 'off', screenshot: 'off' });

async function visibleChromeText(root: Locator): Promise<string> {
  return (await root.allTextContents()).join(' ').replace(/\s+/g, ' ').trim();
}

async function workSurface(page: Page): Promise<'launcher' | 'redirect' | null> {
  const path = new URL(page.url()).pathname.replace(/\/$/, '') || '/';
  if (path.startsWith('/work/') && await page.locator('app-work-shell').count() > 0) {
    return 'redirect';
  }
  if (path !== '/work') return null;
  const listed = await page.locator('app-work-launcher .xp-work-grid').count();
  const empty = await page.locator('app-work-launcher app-empty-state p').count();
  return listed > 0 || empty > 0 ? 'launcher' : null;
}

test.describe('US-8 — Experience /work canary', () => {
  test.skip(!experienceCanaryEnabled, 'Set E2E_EXPERIENCE_CANARY=1 to exercise /work');
  test.afterEach(async ({ page }) => logout(page));

  test('opens the launcher or a deployed app without cockpit chrome', async ({ page }, testInfo) => {
    await assertDeployedRevision(page);
    const memberships = await login(page);
    const workspace = await discoverExperienceWorkspace(page, memberships);
    if (!workspace) {
      test.skip(true, 'experience_v1 is off on every authorized workspace');
      return;
    }

    const listed = await api<{ experiences: ExperienceRow[] }>(
      page,
      workspace.slug,
      '/experiences',
    );
    expect(listed.ok, `GET /experiences failed (${listed.status})`).toBe(true);
    const apps = launchableExperiences(listed.body.experiences ?? [], workspace);
    if (apps.length === 0) {
      test.skip(true, 'no Pilot/In-service Experience is visible to this principal');
      return;
    }

    await bindWorkspace(page, workspace.slug);
    await page.goto('/work');
    await expect.poll(async () => workSurface(page)).not.toBeNull();
    const surface = await workSurface(page);
    expect(surface, 'work must settle on the launcher or a deployed app').toBeTruthy();

    await expect(page.locator('app-side-rail')).toHaveCount(0);
    await expect(page.getByRole('main')).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    if (surface === 'launcher') {
      await expect(page.locator('app-work-launcher')).toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Mes applications|My applications/ }),
      ).toBeVisible();
      await expect(page.locator('.xp-work-grid a.xp-work-card')).toHaveCount(apps.length);
      const chrome = page.locator('app-work-launcher header, app-work-launcher .xp-work-status, app-work-launcher .xp-work-grid p');
      expect(await visibleChromeText(chrome), 'launcher chrome must not name Flow/Skill/Run')
        .not.toMatch(ENGINE_JARGON);
    } else {
      await expect(page.locator('app-work-shell')).toBeVisible();
      expect(new URL(page.url()).pathname).toMatch(/^\/work\/[^/]+/);
      const chrome = page.locator(
        'app-work-shell .xp-work-brand a, app-work-shell .xp-work-actions a, app-work-shell .xp-work-actions button',
      );
      expect(await visibleChromeText(chrome), 'work chrome must not name Flow/Skill/Run')
        .not.toMatch(ENGINE_JARGON);
    }

    const evidence = {
      schema_version: 1,
      kind: 'experience_work_canary',
      claim: 'US-8-WORK-LAUNCHER',
      outcome: 'passed',
      tested_revision: expectedSha || null,
      generated_at: new Date().toISOString(),
      target: { workspace_sha256: sha256(workspace.id) },
      checks: {
        experience_v1: true,
        work_surface: surface,
        no_side_rail: true,
        no_engine_jargon: true,
        main_landmark: true,
      },
    };
    writeEvidence(evidencePathFor('work'), evidence);
    await testInfo.attach('experience-work-canary', {
      body: JSON.stringify(evidence, null, 2),
      contentType: 'application/json',
    });
  });
});
