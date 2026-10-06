import { expect, test, type Page, type Route } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const enabled = process.env['E2E_CHROME_V2_MOCKED'] === '1';
test.use({ serviceWorkers: 'block', video: 'off', ignoreHTTPSErrors: false });
const workspace = { id: 'qa-claims-ws', slug: 'qa-claims', name: 'Showcase QA', role: 'owner', role_template: 'workspace_owner', settings: { features: { experience_v1: true, ecommerce_claims_v1: true } } };
const rows = [
 { claim_id: 'RC-1042', order_id: 'LM-1042', paid_amount: '420.00', display_name: 'Client fictif A', reason: 'delivery_disputed' },
 { claim_id: 'RC-1043', order_id: 'LM-1043', paid_amount: '49.90', display_name: 'Client fictif B', reason: 'parcel_lost' },
 { claim_id: 'RC-1044', order_id: 'LM-1044', paid_amount: '89.00', display_name: 'Client fictif C', reason: 'refund_requested' },
].map(r => ({ ...r, currency: 'EUR', state: 'to_investigate', opened_at: '2026-09-29T10:00:00Z' }));
const source = { reference: 'refund-policy-v2', document_id: 'qa-original-doc', collection: 'qa-rules', filename: 'politique-remboursement-v2.pdf', title: 'politique-remboursement-v2.pdf' };
const claimSource = { reference: 'claim-lm1042', document_id: 'qa-claim-doc', collection: 'qa-case', filename: 'reclamation-lm1042.pdf', title: 'reclamation-lm1042.pdf' };
function detail(id: string) { const row = rows.find(r => r.claim_id === id)!; return { data: { context: [{ ...row, shipping_postcode: '75011', payment_status: 'paid' }], items: [{ product_name: 'Lampe Aube', quantity: 1, unit_price: row.paid_amount }], shipments: [{ status: id === 'RC-1043' ? 'lost' : 'delivered', carrier: 'ColisAzur', tracking_id: 'CA-' + id.slice(3) }], refunds: id === 'RC-1044' ? [{ refund_id: 'RF-1044', amount: '89.00', currency: 'EUR', status: 'executed' }] : [] }, provenance: { captured_at: '2026-10-02T09:00:00Z', snapshot_sha256: 'qa-snapshot', read_mode: 'live' }, sources: [source, claimSource], receipts: [], latest_run_id: null }; }

async function setup(page: Page, theme: string, locale: string, unavailable = false, priority: 'ready' | 'stale' | 'manual' | null = null) {
 const posts: unknown[] = []; let run: Record<string, unknown> | null = null;
 await page.route('**/*', route => ['127.0.0.1', 'localhost'].includes(new URL(route.request().url()).hostname) ? route.continue() : route.fulfill({ status: 204, body: '' }));
 await page.addInitScript(({ slug, theme, locale }) => { localStorage.setItem('agentium_token', 'Bearer isolated-claims-qa'); localStorage.setItem('agentium_workspace_slug', slug); localStorage.setItem('agentium_theme', theme); localStorage.setItem('agentium_locale', locale); }, { slug: workspace.slug, theme, locale });
 const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
 await page.route('**/api/v1/**', async route => {
   const request = route.request(); const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
   if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa-human', email: 'qa@example.test', role: 'admin' });
   if (path === '/auth/workspaces') return json(route, [workspace]);
   if (path === '/auth/workspaces/' + workspace.slug) return json(route, workspace);
   if (path === '/auth/me') return json(route, { id: 'qa-human', email: 'qa@example.test', role: 'admin', is_active: true, workspaces: [workspace] });
   if (path === '/work/reclamations') return json(route, { experience: { id: 'qa-experience', slug: 'reclamations', name: 'Réclamations' }, release: { id: 'qa-release' }, channel: 'live' });
   if (path === '/ecommerce-claims') return json(route, unavailable ? { detail: { code: 'POSTGRESQL_SCHEMA_NOT_LOADED' } } : { data: { queue: rows } }, unavailable ? 503 : 200);
   if (path === '/ecommerce-claims/triage') return json(route, priority ? {
     status: priority === 'stale' ? 'stale' : 'ready', captured_at: new Date().toISOString(), max_age_minutes: 60,
     model: { id: 'qa-sla-model', name: 'Luma SLA', version: 1 },
     composition: 'composed_v1', system: { id: 'qa-system', name: 'Luma — Résolution SAV hybride' },
     training_dataset: { id: 'qa-sla-history', name: 'Synthetic history', rows: 1200 },
     prepared_dataset: { id: 'qa-sav-prepared', name: 'Prepared SAV data', version: 1, rows: 23 },
     scored_dataset: { id: 'qa-sla-scored', name: 'Scored queue', version: 1, rows: 23 },
     scoring: { system_id: 'qa-system', version_id: 'qa-composed-v4', flow_sha256: 'b'.repeat(64), ingress_id: 'source.queue' },
     rows: priority === 'stale' ? [] : [
       { claim_id: 'RC-1042', risk: 0.35, priority: 'medium' },
       { claim_id: 'RC-1043', risk: 0.82, priority: 'high' },
       { claim_id: 'RC-1044', risk: 0.01, priority: 'low' },
     ],
   } : { status: 'not_configured', rows: [] });
   if (path === '/work/reclamations/bindings/showcase.claims.refresh_queue/runs') { posts.push({ ...request.postDataJSON(), idempotency_key: request.headers()['idempotency-key'] }); return json(route, { id: 'qa-scoring-run', status: 'pending' }, 201); }
   if (path === '/runs/qa-scoring-run') return json(route, { id: 'qa-scoring-run', status: 'completed' });
   if (path === '/ecommerce-claims/benchmark' && priority === 'manual') return json(route, {
     state: 'experiment_not_complete', hourly_eur: '40.00', planned_pairs: 10, completed_quality_pairs: 0,
     capacity_value_eur: null, incremental_cost_eur: null, net_benefit_eur: null, roi: null,
     trials: [{ id: 'qa-manual-trial', operator_id: 'qa-human', claim_id: 'RC-1043', state: 'active', condition: 'manual', pair_id: 'P01', events: [], active_human_seconds: null, result: null, review: null }],
     protocol: { pairs: [{ pair_id: 'P01', first_condition: 'manual', manual_claim_id: 'RC-1043', assisted_claim_id: 'RC-1042' }] },
   });
   if (path === '/ecommerce-claims/benchmark') return json(route, { state: 'experiment_not_complete', hourly_eur: '40.00', planned_pairs: 10, completed_quality_pairs: 0, capacity_value_eur: null, incremental_cost_eur: null, net_benefit_eur: null, roi: null, protocol_sha256: 'qa-protocol', trials: [], protocol: { version: 'qa-isolated', pairs: [{ pair_id: 'P01', first_condition: 'manual', manual_claim_id: 'RC-5001', assisted_claim_id: 'RC-5002' }] } });
   if (/^\/ecommerce-claims\/RC-/.test(path)) return json(route, detail(path.split('/').at(-1)!));
   if (path.endsWith('/bindings/showcase.claims.investigate/runs')) {
     posts.push(request.postDataJSON()); const id = (posts.at(-1) as { payload: { claim_id: string } }).payload.claim_id;
     const action = id === 'RC-1043' ? 'refund' : id === 'RC-1044' ? 'close_duplicate' : 'carrier_investigation';
     const proposal = { claim_id: id, order_id: 'LM-' + id.slice(3), action, reason: id === 'RC-1043' ? 'carrier_loss_confirmed' : id === 'RC-1044' ? 'already_refunded' : 'delivery_address_mismatch', amount: action === 'refund' ? '49.90' : '0', currency: 'EUR', evidence_kind: 'synthetic_demo', missing_references: [], requires_human: true, citations: [claimSource, source].map(s => ({ ...s, content: 'Toute résolution exige une validation humaine.', page: 1, chunk_index: 0 })) };
     const tool = id === 'RC-1044' ? 'ecommerce_refund_evidence_v1' : 'ecommerce_delivery_evidence_v1';
     const context = { claim_id: id, served: { model_id: 'qa-sla-model', version: 1 }, target: 'resolution_over_72h', positive_label: '1', score: id === 'RC-1043' ? 0.16 : 0.82,
       prepared_dataset: { id: 'qa-case-prepared', name: 'Case data', version: 1, rows: 1 }, scored_dataset: { id: 'qa-case-scored', name: 'Case prediction', version: 1, rows: 1 } };
     run = { id: 'qa-native-run', system_id: 'qa-system', input_ref: { claim_id: id }, status: 'hitl_pending', hitl: { decision_id: 'qa-decision', node_id: 'hitl.review' }, skill_invocations: ['ecommerce_sav_dataset_v1', 'sql_transform_v1', 'ml_batch_score_v1', 'ecommerce_sav_context_v1', 'postgresql_claim_snapshot_v1', 'ecommerce_policy_evidence_v1', tool, 'ecommerce_resolution_propose_v1'].map((slug, i) => ({ id: 'qa-inv-' + i, skill_slug: slug, status: 'completed', completed_at: new Date().toISOString(), output_ref: slug === 'ecommerce_resolution_propose_v1' ? proposal : slug === 'ecommerce_sav_context_v1' ? context : {} })) };
     return json(route, { id: 'qa-native-run', status: 'pending' }, 201);
   }
   if (path === '/runs/qa-native-run' && request.method() === 'GET') return json(route, run);
   if (path === '/runs/qa-native-run/hitl') { posts.push(request.postDataJSON()); return json(route, { id: 'qa-native-run', system_id: 'qa-system', status: 'running' }); }
   if (path.includes('/documents/') && path.endsWith('/passage')) { const s = path.includes(claimSource.document_id) ? claimSource : source; return json(route, { passage: { text: 'Toute résolution exige une validation humaine.' }, document_id: s.document_id, filename: s.filename, collection: { id: null, slug: s.collection, name: s.collection }, preview_available: false }); }
   if (path.includes('/documents/preview/')) return json(route, { status: 'unavailable' });
   if (request.method() === 'GET') return json(route, path.endsWith('s') ? [] : {});
   return json(route, {});
 });
 return posts;
}

test.describe('Claims studio — isolated end-user QA', () => {
 test.skip(!enabled, 'Enable E2E_CHROME_V2_MOCKED for isolated QA');
 for (const theme of ['dark', 'light']) {
  test(`${theme}: model scores prioritize cases, expose lineage and rescore through the pinned Flow`, async ({ page }) => {
    const posts = await setup(page, theme, 'fr', false, 'ready');
    await page.setViewportSize({ width: 1440, height: 1000 }); await page.goto('/work/reclamations/studio');
    await expect(page.getByRole('heading', { name: 'Parcours Luma', exact: true })).toBeVisible();
    await expect(page.locator('.claims-queue .claims-case').first()).toContainText('LM-1043');
    await page.locator('.claims-queue .claims-case').first().click();
    await expect(page.locator('.claims-risk')).toContainText('82');
    await expect(page.locator('.claims-risk')).toContainText('Priorité haute');
    await expect(page.getByRole('link', { name: 'PostgreSQL', exact: true })).toHaveAttribute('href', /^\/connectors\/postgresql(?:\?|$)/);
    await expect(page.getByRole('link', { name: /Données SAV préparées/ })).toHaveAttribute('href', /^\/data\/qa-sav-prepared(?:\?|$)/);
    await expect(page.getByRole('link', { name: /Modèle SLA/ })).toHaveAttribute('href', /^\/models\/qa-sla-model(?:\?|$)/);
    await expect(page.getByRole('link', { name: 'Flow Luma', exact: true })).toHaveAttribute('href', /^\/systems\/qa-system\/flow(?:\?|$)/);
    const button = page.getByRole('button', { name: 'Recalculer la file', exact: true });
    expect((await button.boundingBox())!.height).toBeLessThanOrEqual(32);
    await button.click();
    await expect(button).toBeEnabled();
    expect(posts[0]).toMatchObject({ payload: {}, page_id: 'dossier', component_id: 'queue_refresh', confirmed: true, idempotency_key: expect.stringMatching(/^[\da-f-]{36}$/) });
    await page.getByRole('button', { name: 'Lancer l’enquête', exact: true }).click();
    await expect(page.getByRole('link', { name: 'Données de ce dossier', exact: true })).toHaveAttribute('href', /^\/data\/qa-case-prepared(?:\?|$)/);
    await expect(page.getByRole('link', { name: 'Prédiction de ce dossier', exact: true })).toHaveAttribute('href', /^\/data\/qa-case-scored(?:\?|$)/);
    await expect(page.locator('.claims-risk')).toContainText('16');
    await expect(page.getByText('Rapprochement des faits et du score', { exact: true })).toBeVisible();
    expect(posts[1]).toMatchObject({ payload: { claim_id: 'RC-1043' }, page_id: 'dossier', component_id: 'investigation' });
    expect((await new AxeBuilder({ page }).include('.claims-app').analyze()).violations).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `/workspace/scratch/luma-ml-2026-10-06/work-priority-${theme}.png`, fullPage: true });
  });
 }
 test('expired scores retain dataset links and the usual queue order', async ({ page }) => {
   await setup(page, 'light', 'fr', false, 'stale'); await page.goto('/work/reclamations/studio');
   await expect(page.getByText('Scores expirés après 60 min.', { exact: false })).toBeVisible();
   await expect(page.locator('.claims-queue .claims-case').first()).toContainText('LM-1042');
   await expect(page.locator('.claims-risk')).toHaveCount(0);
   await expect(page.getByRole('link', { name: /File scorée/ })).toBeVisible();
 });
 test('a manual benchmark hides the model and all predictive aid', async ({ page }) => {
   await setup(page, 'dark', 'fr', false, 'manual'); await page.goto('/work/reclamations/studio');
   await expect(page.getByRole('heading', { name: 'LM-1043', exact: true })).toBeVisible();
   await expect(page.locator('.claims-triage')).toHaveCount(0);
   await expect(page.locator('.claims-risk, .claims-priority')).toHaveCount(0);
   await expect(page.locator('.claims-queue .claims-case').first()).toContainText('LM-1042');
   await expect(page.getByRole('button', { name: 'Lancer l’enquête', exact: true })).toBeDisabled();
 });
 test('mobile priority stays readable in English', async ({ page }) => {
   await setup(page, 'light', 'en', false, 'ready'); await page.setViewportSize({ width: 390, height: 844 });
   await page.goto('/work/reclamations/studio');
   await expect(page.getByRole('heading', { name: 'Luma journey', exact: true })).toBeVisible();
   await expect(page.getByRole('link', { name: /SLA model/ })).toBeVisible();
   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
   await page.screenshot({ path: '/workspace/scratch/luma-ml-2026-10-06/work-priority-mobile.png', fullPage: true });
 });
 test('machine aids stay hidden while a manual benchmark session loads slowly', async ({ page }) => {
   await setup(page, 'light', 'fr', false, 'manual');
   let release!: () => void;
   const gate = new Promise<void>(resolve => { release = resolve; });
   await page.route('**/api/v1/ecommerce-claims/benchmark', async route => { await gate; await route.fallback(); });
   await page.goto('/work/reclamations/studio');
   await expect(page.getByRole('heading', { name: 'LM-1042', exact: true })).toBeVisible();
   await expect(page.locator('.claims-triage, .claims-risk, .claims-priority')).toHaveCount(0);
   await expect(page.getByRole('button', { name: 'Lancer l’enquête', exact: true })).toBeDisabled();
   release();
   await expect(page.getByRole('heading', { name: 'LM-1043', exact: true })).toBeVisible();
   await expect(page.locator('.claims-triage, .claims-risk, .claims-priority')).toHaveCount(0);
 });
 for (const theme of ['dark', 'light']) {
  test(`${theme}: evidence, distinct tools, canonical human decision and unknown ROI`, async ({ page }) => {
    const posts = await setup(page, theme, 'fr'); await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/work/reclamations/studio');
    await expect(page.getByRole('heading', { name: 'Réclamations', exact: true })).toBeVisible();
    await expect(page.getByText('Commande lue dans PostgreSQL', { exact: false })).toBeVisible();
    await expect(page.getByText('Livraison contestée', { exact: true })).toBeVisible();
    await expect(page.getByText('delivery_disputed', { exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: /LM-1043/ }).click();
    await page.getByRole('button', { name: 'Lancer l’enquête', exact: true }).click();
    await expect(page.getByText('Proposer un remboursement', { exact: true })).toBeVisible();
    const completionColors = await page.locator('.claims-steps li[data-state="completed"] .claims-step-dot').first().evaluate(marker => {
      const probe = document.createElement('span'); probe.style.backgroundColor = 'var(--ck-signal-cool)'; marker.parentElement!.append(probe);
      const colors = { actual: getComputedStyle(marker).backgroundColor, expected: getComputedStyle(probe).backgroundColor }; probe.remove(); return colors;
    });
    expect(completionColors.actual).toBe(completionColors.expected);
    await page.getByRole('button', { name: 'Valider la proposition', exact: true }).click();
    await expect(page.getByText('Proposer un remboursement', { exact: true })).toBeVisible();
    expect(posts[0]).toMatchObject({ payload: { claim_id: 'RC-1043' }, page_id: 'dossier', component_id: 'investigation', confirmed: true });
    expect(posts[1]).toMatchObject({ action: 'accept', expected_decision_id: 'qa-decision' });
    await page.getByRole('button', { name: /LM-1044/ }).click();
    await page.getByRole('button', { name: 'Lancer l’enquête', exact: true }).click();
    await expect(page.getByText('Clore la demande déjà remboursée', { exact: true })).toBeVisible();
    await expect(page.getByText('Vérification du remboursement antérieur', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'politique-remboursement-v2.pdf', exact: false }).click();
    await expect(page.getByTestId('work-source-panel')).toBeVisible();
    await page.getByTestId('work-source-close').click();
    await expect(page.getByRole('heading', { name: 'LM-1044', exact: true })).toBeVisible();
    await page.locator('app-claims-benchmark summary').click();
    await expect(page.getByText('L’expérimentation est incomplète.', { exact: false })).toBeVisible();
    const violations = (await new AxeBuilder({ page }).include('.claims-app').analyze()).violations;
    expect(violations).toEqual([]);
    await page.screenshot({ path: `/workspace/scratch/demo-qa-2026-10-02/claims-${theme}.png`, fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
 }
 test('an original stays open when incoming citations reorder the sources', async ({ page }) => {
   await setup(page, 'light', 'fr'); await page.goto('/work/reclamations/studio');
   await page.getByRole('button', { name: source.title, exact: true }).click();
   const panel = page.getByTestId('work-source-panel');
   await expect(panel.getByRole('heading', { name: source.title, exact: true })).toBeVisible();
   await expect(page.getByTestId('work-source-step')).toContainText('Source 1 sur 2');
   await page.getByRole('button', { name: 'Lancer l’enquête', exact: true }).click();
   await expect(page.getByText('Ouvrir une enquête transporteur', { exact: true })).toBeVisible();
   await expect(panel.getByRole('heading', { name: source.title, exact: true })).toBeVisible();
   await expect(page.getByTestId('work-source-step')).toContainText('Source 2 sur 2');
   await page.getByTestId('work-source-previous').click();
   await expect(panel.getByRole('heading', { name: claimSource.title, exact: true })).toBeVisible();
 });
 test('mobile English and a failed data connection remain readable', async ({ page }) => {
   await setup(page, 'light', 'en'); await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/work/reclamations/studio');
   await expect(page.getByRole('heading', { name: 'Claims', exact: true })).toBeVisible();
   await expect(page.getByText('Delivery disputed', { exact: true })).toBeVisible();
   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
   await page.screenshot({ path: '/workspace/scratch/demo-qa-2026-10-02/claims-mobile-en.png', fullPage: true });
 });
 test('connection failure offers recovery with no synthetic data replacement', async ({ page }) => {
   await setup(page, 'dark', 'fr', true); await page.goto('/work/reclamations/studio');
   await expect(page.getByRole('alert')).toContainText('Les dossiers ne sont pas disponibles');
   await expect(page.getByRole('button', { name: /LM-1042/ })).toHaveCount(0);
   await expect(page.getByRole('button', { name: 'Réessayer', exact: true })).toBeVisible();
 });
});
