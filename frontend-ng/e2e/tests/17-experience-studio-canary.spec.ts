import { expect, test, type Locator, type Page } from '@playwright/test';

import { formSchemaSupported } from '../../src/app/features/experience/runtime/model';
import { runAccessibilityMatrix } from '../fixtures/accessibility-matrix';
import {
  allowRetainedExperience,
  api,
  assertDeployedRevision,
  bindWorkspace,
  deployExperience,
  discoverExperienceWorkspace,
  evidencePathFor,
  expectedSha,
  experienceCanaryEnabled,
  login,
  logout,
  reviewerCredentials,
  reviewerCredentialsMisconfigured,
  reviewerRequired,
  sha256,
  writeEvidence,
  type WorkspaceSummary,
} from '../fixtures/experience-canary';

/**
 * US-8 — real authenticated Experience lifecycle canary.
 *
 * The default path is transactional: it creates through the three-step UI,
 * edits and saves in Studio, creates an immutable release, proves that release
 * is absent from Work, then deletes the Experience and its newly-created
 * binding. `E2E_EXPERIENCE_DEPLOY=1` adds a real Pilot deployment and Work
 * render. A deployed Experience cannot be deleted, so that mode also requires
 * `E2E_EXPERIENCE_ALLOW_RETAINED=1` and an attested deployed SHA.
 */

interface SystemSummary {
  id: string;
  name: string;
  status?: string;
  published_flow_version_id?: string | null;
}

interface IngressSummary {
  ingress_id: string;
  kind?: string;
  input_schema?: unknown;
}

interface IngressCatalog {
  published_flow_version_id?: string | null;
  ingresses?: IngressSummary[];
}

interface ExperienceDetail {
  id: string;
  slug: string;
  draft?: { binding_keys?: string[] } | null;
  deployments?: Array<{ channel: string; release_id: string }>;
}

interface ReadyCheck {
  ready: boolean;
  blockers: unknown[];
  warnings: unknown[];
  bindings_sha256: string;
  bindings: Array<{ binding_key: string }>;
}

interface ReleaseSummary {
  id: string;
  release_number: number;
}

interface CompatibleIngress {
  system: SystemSummary;
  ingress: IngressSummary;
}

const CREATE_CTA = /Nouvelle application|New application/;
const CONTINUE = /continuer|continue/i;
const OPEN_EDITOR = /Ouvrir l[’']éditeur|Open the editor/;
const SAVE = /^(Enregistrer|Save)$/;
const SAVED = /Brouillon enregistré|Draft saved/;
const PUBLISH = /^(Publier|Publish)$/;

async function expectContained(locator: Locator, viewportWidth: number): Promise<void> {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  expect(box, 'visible surface has a bounding box').not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(-1);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewportWidth + 1);
}

async function expectNoPageOverflow(page: Page, viewportWidth: number): Promise<void> {
  const width = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(width.client).toBe(viewportWidth);
  expect(width.scroll).toBeLessThanOrEqual(viewportWidth);
}

async function findCompatibleIngress(page: Page, workspaceSlug: string): Promise<CompatibleIngress> {
  const listed = await api<{ systems?: SystemSummary[] } | SystemSummary[]>(page, workspaceSlug, '/systems');
  expect(listed.ok, `GET /systems failed (${listed.status})`).toBe(true);
  const systems = Array.isArray(listed.body) ? listed.body : listed.body.systems ?? [];
  for (const system of systems) {
    if (system.status !== 'active' || !system.published_flow_version_id) continue;
    const catalog = await api<IngressCatalog>(
      page,
      workspaceSlug,
      `/systems/${encodeURIComponent(system.id)}/ingresses`,
    );
    if (!catalog.ok || catalog.body.published_flow_version_id !== system.published_flow_version_id) continue;
    const ingress = (catalog.body.ingresses ?? []).find(
      (item) => (item.kind === undefined || item.kind === 'manual')
        && formSchemaSupported(item.input_schema ?? { type: 'object', properties: {}, required: [] }),
    );
    if (ingress) return { system, ingress };
  }
  throw new Error('The Experience canary needs one active published System with a supported manual ingress.');
}

async function checkMobileAuthoringShell(
  page: Page,
  workspace: WorkspaceSummary,
  width: 320 | 456,
): Promise<void> {
  await page.setViewportSize({ width, height: 720 });
  await page.goto('/create');
  await expectNoPageOverflow(page, width);
  await expectContained(page.locator('app-title-bar header'), width);
  await expectContained(page.getByRole('main'), width);
  await expectContained(page.locator('app-create-hub ck-page-frame > section'), width);
  await expectContained(page.locator('app-mini-rail aside'), width);
  const lastMiniItem = page.locator('app-mini-rail .ck-mini-item').last();
  await lastMiniItem.scrollIntoViewIfNeeded();
  await expectContained(lastMiniItem, width);
  const clippedTitleItems = await page.locator('app-title-bar header > *:visible').evaluateAll(
    (items, right) => items
      .map((item) => item.getBoundingClientRect())
      .filter((rect) => rect.left < -1 || rect.right > right + 1)
      .length,
    width,
  );
  expect(clippedTitleItems).toBe(0);

  const workspaceToggle = page.getByTestId('workspace-switcher-toggle');
  expect(await workspaceToggle.getAttribute('aria-label')).toContain(workspace.name);
  await workspaceToggle.click();
  const workspacePopover = page.getByTestId('workspace-switcher-popover');
  await expectContained(workspacePopover, width);
  await page.keyboard.press('Escape');
  await expect(workspacePopover).toHaveCount(0);

  await page.goto('/create/apps/new');
  await expectNoPageOverflow(page, width);
  await expectContained(page.locator('.xp-wizard'), width);
  await expectContained(page.locator('.xp-wizard-topbar'), width);
  await expectContained(page.locator('.xp-wizard-body'), width);
  await expect(page.locator('app-title-bar')).toHaveAttribute('inert', '');
  await expect(page.locator('app-side-rail')).toHaveAttribute('inert', '');
  const footer = page.locator('.xp-wizard .xp-foot');
  await footer.scrollIntoViewIfNeeded();
  await expectContained(footer, width);
  await expect(footer.getByRole('button', { name: CONTINUE })).toBeVisible();
}

async function checkMobileEditor(page: Page, editorPath: string, width: 320 | 456): Promise<void> {
  await page.setViewportSize({ width, height: 720 });
  await page.goto(editorPath);
  // Same contract as the wizard: the Studio paints a fixed overlay, so the
  // Angular host wraps nothing in flow and has no box. Assert the overlay.
  await expect(page.locator('app-experience-editor .xp-ed')).toBeVisible();
  await expectNoPageOverflow(page, width);
  await expectContained(page.locator('.xp-ed'), width);
  await expectContained(page.locator('.xp-ed-chrome'), width);
  await expectContained(page.locator('.xp-ed-tools'), width);
  await expectContained(page.locator('.xp-bottom-bar'), width);
  await page.locator('.xp-ed-inspector').scrollIntoViewIfNeeded();
  await expect(page.locator('.xp-ed-inspector')).toBeVisible();
  await expect(page.locator('app-title-bar')).toHaveAttribute('inert', '');

  const editorHeading = page.locator('app-experience-editor h1');
  await editorHeading.focus();
  await page.keyboard.press('Control+J');
  const chat = page.locator('app-chat-overlay [role="dialog"]');
  await expect(chat).toBeVisible();
  await expectContained(chat, width);
  await expect(chat.locator('button').first()).toBeFocused();
  // Chat sets aria-hidden on #main-content; getByRole('main') cannot see it.
  await expect(page.locator('#main-content')).toHaveAttribute('inert', '');
  const chatInput = chat.getByRole('textbox').first();
  if (await chatInput.count()) await chatInput.focus();
  await page.keyboard.press('Escape');
  await expect(chat).toHaveCount(0);
  await expect(page.locator('#main-content')).not.toHaveAttribute('inert', '');
  await expect(editorHeading).toBeFocused();
}

async function reviewerCheck(
  page: Page,
  workspace: WorkspaceSummary,
  experienceId: string,
  name: string,
): Promise<boolean> {
  expect(
    reviewerCredentialsMisconfigured,
    'configure both E2E_EXPERIENCE_REVIEWER_USERNAME and E2E_EXPERIENCE_REVIEWER_PASSWORD',
  ).toBe(false);
  if (!reviewerCredentials) {
    expect(reviewerRequired, 'Reviewer credentials are required by E2E_EXPERIENCE_REQUIRE_REVIEWER=1').toBe(false);
    return false;
  }
  await logout(page);
  const memberships = await login(page, reviewerCredentials);
  const reviewerWorkspace = memberships.find((item) => item.id === workspace.id);
  expect(reviewerWorkspace, 'the reviewer principal must belong to the authoring workspace').toBeTruthy();
  expect(reviewerWorkspace?.role_template).toBe('workspace_reviewer');
  await bindWorkspace(page, reviewerWorkspace!.slug);

  await page.goto('/create/apps/new');
  await expect.poll(() => new URL(page.url()).pathname).toMatch(/^\/work(?:\/|$)/);

  await page.goto('/create/apps');
  await expect(page.getByRole('link', { name: CREATE_CTA })).toHaveCount(0);
  await page.locator('app-business-apps-page input[type="search"]').fill(name);
  const row = page.locator('app-business-apps-page tbody tr').filter({ hasText: name });
  await expect(row).toHaveCount(1);
  await expect(row.getByRole('link', { name: /Revoir|Review/ })).toBeVisible();
  await row.getByRole('link', { name: /Revoir|Review/ }).click();
  await expect(page).toHaveURL(new RegExp(`/create/apps/${experienceId}$`));
  await expect(page.locator('.xp-ed')).toHaveClass(/is-readonly/);
  await expect(page.getByText(/Revue seule|Review only/)).toBeVisible();
  await expect(page.getByRole('button', { name: SAVE })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Annuler|Undo/ })).toHaveCount(0);
  await expect(page.locator('.xp-inspector-fields')).toBeDisabled();
  await expect(page.getByRole('button', { name: PUBLISH })).toBeVisible();
  return true;
}

async function cleanupExperience(
  page: Page,
  workspaceSlug: string,
  experienceId: string,
  initialBindings: ReadonlySet<string>,
): Promise<'deleted' | 'retained_deployed' | 'already_absent'> {
  const detail = await api<ExperienceDetail>(
    page,
    workspaceSlug,
    `/experiences/${encodeURIComponent(experienceId)}`,
  );
  if (detail.status === 404) return 'already_absent';
  expect(detail.ok, `GET Experience before cleanup failed (${detail.status})`).toBe(true);
  if ((detail.body.deployments ?? []).length > 0) return 'retained_deployed';

  const newBindings = (detail.body.draft?.binding_keys ?? []).filter((key) => !initialBindings.has(key));
  const deleted = await api<null>(
    page,
    workspaceSlug,
    `/experiences/${encodeURIComponent(experienceId)}`,
    { method: 'DELETE' },
  );
  expect(deleted.status, 'the undeployed canary Experience must be removable').toBe(204);
  for (const key of newBindings) {
    const bindingDeleted = await api<null>(
      page,
      workspaceSlug,
      `/system-bindings/${encodeURIComponent(key)}`,
      { method: 'DELETE' },
    );
    expect([204, 404], `cleanup of binding ${key}`).toContain(bindingDeleted.status);
  }
  return 'deleted';
}

test.use({ trace: 'off', video: 'off', screenshot: 'off' });

test.describe('US-8 — Experience Studio lifecycle canary', () => {
  test.skip(!experienceCanaryEnabled, 'Set E2E_EXPERIENCE_CANARY=1 to exercise /create');

  test('creates, saves, checks and releases a real application from scratch', async ({ page }, testInfo) => {
    test.setTimeout(300_000);
    let workspace: WorkspaceSummary | null = null;
    let experienceId: string | null = null;
    let cleanup: 'pending' | 'deleted' | 'retained_deployed' | 'already_absent' = 'pending';
    let initialBindings = new Set<string>();
    let primarySession = false;

    try {
      await assertDeployedRevision(page);
      expect(
        reviewerCredentialsMisconfigured,
        'configure both reviewer credential variables, or neither',
      ).toBe(false);
      if (reviewerRequired) {
        expect(reviewerCredentials, 'E2E_EXPERIENCE_REQUIRE_REVIEWER=1 requires reviewer credentials').toBeTruthy();
      }
      if (deployExperience) {
        expect(allowRetainedExperience, 'Pilot deployment is permanent: set E2E_EXPERIENCE_ALLOW_RETAINED=1').toBe(true);
        expect(expectedSha, 'Pilot deployment requires E2E_EXPECTED_SHA').toMatch(/^[0-9a-f]{40}$/);
      }
      const memberships = await login(page);
      primarySession = true;
      workspace = await discoverExperienceWorkspace(page, memberships, { studio: true });
      expect(workspace, 'experience_v1 must be enabled on an authorized workspace').toBeTruthy();
      await bindWorkspace(page, workspace!.slug);

      const bindingList = await api<{ bindings?: Array<{ binding_key: string }> }>(
        page,
        workspace!.slug,
        '/system-bindings',
      );
      expect(bindingList.ok, `GET /system-bindings failed (${bindingList.status})`).toBe(true);
      initialBindings = new Set((bindingList.body.bindings ?? []).map((item) => item.binding_key));
      const target = await findCompatibleIngress(page, workspace!.slug);

      for (const width of [456, 320] as const) {
        await checkMobileAuthoringShell(page, workspace!, width);
      }

      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto('/create/apps/new');
      // The wizard paints itself as a fixed full-screen overlay, so its Angular
      // host element wraps nothing in flow and has no box of its own. Assert on
      // the overlay, which is what the reader actually sees.
      await expect(page.locator('app-experience-wizard .xp-wizard')).toBeVisible();
      const selectedPattern = page.locator('[role="radio"][aria-checked="true"]').first();
      await selectedPattern.focus();
      await page.keyboard.press('ArrowRight');
      await expect(page.locator('[role="radio"][aria-checked="true"]').first()).toBeFocused();
      await page.keyboard.press('ArrowLeft');
      await expect(selectedPattern).toBeFocused();

      const name = `QA E2E Experience ${Date.now().toString(36)}`;
      await page.locator('#xp-wiz-name').fill(name);
      const createResponsePromise = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return response.request().method() === 'POST' && url.pathname === '/api/v1/experiences';
      });
      await page.locator('.xp-foot').getByRole('button', { name: CONTINUE }).click();
      const createResponse = await createResponsePromise;
      expect(createResponse.status(), 'Experience creation response').toBe(201);
      const created = await createResponse.json() as ExperienceDetail;
      experienceId = created.id;
      expect(created.slug).toBeTruthy();
      await expect(page.locator('#xp-wiz-heading')).toBeFocused();

      await page.locator('.xp-search input[type="search"]').fill(target.system.name);
      const systemCard = page.locator('.xp-sys').filter({
        has: page.getByText(target.system.name, { exact: true }),
      }).filter({ hasText: target.ingress.ingress_id });
      await expect(systemCard).toHaveCount(1);
      const ingressRow = systemCard.locator('.xp-entry').filter({ hasText: target.ingress.ingress_id });
      await ingressRow.getByRole('button', { name: /Relier|Link/ }).click();
      const stepTwoContinue = page.locator('.xp-foot').getByRole('button', { name: CONTINUE });
      await expect(stepTwoContinue).toBeEnabled();
      await stepTwoContinue.click();
      await expect(page.locator('#xp-wiz-heading')).toBeFocused();
      await page.getByRole('checkbox', { name: /^Admin$/ }).check();

      const finalizeResponsePromise = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return response.request().method() === 'PUT'
          && url.pathname === `/api/v1/experiences/${experienceId}/draft/finalize`;
      });
      await page.getByRole('button', { name: OPEN_EDITOR }).click();
      const finalized = await finalizeResponsePromise;
      expect(finalized.ok(), 'wizard finalization response').toBe(true);
      await expect(page).toHaveURL(new RegExp(`/create/apps/${experienceId}$`));
      const editorPath = new URL(page.url()).pathname;
      await expect(page.locator('app-experience-editor h1')).toHaveText(name);
      await expect(page.locator('app-experience-editor h1')).toBeFocused();

      const pageTitle = page.locator('#xp-inspector-panel-content .xp-field input').first();
      const saveResponsePromise = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return response.request().method() === 'PUT'
          && url.pathname === `/api/v1/experiences/${experienceId}/draft`;
      });
      await pageTitle.fill(`${name} · Home`);
      const saveButton = page.getByRole('button', { name: SAVE });
      await expect(saveButton).toBeEnabled();
      await saveButton.click();
      expect((await saveResponsePromise).ok(), 'explicit Studio save response').toBe(true);
      await expect(page.getByRole('button', { name: SAVED })).toBeDisabled();

      const leftTab = page.locator('.xp-left-tabs [role="tab"][aria-selected="true"]');
      await leftTab.focus();
      await page.keyboard.press('ArrowRight');
      await expect(page.locator('.xp-left-tabs [role="tab"][aria-selected="true"]')).toBeFocused();
      await page.keyboard.press('ArrowLeft');
      await expect(leftTab).toBeFocused();
      const viewportRadio = page.locator('.xp-canvas-tools [role="radio"][aria-checked="true"]');
      await viewportRadio.focus();
      await page.keyboard.press('ArrowRight');
      await expect(page.locator('.xp-canvas-tools [role="radio"][aria-checked="true"]')).toBeFocused();

      const ready = await api<ReadyCheck>(
        page,
        workspace!.slug,
        `/experiences/${encodeURIComponent(experienceId)}/ready-check`,
      );
      expect(ready.ok, `ready-check failed (${ready.status})`).toBe(true);
      expect(ready.body.ready).toBe(true);
      expect(ready.body.blockers).toEqual([]);
      expect(ready.body.bindings).toHaveLength(1);
      expect(ready.body.bindings_sha256).toMatch(/^[0-9a-f]{64}$/);
      await page.locator('.xp-ready-link').click();
      await expect(page.locator('#xp-bottom-panel')).toBeVisible();

      for (const width of [456, 320] as const) {
        await checkMobileEditor(page, editorPath, width);
      }
      const studioMatrix = await runAccessibilityMatrix({
        page,
        testInfo,
        path: editorPath,
        readySelector: 'app-experience-editor .xp-ed',
        surface: 'studio',
      });
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(editorPath);
      await expect(page.locator('app-experience-editor h1')).toHaveText(name);
      await expect.poll(async () => (await page.locator('.xp-ready-link').textContent())?.trim() ?? '')
        .not.toMatch(/Vérification indisponible|Check unavailable/);

      const publishButton = page.getByRole('button', { name: PUBLISH });
      await publishButton.click();
      const dialog = page.locator('.xp-pub-dialog');
      await expect(dialog).toBeVisible();
      await expect(dialog.locator('textarea')).toBeFocused();
      await page.keyboard.press('Escape');
      await expect(dialog).toHaveCount(0);
      await expect(publishButton).toBeFocused();

      await publishButton.click();
      await dialog.locator('textarea').fill(`Canary ${expectedSha || 'unattested'} · ${name}`);
      const releaseResponsePromise = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return response.request().method() === 'POST'
          && url.pathname === `/api/v1/experiences/${experienceId}/releases`;
      });
      await dialog.getByRole('button', { name: /Créer la release|Create the release/ }).click();
      const releaseResponse = await releaseResponsePromise;
      expect(releaseResponse.status(), 'release creation response').toBe(201);
      const release = await releaseResponse.json() as ReleaseSummary;
      expect(release.release_number).toBeGreaterThan(0);
      await expect(dialog.getByText(/Release r\d+ créée|Release r\d+ created/)).toBeFocused();

      const workBeforeDeployment = await api<{ experiences?: Array<{ experience?: { id?: string } }> }>(
        page,
        workspace!.slug,
        '/work',
      );
      expect(workBeforeDeployment.ok, `GET /work failed (${workBeforeDeployment.status})`).toBe(true);
      expect((workBeforeDeployment.body.experiences ?? []).some((item) => item.experience?.id === experienceId))
        .toBe(false);

      let deployed = false;
      let rollbackExecuted = false;
      let secondRelease: ReleaseSummary | null = null;
      if (deployExperience) {
        await dialog.getByRole('radio', { name: /Pilote|Pilot/ }).check();
        const deployResponsePromise = page.waitForResponse((response) => {
          const url = new URL(response.url());
          return response.request().method() === 'POST'
            && url.pathname === `/api/v1/experiences/${experienceId}/deployments`;
        });
        await dialog.getByRole('button', { name: /^(Déployer|Deploy)$/ }).click();
        const deployResponse = await deployResponsePromise;
        expect(deployResponse.status(), 'Pilot deployment response').toBe(201);
        deployed = true;
        await expect(dialog).toHaveCount(0);

        const work = await api<{ experiences?: Array<{ experience?: { id?: string; slug?: string } }> }>(
          page,
          workspace!.slug,
          '/work',
        );
        expect(work.ok, `GET /work after deployment failed (${work.status})`).toBe(true);
        expect((work.body.experiences ?? []).some((item) => item.experience?.id === experienceId)).toBe(true);
        await page.goto(`/work/${created.slug}`);
        await expect(page.locator('app-work-shell')).toBeVisible();
        await expect(page.getByRole('heading', { level: 1, name }).first()).toBeVisible();
        await expect(page.locator('app-side-rail')).toHaveCount(0);
        await expect(page.locator('app-work-shell xp-rt-form')).toBeVisible();
        for (const width of [456, 320] as const) {
          await page.setViewportSize({ width, height: 720 });
          await page.goto(`/work/${created.slug}`);
          await expectNoPageOverflow(page, width);
          await expectContained(page.locator('app-work-shell'), width);
          await expectContained(page.getByRole('main'), width);
        }

        // A rollback only has meaning after a second immutable release has
        // replaced the first one on the same channel.
        await page.setViewportSize({ width: 1440, height: 900 });
        await page.goto(editorPath);
        const secondTitle = page.locator('#xp-inspector-panel-content .xp-field input').first();
        const secondSavePromise = page.waitForResponse((response) => {
          const url = new URL(response.url());
          return response.request().method() === 'PUT'
            && url.pathname === `/api/v1/experiences/${experienceId}/draft`;
        });
        await secondTitle.fill(`${name} · V2`);
        await page.getByRole('button', { name: SAVE }).click();
        expect((await secondSavePromise).ok(), 'second draft save response').toBe(true);

        await page.getByRole('button', { name: PUBLISH }).click();
        await expect(dialog).toBeVisible();
        await dialog.locator('textarea').fill(`Rollback canary · ${name}`);
        const secondReleasePromise = page.waitForResponse((response) => {
          const url = new URL(response.url());
          return response.request().method() === 'POST'
            && url.pathname === `/api/v1/experiences/${experienceId}/releases`;
        });
        await dialog.getByRole('button', { name: /Créer la release|Create the release/ }).click();
        const secondReleaseResponse = await secondReleasePromise;
        expect(secondReleaseResponse.status(), 'second release creation response').toBe(201);
        secondRelease = await secondReleaseResponse.json() as ReleaseSummary;
        expect(secondRelease.release_number).toBeGreaterThan(release.release_number);
        await dialog.getByRole('radio', { name: /Pilote|Pilot/ }).check();
        const secondDeployPromise = page.waitForResponse((response) => {
          const url = new URL(response.url());
          return response.request().method() === 'POST'
            && url.pathname === `/api/v1/experiences/${experienceId}/deployments`;
        });
        await dialog.getByRole('button', { name: /^(Déployer|Deploy)$/ }).click();
        expect((await secondDeployPromise).status(), 'second Pilot deployment response').toBe(201);
        await expect(dialog).toHaveCount(0);

        await page.goto(editorPath);
        await page.getByRole('tab', { name: /Journal/ }).click();
        const rollbackButton = page.getByRole('button', { name: /Revenir en arrière|Roll back/ });
        await expect(rollbackButton).toBeEnabled();
        const rollbackPromise = page.waitForResponse((response) => {
          const url = new URL(response.url());
          return response.request().method() === 'POST'
            && url.pathname === `/api/v1/experiences/${experienceId}/deployments/pilot/rollback`;
        });
        await rollbackButton.click();
        expect((await rollbackPromise).ok(), 'Pilot rollback response').toBe(true);
        rollbackExecuted = true;

        const resolvedAfterRollback = await api<{
          release?: { id?: string };
          deployment?: { channel?: string; release_id?: string };
        }>(page, workspace!.slug, `/work/${encodeURIComponent(created.slug)}`);
        expect(resolvedAfterRollback.ok, `GET Work after rollback failed (${resolvedAfterRollback.status})`).toBe(true);
        expect(resolvedAfterRollback.body.release?.id).toBe(release.id);
        expect(resolvedAfterRollback.body.deployment).toMatchObject({
          channel: 'pilot',
          release_id: release.id,
        });
      } else {
        await dialog.getByRole('button', { name: /Terminer|Done/ }).click();
        await expect(dialog).toHaveCount(0);
        await expect(publishButton).toBeFocused();
      }

      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(editorPath);
      await page.getByRole('tab', { name: /Journal/ }).click();
      await expect(page.locator('#xp-bottom-panel')).toContainText(`R${release.release_number}`);

      if (reviewerCredentials) primarySession = false;
      const reviewerCovered = await reviewerCheck(page, workspace!, experienceId, name);
      if (!primarySession) {
        await logout(page);
        const primaryMemberships = await login(page);
        const primaryWorkspace = primaryMemberships.find((item) => item.id === workspace!.id);
        expect(primaryWorkspace, 'primary principal lost the canary workspace').toBeTruthy();
        await bindWorkspace(page, primaryWorkspace!.slug);
        primarySession = true;
      }

      cleanup = await cleanupExperience(page, workspace!.slug, experienceId, initialBindings);
      expect(cleanup).toBe(deployed ? 'retained_deployed' : 'deleted');

      const evidence = {
        schema_version: 2,
        kind: 'experience_studio_lifecycle_canary',
        claim: 'US-8-STUDIO-LIFECYCLE',
        outcome: 'passed',
        tested_revision: expectedSha || null,
        generated_at: new Date().toISOString(),
        target: {
          workspace_sha256: sha256(workspace!.id),
          experience_sha256: sha256(experienceId),
          system_sha256: sha256(target.system.id),
          release_sha256: sha256(release.id),
        },
        checks: {
          wizard_three_steps: true,
          real_experience_created: true,
          compatible_ingress_linked: true,
          staged_binding_finalized: true,
          explicit_admin_audience: true,
          editor_opened: true,
          explicit_save_persisted: true,
          ready_check_passed: true,
          release_created: true,
          release_absent_from_work_before_deploy: true,
          release_and_deployment_separate: true,
          keyboard_roving_focus: true,
          modal_focus_trap_and_restore: true,
          mobile_456_no_clipping: true,
          mobile_320_no_clipping: true,
          workspace_switcher_mobile_contained: true,
          shell_inert_behind_wizard: true,
          accessibility_matrix: studioMatrix.combinations,
          wcag_aa_axe: true,
          reduced_motion: true,
          reflow_320_css_px: true,
          reviewer: reviewerCovered ? 'executed' : 'not_configured',
          pilot_deployment: deployed ? 'executed' : 'not_requested',
          rollback: rollbackExecuted ? 'executed' : 'not_requested',
          second_release_sha256: secondRelease ? sha256(secondRelease.id) : null,
          work_render: deployed ? 'executed' : 'not_requested',
          cleanup,
        },
      };
      writeEvidence(evidencePathFor('studio'), evidence);
      await testInfo.attach('experience-studio-lifecycle-canary', {
        body: JSON.stringify(evidence, null, 2),
        contentType: 'application/json',
      });
    } finally {
      if (workspace && experienceId && cleanup === 'pending') {
        try {
          if (!primarySession) {
            await logout(page);
            await login(page);
            await bindWorkspace(page, workspace.slug);
            primarySession = true;
          }
          cleanup = await cleanupExperience(page, workspace.slug, experienceId, initialBindings);
        } catch {
          // Keep the primary assertion as the failure; traces stay disabled.
        }
      }
      await logout(page);
    }
  });
});
