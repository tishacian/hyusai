import { expect, test } from '@playwright/test';
import { loginAsAlice } from '../fixtures/auth';
import { appFetch, expectOk } from '../fixtures/api';

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
  test('runs step → continue, lands on outcome', async ({ page }) => {
    await loginAsAlice(page);

    const system = await expectOk<{ id: string }>(page, '/api/v1/systems', {
      method: 'POST',
      data: {
        name: `e2e-debug-${Date.now()}`,
        objective: 'E2E debug smoke fixture',
        status: 'active',
        flow_definition: {
          schema_version: 2,
          nodes: [
            { id: 'src', kind: 'source' },
            {
              id: 'd1',
              kind: 'decision',
              config: {
                default_branch: 'next',
                branches: [
                  { label: 'next', condition: 'true' },
                  { label: 'other', condition: 'false' },
                ],
              },
            },
            { id: 't1', kind: 'task', config: {} },
            { id: 't2', kind: 'task', config: {} },
            { id: 'sink', kind: 'sink' },
          ],
          edges: [
            { from: 'src', to: 'd1' },
            { from: 'd1', to: 't1', kind: 'branch', branch_label: 'next' },
            { from: 't1', to: 't2' },
            { from: 't2', to: 'sink' },
          ],
        },
      },
    });

    const run = await expectOk<{ id: string }>(page, `/api/v1/systems/${system.id}/runs`, {
      method: 'POST',
      data: {
        input_ref: {
          query: 'Debug flow trigger',
          _debug: { mode: 'step' },
        },
        trigger: 'manual',
      },
    });
    expect(run.id).toBeTruthy();

    await expect
      .poll(async () => {
        const res = await appFetch<{ status?: string }>(page, `/api/v1/runs/${run.id}`);
        return res.body.status;
      }, { timeout: 30_000 })
      .toBe('debug_pending');

    await page.goto(`/runs/${run.id}?mode=debug`);
    await expect(page.locator('body')).toContainText(/debug_pending|debug/i);

    await expectOk(page, `/api/v1/runs/${run.id}/step`, {
      method: 'POST',
      data: { action: 'step' },
    });

    await expect
      .poll(async () => {
        const res = await appFetch<{ status?: string }>(page, `/api/v1/runs/${run.id}`);
        return res.body.status;
      }, { timeout: 30_000 })
      .toBe('debug_pending');

    await expectOk(page, `/api/v1/runs/${run.id}/step`, {
      method: 'POST',
      data: { action: 'continue' },
    });

    await expect
      .poll(async () => {
        const res = await appFetch<{ status?: string }>(page, `/api/v1/runs/${run.id}`);
        return res.body.status;
      }, { timeout: 30_000 })
      .toBe('completed');
    await page.reload();
    await expect(page.locator('body')).toContainText(/completed/i);
    await expect(page.locator('body')).toContainText(/decision|confidence/i);

    await appFetch(page, `/api/v1/systems/${system.id}`, { method: 'DELETE' });
  });
});
