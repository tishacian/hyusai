import { expect, test } from '@playwright/test';
import { loginAsAlice } from '../fixtures/auth';

/**
 * E2.03 — HITL (human-in-the-loop) approve flow.
 *
 * Requires a system seeded with a control policy that forces a
 * `hitl_pending` checkpoint when `confidence < 0.5`. The fixture is
 * created by `scripts/test-vm.sh seed:hitl` and produces :
 *   - workspace: `playwright-staging`
 *   - system: `hitl-demo` (confidence threshold = 0.5)
 *   - prompt: a deliberately ambiguous question that scores low.
 *
 * The test :
 * 1. Triggers a run against the `hitl-demo` system.
 * 2. Waits for the run to transition to `hitl_pending`.
 * 3. Opens `/runs/:id`, hits **Approve**, expects the run to resume
 *    and reach `completed`.
 */
test.describe('E2.03 — HITL Approve', () => {
  test('run pauses at HITL, operator accepts, resumes to completed', async ({
    page,
    request,
  }) => {
    await loginAsAlice(page);

    const systemsRes = await request.get('/api/v1/systems?q=hitl-demo');
    const systems = await systemsRes.json();
    const system = Array.isArray(systems?.items) ? systems.items[0] : null;
    test.skip(!system, 'hitl-demo fixture not seeded on the target env');

    const runRes = await request.post(`/api/v1/systems/${system.id}/execute`, {
      data: {
        input: { query: 'Is this document reliable? Hedge if unsure.' },
        mode: 'sync',
      },
    });
    const run = await runRes.json();
    expect(run.id).toBeTruthy();

    await page.goto(`/runs/${run.id}`);
    await expect(page.locator('body')).toContainText(/hitl_pending|awaiting approval/i, {
      timeout: 30_000,
    });

    const approveButton = page
      .getByRole('button', { name: /approve|accept/i })
      .first();
    await approveButton.click();

    await expect(page.locator('body')).toContainText(/completed/i, {
      timeout: 30_000,
    });
  });
});
