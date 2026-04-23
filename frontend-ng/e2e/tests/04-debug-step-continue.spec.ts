import { expect, test } from '@playwright/test';
import { loginAsAlice } from '../fixtures/auth';

/**
 * E2.04 — Debug step/continue flow.
 *
 * Exercises the debugger UI :
 * 1. Start a run in debug mode (breakpoint before the first skill).
 * 2. **Step** through skill #1 — UI shows `invocation:1 completed`.
 * 3. **Continue** — run resumes until the DAG terminates.
 * 4. Outcome block renders with decision + confidence.
 *
 * The system under test (`debug-demo`) has a 2-skill sequential DAG so
 * there's exactly one `Step` worth doing. Fixture is seeded by
 * `scripts/test-vm.sh seed:debug`.
 */
test.describe('E2.04 — Debug step/continue', () => {
  test('runs step → continue, lands on outcome', async ({ page, request }) => {
    await loginAsAlice(page);

    const systemsRes = await request.get('/api/v1/systems?q=debug-demo');
    const systems = await systemsRes.json();
    const system = Array.isArray(systems?.items) ? systems.items[0] : null;
    test.skip(!system, 'debug-demo fixture not seeded on the target env');

    const runRes = await request.post(`/api/v1/systems/${system.id}/execute`, {
      data: {
        input: { query: 'Debug flow trigger' },
        mode: 'debug',
      },
    });
    const run = await runRes.json();
    expect(run.id).toBeTruthy();

    await page.goto(`/runs/${run.id}?mode=debug`);

    const stepButton = page.getByRole('button', { name: /^step$/i }).first();
    await expect(stepButton).toBeVisible({ timeout: 20_000 });
    await stepButton.click();

    await expect(page.locator('body')).toContainText(/invocation.*1.*completed|skill 1/i, {
      timeout: 20_000,
    });

    const continueButton = page.getByRole('button', { name: /continue|resume/i }).first();
    await continueButton.click();

    await expect(page.locator('body')).toContainText(/completed/i, {
      timeout: 30_000,
    });
    await expect(page.locator('body')).toContainText(/decision|confidence/i);
  });
});
