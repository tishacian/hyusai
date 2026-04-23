import path from 'node:path';
import { expect, test } from '@playwright/test';
import { loginAsAlice } from '../fixtures/auth';

/**
 * E2.02 — Chat drop-and-ask with citations.
 *
 * Covers the happy-path RAG flow :
 * 1. Drop two PDF onto the chat workspace.
 * 2. Wait for ingest → chunks available in the session ephemeral
 *    knowledge base.
 * 3. Ask a question answerable from the PDFs.
 * 4. The assistant response includes at least one `[1]` citation chip.
 * 5. Clicking the chip expands the sources panel and scrolls to the
 *    matching source entry.
 *
 * The two PDFs used here live in `e2e/fixtures/docs/` and are tiny
 * (<100 KB each) to keep CI fast. They're committed to the repo —
 * don't stick a real client doc in here.
 */
test.describe('E2.02 — Chat drop-and-ask', () => {
  const PDF_A = path.join(__dirname, '..', 'fixtures', 'docs', 'sample-a.pdf');
  const PDF_B = path.join(__dirname, '..', 'fixtures', 'docs', 'sample-b.pdf');

  test('drops 2 PDF, asks, clicks citation chip', async ({ page }) => {
    await loginAsAlice(page);

    await page.goto('/chat');
    await expect(page.locator('body')).toContainText(/Chat|Session docs/i);

    const fileInput = page.locator('input[type="file"]').first();
    await fileInput.setInputFiles([PDF_A, PDF_B]);

    await expect(page.locator('body')).toContainText(/sample-a|sample-b/, {
      timeout: 30_000,
    });

    const chatInput = page.locator(
      'textarea, input[type="text"][placeholder*="Ask"]',
    ).first();
    await chatInput.fill(
      'According to the attached documents, what is the main conclusion?',
    );
    await chatInput.press('Enter');

    // Streaming response — wait for completion signal (citation chips
    // only render once the stream reaches `[[CITE:...]]` placeholders).
    const citation = page.locator('[data-cite-chip], button:has-text("[1]")').first();
    await expect(citation).toBeVisible({ timeout: 90_000 });

    await citation.click();
    const sourcesPanel = page.locator('[data-sources-panel], aside:has-text("Sources")');
    await expect(sourcesPanel).toBeVisible();
    await expect(sourcesPanel).toContainText(/sample-a|sample-b/);
  });
});
