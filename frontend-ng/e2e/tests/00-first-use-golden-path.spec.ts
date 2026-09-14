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
const maxSignInToComposerMs = Number(process.env['E2E_PERF_SIGNIN_TO_COMPOSER_MS'] ?? '15000');
const maxModelReadinessMs = Number(process.env['E2E_PERF_MODEL_READINESS_MS'] ?? '15000');
const maxSourcePreviewMs = Number(process.env['E2E_PERF_SOURCE_PREVIEW_MS'] ?? '5000');
const maxIngestionMs = Number(process.env['E2E_GOLDEN_MAX_INGESTION_MS'] ?? '30000');
/**
 * Envelope for the whole scenario, not a milestone budget: the run signs in,
 * probes the model, ingests a document and then spends **two real LLM turns**
 * (first answer + forced-failure recovery), which does not fit Playwright's
 * 60s default. Every milestone budget above stays exactly as it was.
 */
const scenarioTimeoutMs = Number(process.env['E2E_GOLDEN_SCENARIO_TIMEOUT_MS'] ?? '180000');

/**
 * Per-run evidence marker.
 *
 * The gate runs against an isolated stack, not an empty one: a previous failed
 * or successful run leaves its documents and its conversation behind, and the
 * chat restores that history. Every artefact this test relies on therefore
 * carries a marker unique to this execution, so retrieval, the source list and
 * the preview can only be satisfied by the document this test just created.
 *
 * Privacy-safe by construction: built from the clock and randomness only — no
 * user, host, workspace or file-system identity travels into the document, the
 * prompt or the attached metrics.
 */
function evidenceMarker(locale: string): string {
  const random = Math.random().toString(36).slice(2, 8);
  // Only [A-Z0-9-] by construction, so it is safe to embed verbatim in the
  // XPath scopes below and in a filename.
  return `AGX-${locale}-${Date.now().toString(36)}-${random}`.toUpperCase().replace(/[^A-Z0-9-]/g, '');
}

/** Case-insensitive literal matcher — markers and filenames are not patterns. */
function literal(text: string): RegExp {
  return new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
}

test.describe('P0.6 — first-use golden path', () => {
  test.skip(!enabled, 'Set E2E_GOLDEN_PATH=1 against an isolated clean workspace.');
  test.skip(!provider || !model, 'E2E_GOLDEN_PROVIDER and E2E_GOLDEN_MODEL are required.');

  for (const locale of ['en', 'fr'] as const) {
    test(`${locale}: connect → add knowledge → ask → source → recover`, async ({ page }, testInfo) => {
      test.setTimeout(scenarioTimeoutMs);

      const marker = evidenceMarker(locale);
      const markerPattern = literal(marker);
      const fixtureName = `agentium-golden-${marker.toLowerCase()}.pdf`;
      // The document body stays ASCII on purpose: the tiny fixture writer emits
      // Helvetica literals, so accented UTF-8 bytes would come back out of the
      // extractor — and out of the PDF text layer — as mojibake. Everything the
      // operator actually reads or types (question, retry prompt, UI copy) is
      // genuinely localised.
      const evidence = locale === 'fr'
        ? {
            lead: `Preuve du parcours initial Agentium ${marker}.`,
            answer:
              `Dans la preuve ${marker}, le parcours initial Agentium ouvre la source qui porte `
              + 'la citation, puis il repart quand la connexion tombe.',
            question: `Dans la preuve ${marker}, que fait le parcours initial Agentium ?`,
            retry: `Répète la réponse vérifiée consignée dans la preuve ${marker}.`,
            ingested: 'Vous pouvez maintenant poser une question fondée sur ces documents.',
          }
        : {
            lead: `Agentium first-use evidence ${marker}.`,
            answer:
              `In evidence ${marker}, the Agentium first-use path opens the source that carries `
              + 'the citation, then recovers when the connection drops.',
            question: `In evidence ${marker}, what does the Agentium first-use path do?`,
            retry: `Repeat the verified answer recorded in evidence ${marker}.`,
            ingested: 'You can now ask a question grounded in these documents.',
          };
      const metrics: Record<string, number> = {};
      const signInStartedAt = Date.now();
      await loginAsAlice(page);
      metrics['signInToUsableComposerMs'] = Date.now() - signInStartedAt;
      expect(metrics['signInToUsableComposerMs']).toBeLessThanOrEqual(maxSignInToComposerMs);
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
      const readinessStartedAt = Date.now();
      await page
        .locator('form')
        .filter({ has: page.locator('select[name="routeProvider"]') })
        .getByRole('button')
        .click();
      expect((await setupResponse).ok(), 'model setup must probe successfully before it is saved').toBe(true);
      metrics['modelReadinessMs'] = Date.now() - readinessStartedAt;
      expect(metrics['modelReadinessMs']).toBeLessThanOrEqual(maxModelReadinessMs);

      await page.goto('/knowledge');
      const documentPath = writeTinyPdf(testInfo, fixtureName, [
        evidence.lead,
        evidence.answer,
      ]);
      await page.locator('input[type="file"]').first().setInputFiles(documentPath);
      // The knowledge KPI row already says "ready"/"prête" for previously
      // indexed collections, so wait on the upload panel's own outcome copy —
      // the only text that proves *this* upload finished ingesting.
      await expect(
        page.getByText(evidence.ingested, { exact: false }).first(),
        'the uploaded evidence document must finish ingesting',
      ).toBeVisible({ timeout: maxIngestionMs });

      await page.goto('/chat?mode=quick');
      const composer = page
        .locator('textarea, input[type="text"][placeholder*="Ask"], input[type="text"][placeholder*="question"]')
        .first();
      const userBubbles = page.locator('.ck-chat-user-bubble');
      // The chat decides asynchronously *which* conversation is on screen: it
      // lists the workspace sessions, then restores the stored one. An enabled
      // composer is the product's readiness signal for that decision — it is
      // inert for exactly as long as the conversation can still be replaced —
      // so waiting on it is a semantic wait, not a sleep.
      await expect(composer, 'the restored conversation must settle before anything is typed')
        .toBeEnabled({ timeout: maxSignInToComposerMs });

      // This run asks in a conversation of its own. On a workspace that already
      // carries earlier golden-path threads, sharing one would let a previous
      // run's answer satisfy the assertions below.
      await page
        .getByRole('button', { name: /^(New chat|Nouveau chat)$/ })
        .click();
      await expect(composer, 'the new conversation must be ready before the question')
        .toBeEnabled({ timeout: maxSignInToComposerMs });
      // Readiness means the conversation is final, so an empty thread here can
      // no longer be swapped for a restored one — which is precisely the race
      // that made a French run act on the English run's citations.
      await expect(userBubbles, 'the new conversation must start empty and stay empty')
        .toHaveCount(0);

      // Every locator below is additionally scoped with `following::` to the DOM
      // that comes after *this* run's own question bubble, so no other
      // conversation and no earlier turn can supply a citation, a Sources toggle
      // or a source row — and if this turn were ever wiped, the scope would
      // resolve to nothing and the gate would fail loudly instead of passing on
      // someone else's answer.
      const turnScope = `//*[contains(@class, "ck-chat-user-bubble") and contains(., "${marker}")]`;
      const askedQuestion = page.locator(`xpath=${turnScope}`);
      const citations = page.locator(`xpath=${turnScope}/following::button[@data-cite-chip]`);
      await composer.fill(evidence.question);
      const startedAt = Date.now();
      await composer.press('Enter');
      await expect(askedQuestion, 'the question must be posted as its own turn').toHaveCount(1);
      await expect(citations.first(), 'the question must produce a cited answer of its own')
        .toBeVisible({ timeout: maxFirstAnswerMs });
      metrics['questionToFirstCitedAnswerMs'] = Date.now() - startedAt;
      expect(metrics['questionToFirstCitedAnswerMs'], 'time to first cited answer exceeded the release budget')
        .toBeLessThanOrEqual(maxFirstAnswerMs);

      // Streaming rewrites the answer body (and with it the source rows) on
      // every chunk, which is what detached the preview button mid-click. The
      // composer is disabled for exactly as long as the stream is open, so an
      // enabled composer is the semantic end-of-stream signal. Deliberately
      // measured outside the source-preview budget below.
      await expect(composer, 'the answer must finish streaming before sources are touched')
        .toBeEnabled({ timeout: maxFirstAnswerMs });

      // Everything below targets the *latest* answer only: its citation, its
      // Sources toggle and its source list — all within this run's turn scope.
      const citation = citations.last();
      // `starts-with` keeps the control bar's "+ Sources" chip out: an answer
      // toggle reads "Sources · n" / "Sources utilisées".
      const sourcesButton = page
        .locator(`xpath=${turnScope}/following::button[starts-with(normalize-space(.), "Sources")]`)
        .last();
      await expect(sourcesButton).toBeVisible();
      const latestSourceList = page
        .locator(`xpath=${turnScope}/following::ol[li[contains(@id, "-src-")]]`)
        .last();
      // State is settled (the stream is over), so this cannot race the render:
      // open the panel through the latest answer's own toggle when it is
      // collapsed. Clicking a citation only ever opens a panel, never closes
      // one, so the click below keeps it open either way.
      if (!(await latestSourceList.isVisible())) await sourcesButton.click();
      await expect(latestSourceList).toBeVisible();

      const sourceStartedAt = Date.now();
      await citation.click();
      const sourceItem = latestSourceList
        .locator('li[id*="-src-"]')
        .filter({ hasText: markerPattern })
        .first();
      await expect(sourceItem, `the latest answer must cite the evidence document ${fixtureName}`)
        .toBeVisible();
      const previewButton = sourceItem.getByRole('button', {
        name: /Preview source document|Prévisualiser le document source/i,
      });
      // Locator retry semantics only: the button must still be there — and stay
      // there — once the message finished its post-stream updates.
      await expect(previewButton, 'the cited source must keep an actionable preview control')
        .toBeVisible();
      await previewButton.click();

      await expect(page.getByRole('heading', { name: markerPattern })).toBeVisible();
      const pdfViewer = page.locator('ngx-extended-pdf-viewer');
      await expect(pdfViewer).toBeVisible();
      // Proof the original PDF was fetched and rendered, not merely named: the
      // marker only exists inside the bytes this test uploaded.
      await expect(pdfViewer.locator('.textLayer'), 'the rendered PDF must contain this run’s evidence')
        .toContainText(marker);
      metrics['citationToSourcePreviewMs'] = Date.now() - sourceStartedAt;
      expect(metrics['citationToSourcePreviewMs']).toBeLessThanOrEqual(maxSourcePreviewMs);

      await testInfo.attach(`core-performance-${locale}.json`, {
        body: Buffer.from(JSON.stringify({ locale, metrics }, null, 2)),
        contentType: 'application/json',
      });

      // The preview is a full-screen overlay: leave it open and the recovery
      // turn's error card sits behind it, so the "Try again" click would be
      // intercepted. Dismiss it the way an operator does, then prove the
      // overlay is really gone before driving the composer again.
      await page.getByRole('button', { name: 'Close preview' }).click();
      await expect(pdfViewer, 'the preview overlay must be dismissed before recovery').toBeHidden();

      let forced = false;
      await page.route('**/api/v1/chat/stream**', async (route) => {
        if (!forced) {
          forced = true;
          await route.abort('connectionfailed');
          return;
        }
        await route.continue();
      });
      const citationsBeforeRecovery = await citations.count();
      await composer.fill(evidence.retry);
      await composer.press('Enter');
      // Scoped to the failed turn's own card: the readiness banner near the
      // composer carries the very same "Try again" / "Réessayer" label and sits
      // after the message list, so a page-wide `.last()` would grab that one.
      const failureCard = page.locator(`xpath=${turnScope}/following::app-chat-error-card`).last();
      const retry = failureCard.getByRole('button', { name: /Try again|Réessayer/i });
      await expect(retry).toBeVisible({ timeout: 15_000 });
      await retry.click();
      // Recovery replaces the failed turn: the error card goes away and a new
      // cited answer lands. Counting rules out the previous answer's chips.
      await expect(failureCard, 'retrying must clear the failed turn').toBeHidden({ timeout: maxFirstAnswerMs });
      await expect
        .poll(() => citations.count(), {
          message: 'the recovered turn must produce a new cited answer',
          timeout: maxFirstAnswerMs,
        })
        .toBeGreaterThan(citationsBeforeRecovery);
    });
  }
});
