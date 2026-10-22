import { expect, test, type Page, type Route } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/** Local browser contracts only. These fixtures do not qualify provider accounting or budget admission. */
const workspace = { id: 'usage-qa', slug: 'usage-qa', name: 'Usage QA', role: 'owner', role_template: 'workspace_owner', settings: {} };
const coverage = { complete: true, mode: 'complete_retained_calls', scanned: 23, limit: 20000 };
const summary = {
  counts: { calls: 23, dispatched: 21, completed: 18, failed: 2, unknown: 1, blocked: 2 },
  tokens: { input: 21432, output: 1350, total: 22782, cached_input: 4000, cache_write: null, reasoning: 230, known_calls: 20, unknown_calls: 1 },
  costs: [{ currency: 'USD', known_amount: '0.33021', known_calls: 18, unknown_calls: 1, basis: 'provider_tokens_at_versioned_tariff' }, { currency: 'EUR', known_amount: '0', known_calls: 2, unknown_calls: 0, basis: 'provider_tokens_at_versioned_tariff' }],
  groups: [{ provider: 'openai', model: 'gpt-demo', purpose: 'agent_decision', system_id: 'system-1', traffic: 'business', currency: 'USD', calls: 19, total_tokens: 20000, known_amount: '0.33021' }, { provider: 'local', model: 'local-model', purpose: 'judge', system_id: 'system-1', traffic: 'evaluation', currency: 'EUR', calls: 2, total_tokens: 2782, known_amount: '0' }], coverage,
};
const call = { id: 'call-1', run_id: 'run-1', system_id: 'system-1', root_system_id: 'system-1', invocation_id: 'invocation-1', job_id: null, campaign_id: null, evaluation_id: null, purpose: 'agent_decision', traffic: 'business', provider: 'openai', model: 'gpt-demo', returned_model: 'gpt-demo-2026', status: 'completed', started_at: '2026-10-22T08:00:00Z', completed_at: '2026-10-22T08:00:01Z', latency_ms: 1000, input_tokens: 1000, output_tokens: 50, total_tokens: 1050, cached_input_tokens: 100, cache_write_tokens: null, reasoning_tokens: 10, amount: '0.012', currency: 'USD', cost_basis: 'provider_tokens_at_versioned_tariff', usage_coverage: 'provider_reported', diagnostic: null };
const budget = { id: 'budget-1', scope: 'workspace', system_id: null, revision: 4, enabled: true, timezone: 'Europe/Paris', max_tokens: 1000000, currency_limits: { USD: '100' }, activated_at: '2026-10-01T00:00:00Z', current_period: { start: '2026-10-01T00:00:00Z', end: '2026-11-01T00:00:00Z', consumed_tokens: 100000, reserved_tokens: 20000, amounts: [{ currency: 'USD', consumed: '32', reserved: '8', limit: '100' }] }, history: [{ revision: 4, at: '2026-10-01T00:00:00Z', actor: 'qa', changes: { enabled: true } }] };

async function fixture(page: Page, locale: 'fr' | 'en', admin = true, includeProvenance = false) {
  const queries: URLSearchParams[] = [], writes: Record<string, unknown>[] = [], tariffWrites: Record<string, any>[] = [];
  const retainedTariff = { id:'retained-tariff',revision:2,provider:'openai',model:'gpt-demo',currency:'EUR',rates:{input_per_million:'1.15',output_per_million:'9.2'},provenance:{reference:'Retained provider price',observed_on:'2026-10-20',conversion:{source_currency:'USD',source_rates:{input_per_million:'1.25',output_per_million:'10'},rate:'0.92',reference:'Retained treasury convention',observed_on:'2026-10-20',convention:'target_per_source',rounding:'half_even_12dp'}}};
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.continue() : route.fulfill({ status: 204, body: '' }));
  await page.addInitScript(({ locale, slug }) => { localStorage.setItem('agentium_token', 'Bearer local-usage-fixture'); localStorage.setItem('agentium_workspace_slug', slug); localStorage.setItem('agentium_locale', locale); localStorage.setItem('agentium_theme', locale === 'fr' ? 'dark' : 'light'); }, { locale, slug: workspace.slug });
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname.replace(/^\/api\/v1/, '');
    if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa', role: 'member', email: 'qa@example.test' });
    if (path === '/auth/me') return json(route, { id: 'qa', role: 'member', email: 'qa@example.test', is_active: true, workspaces: [workspace] });
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === '/auth/workspaces/' + workspace.slug) return json(route, workspace);
    if (path === '/systems') return json(route, [{ id: 'system-1', name: 'Customer service' }, { id: 'system-2', name: 'Document review' }]);
    if (path === '/observability/activities/features') return json(route, { enabled: true, scopes: ['workspace'], kinds: [], statuses: [] });
    if (path === '/observability/usage/summary') { queries.push(url.searchParams); return json(route, summary); }
    if (path === '/observability/usage/series') return json(route, { timezone: 'UTC', buckets: [{ ...summary, counts: { ...summary.counts, dispatched: 14 }, date: '2026-10-21' }, { ...summary, counts: { ...summary.counts, dispatched: 7 }, costs: [{ currency: 'USD', known_amount: null, known_calls: 0, unknown_calls: 7, basis: 'provider_tokens_at_versioned_tariff' }], date: '2026-10-22' }] });
    if (path === '/observability/usage/calls') { const offset = Number(url.searchParams.get('offset') || 0); return json(route, { items: [{ ...call, id: offset ? 'call-26' : call.id, ...(includeProvenance ? {currency:'EUR',amount:'0.00000038',tariff_snapshot:retainedTariff} : {}) }], total: 30, offset, limit: 25, coverage }); }
    if (path === '/observability/usage/budgets' && request.method() === 'POST') { writes.push(request.postDataJSON()); return json(route, { ...budget, ...request.postDataJSON(), id: 'budget-2', revision: 1 }); }
    if (path === '/observability/usage/budgets') return json(route, { items: admin ? [budget] : [], can_manage: admin, readiness: { ready: false, code: 'USAGE_ROLLOUT_UNVERIFIED', missing_transports: [] } });
    if (path === '/observability/usage/tariffs' && request.method() === 'POST') { const body=request.postDataJSON();tariffWrites.push(body);return json(route,{...body,id:'new-tariff',revision:3}); }
    if (path === '/observability/usage/tariffs') return json(route, { can_manage: admin, items: [{ id: 'tariff-1', revision: 2, provider: 'openai', model: 'gpt-demo', currency: 'USD', rates: { input_per_million: '1.25', output_per_million: '10', cached_input_per_million: null } },...tariffWrites.map(body=>({...body,id:'new-tariff',revision:3}))] });
    return json(route, request.method() === 'GET' && path.endsWith('s') ? [] : {});
  });
  return { queries, writes, tariffWrites };
}

test.describe('Usage and budgets — isolated browser contracts', () => {
  test.beforeEach(async ({}, info) => { test.skip(!['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Loopback fixture only.'); });
  for (const [locale, width] of [['fr', 1440], ['en', 390]] as const) {
    test(`${locale}/${width}: scoped consumption, evidence, accessible budgets and explicit activation`, async ({ page }, info) => {
      const state = await fixture(page, locale), en = locale === 'en';
      await page.setViewportSize({ width, height: 1050 });
      await page.goto('/observability?facet=usage&systemId=system-1&since=90d&traffic=business&as_of=2026-10-22T10%3A00%3A00Z');
      const usage = page.locator('app-usage-dashboard');
      await expect(usage.getByRole('heading', { name: en ? 'Usage and costs' : 'Usage et coûts', exact: true })).toBeVisible();
      await expect(usage.locator('app-usage-summary')).toContainText('21');
      expect(state.queries.at(-1)?.get('window')).toBe('90d'); expect(state.queries.at(-1)?.get('traffic')).toBe('business'); expect(state.queries.at(-1)?.get('system_id')).toBe('system-1');
      await expect(usage.getByRole('link', { name: en ? 'View invocation' : 'Voir l’appel' }).first()).toHaveAttribute('href', /run-1.*invocation-1/);
      await usage.getByRole('combobox', { name: 'Population', exact: true }).selectOption('evaluation');
      await expect.poll(() => state.queries.at(-1)?.get('traffic')).toBe('evaluation');
      const anchor = page.locator('[data-testid="observation-window"] time');
      await expect(anchor).toContainText('UTC'); await expect(anchor).not.toContainText('T10:00');
      expect(await usage.locator('.bar-fill').first().evaluate(element => element.getBoundingClientRect().width)).toBeLessThanOrEqual(32);
      await usage.locator('.bar-column').first().focus(); await expect(usage.locator('.bar-tooltip').first()).toBeVisible();
      await usage.getByRole('combobox', { name: en ? 'Measure' : 'Mesure', exact: true }).selectOption('USD');
      await expect(usage.locator('.bar-column.unknown')).toHaveCount(1);
      await expect(usage.locator('.chart-legend')).toContainText(en ? 'missing measurement' : 'mesure absente');
      await usage.getByRole('combobox', { name: en ? 'Measure' : 'Mesure', exact: true }).selectOption('calls');
      expect((await new AxeBuilder({ page }).include('app-usage-dashboard').analyze()).violations).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await usage.locator('.bar-column').first().evaluate(element => (element as HTMLElement).blur());
      await usage.getByRole('heading', { name: en ? 'Usage and costs' : 'Usage et coûts', exact: true }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath(`usage-${locale}-${width}.png`), fullPage: true });
      await usage.getByRole('button', { name: en ? 'Budgets' : 'Budgets', exact: true }).click();
      const budgets = usage.locator('app-usage-budgets');
      await expect(budgets.getByText('Europe/Paris', { exact: false }).first()).toBeVisible();
      await expect(budgets.getByText(en ? 'available' : 'disponibles', { exact: false }).first()).toBeVisible();
      await budgets.getByRole('button', { name: en ? 'Configure a budget' : 'Configurer un budget' }).click();
      const editor = budgets.locator('form').first();
      await editor.getByRole('combobox', { name: en ? 'Scope' : 'Périmètre', exact: true }).selectOption('system');
      await editor.getByRole('combobox', { name: en ? 'Application / System' : 'Application / Système', exact: true }).selectOption('system-2');
      await editor.getByLabel(en ? 'Monthly token limit' : 'Plafond mensuel de jetons').fill('120000');
      await expect(editor.getByRole('button', { name: en ? 'Save and activate' : 'Enregistrer et activer', exact: true })).toBeDisabled();
      expect((await new AxeBuilder({ page }).include('app-usage-budgets').analyze()).violations).toEqual([]);
      await page.screenshot({ path: info.outputPath(`budgets-${locale}-${width}.png`), fullPage: true });
      await editor.getByRole('button', { name: en ? 'Save' : 'Enregistrer', exact: true }).click();
      await expect.poll(() => state.writes.length).toBe(1); expect(state.writes[0]['enabled']).toBe(false); expect(state.writes[0]['expected_revision']).toBe(0); expect(state.writes[0]['system_id']).toBe('system-2');
    });
  }
  test('member cannot configure budgets and absence of access is not shown as absence of budgets', async ({ page }) => {
    await fixture(page, 'en', false); await page.goto('/observability?facet=usage&usageView=budgets');
    const budgets = page.locator('app-usage-budgets');
    await expect(budgets).toContainText('restricted to workspace administrators');
    await expect(budgets.getByRole('button', { name: 'Configure a budget' })).toHaveCount(0);
    await expect(budgets).not.toContainText('No spending limits configured');
  });
  for (const locale of ['fr','en'] as const) test(`${locale}: declared tariff conversion is reviewed before saving and retained on the call`, async ({ page }) => {
    const state=await fixture(page,locale,true,true),en=locale==='en';await page.goto('/observability?facet=usage');
    const calls=page.locator('app-usage-calls');await expect(calls).toContainText(en?'< €0.000001':'< 0,000001');await calls.getByText(en?'Declared conversion':'Conversion déclarée',{exact:true}).click();
    await expect(calls).toContainText('Retained treasury convention');await expect(calls).toContainText(en?'1 USD = 0.92 EUR':'1 USD = 0,92 EUR');
    await page.locator('app-usage-dashboard').getByRole('button',{name:'Budgets',exact:true}).click();const budgets=page.locator('app-usage-budgets');
    await budgets.locator('details.tariffs > summary').click();await expect(budgets).toContainText(en?'Source not recorded':'Source non renseignée');await budgets.getByRole('button',{name:en?'Add tariff':'Ajouter un tarif',exact:true}).click();
    const editor=budgets.locator('form[aria-labelledby="usage-tariff-editor-title"]');await editor.locator('[name="tariffProvider"]').fill('openai');await editor.locator('[name="tariffModel"]').fill('gpt-demo');await editor.locator('[name="tariffCurrency"]').fill('EUR');
    await expect(editor.locator('[name="priceReference"]')).toBeHidden();await editor.locator('.tariff-advanced > summary').click();await editor.locator('[name="priceReference"]').fill('Provider published pricing');await editor.locator('[name="priceObservedOn"]').fill('2026-10-22');await editor.locator('[name="conversionEnabled"]').check();
    await editor.locator('[name="sourceCurrency"]').fill('USD');await editor.locator('[name="conversionRate"]').fill(en?'0.92':'0,92');await editor.locator('[name="rateReference"]').fill('Workspace treasury convention');await editor.locator('[name="rateObservedOn"]').fill('2026-10-21');await editor.getByRole('textbox',{name:en?'Input / million':'Entrée / million',exact:true}).fill('1.25');await editor.getByRole('textbox',{name:en?'Output / million':'Sortie / million',exact:true}).fill('10');
    await editor.getByRole('button',{name:en?'Apply to tariff rates':'Appliquer aux tarifs',exact:true}).click();await expect(editor.locator('[name="tariffInput"]')).toHaveValue('1.15');await expect(editor.locator('[name="tariffOutput"]')).toHaveValue('9.2');expect(state.tariffWrites).toHaveLength(0);
    await editor.locator('[name="tariffInput"]').fill('1.16');await editor.getByRole('button',{name:en?'Save this version':'Enregistrer cette version',exact:true}).click();await expect(budgets).toContainText(en?'Rates no longer match':'Les tarifs ne correspondent plus');expect(state.tariffWrites).toHaveLength(0);
    await editor.getByRole('button',{name:en?'Apply to tariff rates':'Appliquer aux tarifs',exact:true}).click();expect((await new AxeBuilder({page}).include('app-usage-budgets').analyze()).violations).toEqual([]);await editor.getByRole('button',{name:en?'Save this version':'Enregistrer cette version',exact:true}).click();await expect.poll(()=>state.tariffWrites.length).toBe(1);
    expect(state.tariffWrites[0].currency).toBe('EUR');expect(state.tariffWrites[0].input_per_million).toBe('1.15');expect(state.tariffWrites[0].provenance.conversion).toEqual({source_currency:'USD',source_rates:{input_per_million:'1.25',output_per_million:'10'},rate:'0.92',reference:'Workspace treasury convention',observed_on:'2026-10-21',convention:'target_per_source',rounding:'half_even_12dp'});
  });

});
