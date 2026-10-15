import { expect, test } from '@playwright/test';
import { loginAsAlice } from '../fixtures/auth';
import { expectOk } from '../fixtures/api';

/** Explicit opt-in, read-only deployment canary. It does not qualify worker restart, broker recovery or cancellation. */
test('activity journal deployment: authenticated list, native evidence and detail', async ({ page }, info) => {
  test.skip(process.env['E2E_ACTIVITY_OBSERVABILITY_CANARY'] !== '1', 'Requires an explicitly chosen canary deployment with activity_observability_enabled.');
  await loginAsAlice(page);
  const features = await expectOk<{ enabled: boolean; scopes: string[] }>(page, '/api/v1/observability/activities/features');
  expect(features.enabled).toBe(true);
  const result = await expectOk<{ items: Array<{ id: string; native_id: string; version: number }>; total: number; snapshot_cursor: string }>(page, '/api/v1/observability/activities?limit=25&offset=0');
  expect(result.total).toBeGreaterThanOrEqual(result.items.length); expect(result.snapshot_cursor).toBeTruthy();
  test.skip(!result.items.length, 'Create a real fixture activity in this deployment before running the read-only canary.');
  const activity = result.items[0];
  await page.goto(`/observability?activityId=${encodeURIComponent(activity.id)}`);
  const detail = page.getByTestId('activity-detail');
  await expect(detail).toContainText(activity.native_id);
  await expect(detail.getByRole('heading', { name: /Chronologie|Timeline/ })).toBeVisible();
  const canonical = await expectOk<{ id: string; native_id: string; version: number; coverage: unknown; links: Array<{ href: string }> }>(page, `/api/v1/observability/activities/${encodeURIComponent(activity.id)}`);
  expect(canonical.id).toBe(activity.id); expect(canonical.version).toBeGreaterThanOrEqual(activity.version); expect(canonical.coverage).toBeTruthy();
  for (const link of canonical.links) expect(link.href).toMatch(/^\/(?!\/)/);
  await page.reload(); await expect(page.getByTestId('activity-detail')).toContainText(activity.native_id);
  if (!features.scopes.includes('platform')) await expect(page.getByTestId('activity-monitor').getByRole('button', { name: /^(Platform|Plateforme)$/ })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('activity-canary.png'), fullPage: true });
  info.annotations.push({ type: 'coverage', description: 'Read-only API/UI canary. No cancellation, production restart, load or broker-failure qualification.' });
});
