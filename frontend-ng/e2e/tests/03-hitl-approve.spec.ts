import { expect, test } from '@playwright/test';
import { loginAsAlice } from '../fixtures/auth';
import { appFetch, expectOk } from '../fixtures/api';

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
  test('run pauses at HITL, operator accepts, resumes to completed', async ({ page }) => {
    await loginAsAlice(page);

    const system = await expectOk<{ id: string }>(page, '/api/v1/systems', {
      method: 'POST',
      data: {
        name: `e2e-hitl-${Date.now()}`,
        objective: 'E2E HITL smoke fixture',
        status: 'active',
        flow_definition: {
          schema_version: 2,
          nodes: [
            { id: 'src', kind: 'source' },
            { id: 'h', kind: 'hitl', config: { prompt: 'Approve E2E run?' } },
            { id: 'sink', kind: 'sink' },
          ],
          edges: [
            { from: 'src', to: 'h' },
            { from: 'h', to: 'sink' },
          ],
        },
      },
    });

    const run = await expectOk<{ id: string }>(page, `/api/v1/systems/${system.id}/runs`, {
      method: 'POST',
      data: {
        input_ref: { query: 'Is this document reliable? Hedge if unsure.' },
        trigger: 'manual',
      },
    });
    expect(run.id).toBeTruthy();

    await expect
      .poll(async () => {
        const res = await appFetch<{ status?: string }>(page, `/api/v1/runs/${run.id}`);
        return res.body.status;
      }, { timeout: 30_000 })
      .toBe('hitl_pending');

    await page.goto(`/runs/${run.id}`);
    await expect(page.locator('body')).toContainText(/hitl_pause|Approve E2E run|HITL/i, {
      timeout: 30_000,
    });

    await expectOk(page, `/api/v1/runs/${run.id}/hitl`, {
      method: 'POST',
      data: { action: 'accept', actor: 'playwright' },
    });

    await expect
      .poll(async () => {
        const res = await appFetch<{ status?: string }>(page, `/api/v1/runs/${run.id}`);
        return res.body.status;
      }, { timeout: 30_000 })
      .toBe('completed');
    await page.reload();
    await expect(page.locator('body')).toContainText(/completed/i);

    await appFetch(page, `/api/v1/systems/${system.id}`, { method: 'DELETE' });
  });
});
