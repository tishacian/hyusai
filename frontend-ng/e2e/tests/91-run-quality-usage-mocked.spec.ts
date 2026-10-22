import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';

test.use({ serviceWorkers: 'block', video: 'off', reducedMotion: 'reduce' });
const workspace = { id: 'assurance-workspace', slug: 'assurance-workspace', name: 'Service operations', role: 'owner', role_template: 'workspace_owner', settings: { features: { hypervisor_v2: true } } };
const usage = {
  counts: { calls: 4, dispatched: 3, completed: 2, failed: 0, unknown: 1, blocked: 1 },
  tokens: { input: 1200, output: 300, total: 1500, cached_input: 200, cache_write: null, reasoning: 100, known_calls: 2, unknown_calls: 1 },
  costs: [{ currency: 'USD', known_amount: '0.003', known_calls: 1, unknown_calls: 1, basis: 'tariff' }, { currency: 'EUR', known_amount: '0', known_calls: 1, unknown_calls: 0, basis: 'tariff' }],
  groups: [], coverage: { mode: 'ledger', complete: true, scanned: 4, limit: 20000 },
};
const quality = { records: [], has_more: false, totals: { evaluations: 9, distinct_runs: 9, technical_failures: 9, completed: 0, partial: 0, assessed: 0, passed: 0, failed: 0, unassessed: 9, pass_rate: null, pass_rate_denominator: 0, questions_total: 9, questions_answered: 0, evidence_unavailable: 0, reviewed: 0 } };
const views = [{ id: 'service', label: 'Service quality', period: '7d', denominator: 'runs', system_id: 'service-system', schema_version: 2,
  strata: { comprendre: [{ type: 'quality', settings: { traffic: 'evaluation' } }, { type: 'ai_usage', settings: { traffic: 'all' } }], detailler: [], decider: [] }, register_columns: [], sort: 'name' }];
async function setup(page: Page, locale: 'fr' | 'en') {
  const requests: URL[] = [], writes: string[] = [], errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => ['127.0.0.1', 'localhost'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.addInitScript(({ locale, slug }) => {
    localStorage.setItem('agentium_token', 'Bearer isolated-assurance-qa');
    localStorage.setItem('agentium_locale', locale); localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_theme', locale === 'fr' ? 'dark' : 'light');
  }, { locale, slug: workspace.slug });
  const json = (route: Route, body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/v1/**', route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname.replace(/^\/api\/v1/, '');
    requests.push(url); if (request.method() !== 'GET') writes.push(path);
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa', role: 'admin' });
    if (path === '/auth/me') return json(route, { id: 'qa', role: 'admin', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === '/auth/workspaces/' + workspace.slug) return json(route, workspace);
    if (path === '/runs/run-proof') return json(route, { id: 'run-proof', system_id: 'service-system', status: 'completed', started_at: '2026-10-22T09:00:00Z', completed_at: '2026-10-22T09:01:00Z', skill_invocations: [], output_data: { summary: 'A proposal is available for review.' } });
    if (path.endsWith('/files') || path === '/systems' || path === '/capabilities') return json(route, []);
    if (path === '/observability/activities/features') return json(route, { execution_view_enabled: false, journal_enabled: true, series_enabled: true });
    if (path === '/evaluation/summary' || path === '/evaluation/by-run/run-proof/summary') return json(route, quality);
    if (path === '/evaluation/by-run/run-proof') return json(route, { status: 'unavailable' });
    if (path === '/observability/usage/summary') return json(route, usage);
    if (path === '/observability/usage/calls') return json(route, { items: [], total: 0, offset: 0, limit: 10, coverage: usage.coverage });
    if (path === '/hypervisor/views') return json(route, { views, default_view_id: 'service', can_edit: false });
    if (path === '/hypervisor/activity/systems') return json(route, { systems: [{ id: 'service-system', name: 'Service desk' }] });
    if (path === '/hypervisor/series') return json(route, { window: '7d', from: '2026-10-16', to: '2026-10-22', systems: [] });
    if (path === '/ml-operations/features') return json(route, { enabled: false });
    if (path === '/hypervisor/decisions' || path === '/hypervisor/recommendations' || path === '/hypervisor/value-bases') return json(route, { items: [] });
    return json(route, {});
  });
  return { requests, writes, errors };
}

for (const locale of ['fr', 'en'] as const) {
  test(`${locale}: Run navigation retains context and browser history without executing anything`, async ({ page }, info) => {
    await page.setViewportSize({ width: locale === 'fr' ? 1440 : 390, height: 900 });
    const state = await setup(page, locale);
    await page.goto('/runs/run-proof?facet=quality&lens=operate');
    const nav = page.getByTestId('run-sections');
    await expect(nav.getByRole('link')).toHaveCount(4);
    await expect(page.getByTestId('evaluation-records')).toBeVisible();
    await expect(page.locator('app-run-usage')).toHaveCount(0);
    await nav.getByRole('link', { name: locale === 'fr' ? 'Usage et coûts' : 'Usage and costs', exact: true }).click();
    await expect(page.locator('app-run-usage app-usage-summary')).toBeVisible();
    await expect(page.locator('app-evaluation-records')).toHaveCount(0);
    expect(new URL(page.url()).searchParams.get('lens')).toBe('operate');
    await expect(page.locator('app-usage-summary .money')).toHaveCount(2);
    await expect(page.locator('app-usage-summary .money').first()).toContainText('$');
    await expect(page.locator('app-usage-summary .money').last()).toContainText('€');
    expect(state.requests.filter(url => url.pathname.endsWith('/observability/usage/summary')).every(url => url.searchParams.get('run_id') === 'run-proof')).toBe(true);
    await page.screenshot({ path: info.outputPath(`run-usage-${locale}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect((await new AxeBuilder({ page }).include('app-run-page').analyze()).violations).toEqual([]);
    await page.goBack();
    await expect(page.getByTestId('evaluation-records')).toBeVisible();
    await expect(nav.getByRole('link', { name: locale === 'fr' ? 'Qualité' : 'Quality', exact: true })).toHaveAttribute('aria-current', 'page');
    expect(state.writes.filter(path => !path.startsWith('/auth/') && path !== '/audit' && !path.includes('/navigation'))).toEqual([]);
    expect(state.errors).toEqual([]);
  });

  test(`${locale}: configurable Impact blocks keep QA, unknown quality and separate currencies honest`, async ({ page }, info) => {
    await page.setViewportSize({ width: locale === 'fr' ? 1440 : 390, height: 900 });
    const state = await setup(page, locale);
    await page.goto('/hypervisor');
    const qualityBlock = page.getByTestId('impact-quality'), usageBlock = page.getByTestId('impact-ai_usage');
    await expect(qualityBlock).toBeVisible(); await expect(usageBlock).toBeVisible();
    await expect(qualityBlock.locator('dd').nth(2).locator('span')).toHaveText('—');
    await expect(qualityBlock.locator('dd').nth(3)).toHaveText('9');
    expect(state.requests.some(url => url.pathname.endsWith('/evaluation/summary') && url.searchParams.get('system_id') === 'service-system' && url.searchParams.get('traffic') === 'evaluation')).toBe(true);
    const link = qualityBlock.getByRole('link');
    await expect(link).toHaveAttribute('href', /traffic=evaluation/);
    await expect(link).toHaveAttribute('href', /systemId=service-system/);
    await expect(link).toHaveAttribute('href', /as_of=/);
    await expect(usageBlock.locator('.money span')).toHaveCount(2);
    await expect(usageBlock).not.toContainText('700');
    await page.screenshot({ path: info.outputPath(`impact-assurance-${locale}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect((await new AxeBuilder({ page }).include('app-impact-assurance').analyze()).violations).toEqual([]);
    expect(state.writes.filter(path => !path.startsWith('/auth/') && path !== '/audit')).toEqual([]);
    expect(state.errors).toEqual([]);
  });
}
