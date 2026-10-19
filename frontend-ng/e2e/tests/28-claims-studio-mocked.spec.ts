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
function detail(id: string, queue = rows) { const row = queue.find(r => r.claim_id === id)!; return { data: { context: [{ ...row, shipping_postcode: '75011', payment_status: 'paid' }], items: [{ product_name: 'Lampe Aube', quantity: 1, unit_price: row.paid_amount }], shipments: [{ status: id === 'RC-1043' ? 'lost' : 'delivered', carrier: 'ColisAzur', tracking_id: 'CA-' + id.slice(3) }], refunds: id === 'RC-1044' ? [{ refund_id: 'RF-1044', amount: '89.00', currency: 'EUR', status: 'executed' }] : [] }, provenance: { captured_at: '2026-10-02T09:00:00Z', snapshot_sha256: 'qa-snapshot', read_mode: 'live' }, sources: [source, claimSource], receipts: [], latest_run_id: null }; }

async function setup(page: Page, theme: string, locale: string, unavailable = false, priority: 'ready' | 'stale' | 'manual' | null = null, options: { volume?: boolean; receipt?: boolean; benchmarkUnavailable?: boolean; judge?: 'abstained'|'failed'; dataFailure?: string; detailFailure?: string; consumer?: boolean; canConfigure?: boolean; accessUnavailable?: boolean } = {}) {
 const posts: unknown[] = []; let run: Record<string, unknown> | null = null;
 const activeWorkspace = options.consumer ? { ...workspace, role: 'member', role_template: 'workspace_member' } : workspace;
 const queue = options.volume ? [...rows, ...Array.from({ length: 20 }, (_, index) => ({ ...rows[index % rows.length], claim_id: `RC-${5001 + index}`, order_id: `LM-${5001 + index}`, display_name: `Client synthétique ${index + 1}`, state: index % 2 ? 'waiting_information' : 'resolved' }))] : rows;
 await page.route('**/*', route => ['127.0.0.1', 'localhost'].includes(new URL(route.request().url()).hostname) ? route.continue() : route.fulfill({ status: 204, body: '' }));
 await page.addInitScript(({ slug, theme, locale }) => { localStorage.setItem('agentium_token', 'Bearer isolated-claims-qa'); localStorage.setItem('agentium_workspace_slug', slug); localStorage.setItem('agentium_theme', theme); localStorage.setItem('agentium_locale', locale); }, { slug: workspace.slug, theme, locale });
 const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
 await page.route('**/api/v1/**', async route => {
   const request = route.request(); const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
   if (path === '/auth/validate') return json(route, { valid: true, user_id: 'qa-human', email: 'qa@example.test', role: options.consumer ? 'user' : 'admin' });
   if (path === '/auth/workspaces') return json(route, [activeWorkspace]);
   if (path === '/auth/workspaces/' + workspace.slug) return json(route, activeWorkspace);
   if (path === '/auth/me') return json(route, { id: 'qa-human', email: 'qa@example.test', role: options.consumer ? 'user' : 'admin', is_active: true, workspaces: [activeWorkspace] });
   if (path === '/connectors') return json(route, options.accessUnavailable ? { detail: 'unavailable' } : { connectors: [], can_configure: options.canConfigure ?? !options.consumer }, options.accessUnavailable ? 503 : 200);
   if (path === '/work/reclamations') return json(route, { experience: { id: 'qa-experience', slug: 'reclamations', name: 'Réclamations' }, release: { id: 'qa-release' }, channel: 'live' });
   if (path === '/ecommerce-claims' && options.dataFailure) return json(route, { detail: { code: options.dataFailure, message: 'PRIVATE_DATABASE_DIAGNOSTIC' } }, options.dataFailure === 'PG_AUTH_FAILED' ? 403 : 503);
   if (path === '/ecommerce-claims') return json(route, unavailable ? { detail: { code: 'POSTGRESQL_SCHEMA_NOT_LOADED' } } : { data: { queue } }, unavailable ? 503 : 200);
   if (path === '/ecommerce-claims/triage') return json(route, priority ? {
     status: priority === 'stale' ? 'stale' : 'ready', captured_at: new Date().toISOString(), max_age_minutes: 60,
     model: { id: 'qa-sla-model', name: 'Luma SLA', version: 1 },
     prediction_contract: {
       schema_version: 1, model_id: 'qa-sla-model', model_version: 1, task: 'classification',
       target: 'resolution_over_72h', positive_label: '1', label: 'SLA', unit: 'probability',
       value_column: 'prediction', score_column: 'score_1', max_age_seconds: 3600, order: 'descending',
       bands: [{ key: 'low', label: locale === 'fr' ? 'Priorité standard' : 'Standard priority', min: 0 },
         { key: 'medium', label: locale === 'fr' ? 'Priorité intermédiaire' : 'Medium priority', min: .35 },
         { key: 'high', label: locale === 'fr' ? 'Priorité haute' : 'High priority', min: .6 }],
     },
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
   if (path === '/ecommerce-claims/benchmark' && options.benchmarkUnavailable) return json(route, { detail: { code: 'BENCHMARK_UNAVAILABLE' } }, 503);
   if (path === '/ecommerce-claims/benchmark' && priority === 'manual') return json(route, {
     state: 'experiment_not_complete', hourly_eur: '40.00', planned_pairs: 10, completed_quality_pairs: 0,
     capacity_value_eur: null, incremental_cost_eur: null, net_benefit_eur: null, roi: null,
     trials: [{ id: 'qa-manual-trial', operator_id: 'qa-human', claim_id: 'RC-1043', state: 'active', condition: 'manual', pair_id: 'P01', events: [], active_human_seconds: null, result: null, review: null }],
     protocol: { pairs: [{ pair_id: 'P01', first_condition: 'manual', manual_claim_id: 'RC-1043', assisted_claim_id: 'RC-1042' }] },
   });
   if (path === '/ecommerce-claims/benchmark') return json(route, { state: 'experiment_not_complete', hourly_eur: '40.00', planned_pairs: 10, completed_quality_pairs: 0, capacity_value_eur: null, incremental_cost_eur: null, net_benefit_eur: null, roi: null, protocol_sha256: 'qa-protocol', trials: [], protocol: { version: 'qa-isolated', pairs: [{ pair_id: 'P01', first_condition: 'manual', manual_claim_id: 'RC-5001', assisted_claim_id: 'RC-5002' }] } });
   if (/^\/ecommerce-claims\/RC-/.test(path)) {
     if (options.detailFailure) return json(route, { detail: { code: options.detailFailure, message: 'PRIVATE_DATABASE_DIAGNOSTIC' } }, 503);
     const body = detail(path.split('/').at(-1)!, queue);
     return json(route, options.receipt ? { ...body, receipts: [{ receipt_id: 'qa-existing-receipt', status: 'simulated', claim_id: body.data.context[0].claim_id, order_id: body.data.context[0].order_id, action: 'carrier_investigation', reason: 'delivery_address_mismatch', amount: '0', currency: 'EUR', evidence_kind: 'synthetic_demo', missing_references: [], requires_human: true, citations: [] }] } : body);
   }
   if (path.endsWith('/bindings/showcase.claims.investigate/runs')) {
     posts.push(request.postDataJSON()); const id = (posts.at(-1) as { payload: { claim_id: string } }).payload.claim_id;
     const action = id === 'RC-1043' ? 'refund' : id === 'RC-1044' ? 'close_duplicate' : 'carrier_investigation';
     const proposal = { claim_id: id, order_id: 'LM-' + id.slice(3), action, reason: id === 'RC-1043' ? 'carrier_loss_confirmed' : id === 'RC-1044' ? 'already_refunded' : 'delivery_address_mismatch', amount: action === 'refund' ? '49.90' : '0', currency: 'EUR', evidence_kind: 'synthetic_demo', missing_references: [], requires_human: true, citations: [claimSource, source].map(s => ({ ...s, content: 'Toute résolution exige une validation humaine.', page: 1, chunk_index: 0 })) };
     const tool = id === 'RC-1044' ? 'ecommerce_refund_evidence_v1' : 'ecommerce_delivery_evidence_v1';
     const context = { claim_id: id, served: { model_id: 'qa-sla-model', version: 1 }, target: 'resolution_over_72h', positive_label: '1', score: id === 'RC-1043' ? 0.16 : 0.82,
       prepared_dataset: { id: 'qa-case-prepared', name: 'Case data', version: 1, rows: 1 }, scored_dataset: { id: 'qa-case-scored', name: 'Case prediction', version: 1, rows: 1 } };
     run = { id: 'qa-native-run', system_id: 'qa-system', input_ref: { claim_id: id }, status: 'hitl_pending', hitl: { decision_id: 'qa-decision', node_id: 'hitl.review' }, skill_invocations: ['ecommerce_sav_dataset_v1', 'sql_transform_v1', 'ml_batch_score_v1', 'ecommerce_sav_context_v1', 'postgresql_claim_snapshot_v1', 'ecommerce_policy_evidence_v1', tool, 'ecommerce_resolution_propose_v1'].map((slug, i) => ({ id: 'qa-inv-' + i, skill_slug: slug, status: 'completed', completed_at: new Date().toISOString(), output_ref: slug === 'ecommerce_resolution_propose_v1' ? proposal : slug === 'ecommerce_sav_context_v1' ? context : {} })) };
     if (options.judge) (run['skill_invocations'] as unknown[]).push({
       id: 'qa-judge', skill_slug: 'evaluate_v2', status: options.judge === 'failed' ? 'failed' : 'completed',
       error: options.judge === 'failed' ? 'PRIVATE_PROVIDER_DIAGNOSTIC' : null,
       output_ref: options.judge === 'failed' ? {} : {
         schema_version: 2, evaluation_id: 'qa-evaluation', status: 'partial', quality_status: 'unassessed', disposition: 'review', confidence: null,
         questions: [{key: 'policy', question: locale === 'fr' ? 'Les preuves permettent-elles cette résolution ?' : 'Does the evidence support this resolution?'}],
         answers: {policy: {status: 'abstained', value: null, reason: 'insufficient_evidence', explanation: locale === 'fr' ? 'La preuve transporteur manque.' : 'Carrier evidence is missing.', evidence: [], confidence: null}},
         coverage: {questions_answered: 0, questions_total: 1, evidence_examined: 2, evidence_total: 2, images_examined: 0, images_total: 0},
         cost: {amount: null, currency: 'USD', measurement_coverage: 'unavailable'},
       },
     });
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
 for (const consumer of [false, true]) {
  test(`PostgreSQL: TLS failure gives proportionate recovery for ${consumer ? 'a consumer' : 'an administrator'}`, async ({ page }, testInfo) => {
   const requests: string[] = [];
   page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/v1/connectors')) requests.push(`${request.method()} ${new URL(request.url()).pathname}`); });
   const options = { dataFailure: 'PG_TLS_UNAVAILABLE', consumer };
   await setup(page, consumer ? 'light' : 'dark', 'fr', false, null, options);
   await page.setViewportSize({ width: consumer ? 390 : 1440, height: 900 });
   await page.goto('/work/reclamations/studio');
   const warning = page.locator('.claims-data-error');
   await expect(warning).toContainText('Les dossiers sont temporairement indisponibles.');
   await expect(warning).toContainText('Ce serveur PostgreSQL ne prend pas en charge la connexion TLS requise.');
   await expect(warning).toContainText('Un administrateur doit activer TLS sur le serveur.');
   await expect(warning).not.toContainText('publication');
   await expect(page.getByText('PRIVATE_DATABASE_DIAGNOSTIC')).toHaveCount(0);
   await expect(page.locator('.work-record-item')).toHaveCount(0);
   const retry = warning.getByRole('button', { name: 'Réessayer', exact: true });
   await expect(retry).toBeVisible();
   expect((await retry.boundingBox())!.height).toBeLessThanOrEqual(32);
   const explore = warning.getByRole('link', { name: 'Explorer PostgreSQL', exact: true });
   if (consumer) {
     await expect(explore).toHaveCount(0);
     await expect(warning).toContainText('Contactez un administrateur du workspace pour rétablir la connexion, puis réessayez.');
   } else {
     await expect(explore).toHaveAttribute('href', /^\/connectors\/postgresql(?:\?|$)/);
     expect((await explore.boundingBox())!.height).toBeLessThanOrEqual(32);
   }
   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
   expect((await new AxeBuilder({ page }).include('.claims-app').analyze()).violations).toEqual([]);
   await page.screenshot({ path: testInfo.outputPath(`postgresql-tls-${consumer ? 'consumer' : 'administrator'}.png`), fullPage: true });
   options.dataFailure = '';
   await retry.click();
   await expect(page.locator('.claims-data-error')).toHaveCount(0);
   await expect(page.locator('.work-record-item')).toHaveCount(3);
   expect(requests.length).toBeGreaterThan(0);
   expect(requests.every(request => request === 'GET /api/v1/connectors')).toBe(true);
  });
 }
 test('PostgreSQL: authentication failure uses the server capability, not the apparent owner role', async ({ page }) => {
   await setup(page, 'dark', 'fr', false, null, { dataFailure: 'PG_AUTH_FAILED', canConfigure: false });
   await page.goto('/work/reclamations/studio');
   const warning = page.locator('.claims-data-error');
   await expect(warning).toContainText('PostgreSQL refuse l’authentification.');
   await expect(warning).toContainText('Contactez un administrateur du workspace');
   await expect(page.locator('.claims-app a[href^="/connectors/postgresql"]')).toHaveCount(0);
   await expect(page.getByText('PRIVATE_DATABASE_DIAGNOSTIC')).toHaveCount(0);
 });
 test('PostgreSQL: connection failure stays actionable when permissions cannot be verified', async ({ page }) => {
   await setup(page, 'light', 'en', false, null, { dataFailure: 'PG_CONNECTION_REFUSED', accessUnavailable: true });
   await page.goto('/work/reclamations/studio');
   const warning = page.locator('.claims-data-error');
   await expect(warning).toContainText('The PostgreSQL connection was refused.');
   await expect(warning).toContainText('Contact a workspace administrator');
   await expect(warning.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
   await expect(warning.getByRole('link')).toHaveCount(0);
 });
 test('PostgreSQL: an unknown reader failure remains generic and never renders server text', async ({ page }) => {
   await setup(page, 'dark', 'en', false, null, { dataFailure: 'POSTGRESQL_READ_UNAVAILABLE', consumer: true });
   await page.goto('/work/reclamations/studio');
   await expect(page.locator('.claims-data-error')).toContainText('Agentium could not reach PostgreSQL.');
   await expect(page.getByText('PRIVATE_DATABASE_DIAGNOSTIC')).toHaveCount(0);
 });
 test('PostgreSQL: a case-level TLS failure can be retried while the queue remains available', async ({ page }) => {
   const options = { detailFailure: 'PG_TLS_VERIFICATION_FAILED', consumer: true };
   await setup(page, 'dark', 'fr', false, 'ready', options);
   await page.goto('/work/reclamations/studio?record=RC-1042');
   const warning = page.locator('.claims-data-error');
   await expect(warning).toContainText('Le certificat PostgreSQL n’a pas pu être validé.');
   await expect(page.locator('.work-record-item')).toHaveCount(3);
   await expect(page.locator('.claims-app a[href^="/connectors/postgresql"]')).toHaveCount(0);
   await expect(page.locator('.claims-triage-path')).toContainText('PostgreSQL');
   options.detailFailure = '';
   await warning.getByRole('button', { name: 'Réessayer', exact: true }).click();
   await expect(warning).toHaveCount(0);
   await expect(page.locator('.claims-dossier')).toContainText('LM-1042');
 });
 for (const width of [1440, 390]) {
  test(`judge: evidence-based abstention remains visible before human approval at ${width}px`, async ({ page }, testInfo) => {
    const posts = await setup(page, 'dark', 'en', false, null, {judge: 'abstained'});
    await page.setViewportSize({width, height: 900});
    await page.goto('/work/reclamations/studio?record=RC-1042');
    await page.getByRole('button', {name: 'Start investigation', exact: true}).click();
    const review = page.getByTestId('typed-judge-result');
    await expect(review.getByRole('heading', {name: 'Quality review', exact: true})).toBeVisible();
    await expect(review).toContainText('Unassessed');
    await expect(review).toContainText('Human review required before delivery.');
    await expect(review).toContainText('Does the evidence support this resolution?');
    await expect(review.getByText(/Abstained.*Insufficient evidence/)).toBeVisible();
    await expect(review.getByText('Carrier evidence is missing.', {exact: true})).toBeVisible();
    const technical = review.getByTestId('judge-technical-details');
    await expect(technical).not.toHaveAttribute('open');
    await expect(review.getByText(/Calibrated confidence/)).not.toBeVisible();
    const approval = page.getByRole('button', {name: 'Approve proposal', exact: true});
    await expect(approval).toBeVisible();
    expect((await review.boundingBox())!.y).toBeLessThan((await approval.boundingBox())!.y);
    expect(posts).toHaveLength(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect((await new AxeBuilder({page}).include('.claims-app').analyze()).violations).toEqual([]);
    await page.screenshot({path: testInfo.outputPath(`judge-review-${width}.png`), fullPage: true});
  });
 }
 test('judge: a failed evaluation is explicit without exposing provider diagnostics', async ({ page }) => {
   await setup(page, 'light', 'fr', false, null, {judge: 'failed'});
   await page.goto('/work/reclamations/studio?record=RC-1042');
   await page.getByRole('button', {name: 'Lancer l’enquête', exact: true}).click();
   await expect(page.getByTestId('run-quality-review-state')).toContainText('Aucune validation du juge n’est attestée.');
   await expect(page.getByTestId('typed-judge-result')).toHaveCount(0);
   await expect(page.getByText('PRIVATE_PROVIDER_DIAGNOSTIC')).toHaveCount(0);
   await expect(page.getByRole('button', {name: 'Valider la proposition', exact: true})).toBeVisible();
 });
 for (const theme of ['dark', 'light']) {
  test(`${theme}: model scores prioritize cases, expose lineage and rescore through the pinned Flow`, async ({ page }, testInfo) => {
    const posts = await setup(page, theme, 'fr', false, 'ready');
    await page.setViewportSize({ width: 1440, height: 1000 }); await page.goto('/work/reclamations/studio');
    await expect(page.getByRole('heading', { name: 'Parcours Luma', exact: true })).toBeVisible();
    await expect(page.locator('.claims-queue .work-record-item').first()).toContainText('LM-1043');
    await page.locator('.claims-queue .work-record-item').first().click();
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
    await expect(page.getByRole('button', { name: 'Valider la proposition', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Données de ce dossier', exact: true })).toHaveAttribute('href', /^\/data\/qa-case-prepared(?:\?|$)/);
    await expect(page.getByRole('link', { name: 'Prédiction de ce dossier', exact: true })).toHaveAttribute('href', /^\/data\/qa-case-scored(?:\?|$)/);
    await expect(page.locator('.claims-risk')).toContainText('16');
    await expect(page.getByText('Rapprochement des faits et du score', { exact: true })).toBeVisible();
    expect(posts[1]).toMatchObject({ payload: { claim_id: 'RC-1043' }, page_id: 'dossier', component_id: 'investigation' });
    expect((await new AxeBuilder({ page }).include('.claims-app').analyze()).violations).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`work-priority-${theme}.png`), fullPage: true });
  });
 }
 test('expired scores retain dataset links and the usual queue order', async ({ page }, testInfo) => {
   await setup(page, 'light', 'fr', false, 'stale'); await page.goto('/work/reclamations/studio');
   await expect(page.getByText('Scores expirés après 60 min.', { exact: false })).toBeVisible();
   await expect(page.locator('.claims-queue .work-record-item').first()).toContainText('LM-1042');
   await expect(page.locator('.claims-risk')).toHaveCount(0);
   await expect(page.getByRole('link', { name: /File scorée/ })).toBeVisible();
 });
 test('a manual benchmark hides the model and all predictive aid', async ({ page }, testInfo) => {
   await setup(page, 'dark', 'fr', false, 'manual'); await page.goto('/work/reclamations/studio');
   await expect(page.getByRole('heading', { name: 'LM-1043', exact: true })).toBeVisible();
   await expect(page.locator('.claims-triage')).toHaveCount(0);
   await expect(page.locator('.claims-risk, .claims-priority')).toHaveCount(0);
   await expect(page.locator('.claims-queue .work-record-item').first()).toContainText('LM-1042');
   await expect(page.getByRole('button', { name: 'Lancer l’enquête', exact: true })).toBeDisabled();
 });
 test('mobile priority stays readable in English', async ({ page }, testInfo) => {
   await setup(page, 'light', 'en', false, 'ready'); await page.setViewportSize({ width: 390, height: 844 });
   await page.goto('/work/reclamations/studio');
   await expect(page.getByRole('heading', { name: 'Luma journey', exact: true })).toBeVisible();
   await expect(page.getByRole('link', { name: /SLA model/ })).toBeVisible();
   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
   await page.screenshot({ path: testInfo.outputPath('work-priority-mobile.png'), fullPage: true });
 });
 test('machine aids stay hidden while a manual benchmark session loads slowly', async ({ page }, testInfo) => {
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
  test(`${theme}: evidence, distinct tools, canonical human decision and unknown ROI`, async ({ page }, testInfo) => {
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
    await page.screenshot({ path: testInfo.outputPath(`claims-${theme}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
 }
 test('an original stays open when incoming citations reorder the sources', async ({ page }, testInfo) => {
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
 test('mobile English and a failed data connection remain readable', async ({ page }, testInfo) => {
   await setup(page, 'light', 'en'); await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/work/reclamations/studio');
   await expect(page.getByRole('heading', { name: 'Claims', exact: true })).toBeVisible();
   await page.getByRole('button', { name: /LM-1042.*Change/ }).click();
   await expect(page.getByText('Delivery disputed', { exact: true })).toBeVisible();
   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
   await page.screenshot({ path: testInfo.outputPath('claims-mobile-en.png'), fullPage: true });
 });
 test('23-case mobile queue keeps the action near the top and preserves a searchable selection through reload and history', async ({ page }, testInfo) => {
   await setup(page, 'light', 'fr', false, null, { volume: true });
   await page.setViewportSize({ width: 390, height: 844 });
   await page.goto('/work/reclamations/studio?record=RC-5019&lang=fr');
   const queue = page.locator('app-work-record-queue');
   await expect(page.getByRole('heading', { name: 'LM-5019', exact: true })).toBeVisible();
   await expect(queue.locator('.work-record-toggle')).toContainText('LM-5019');
   await expect(queue.locator('.work-record-toggle')).toHaveAttribute('aria-expanded', 'false');
   const action = page.getByRole('button', { name: 'Lancer l’enquête', exact: true });
   await expect(action).toBeEnabled();
   expect((await action.boundingBox())!.y).toBeLessThan(1000);
   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
   await queue.locator('.work-record-toggle').click();
   expect((await queue.locator('.work-record-list').boundingBox())!.height).toBeLessThanOrEqual(380);
   await queue.getByRole('searchbox', { name: 'Rechercher', exact: true }).fill('synthetique 19');
   await expect(queue.locator('.work-record-item')).toHaveCount(1);
   await expect(queue.locator('.work-record-item')).toContainText('LM-5019');
   await queue.getByRole('searchbox').fill('');
   await queue.getByRole('combobox', { name: 'Statut', exact: true }).selectOption('waiting_information');
   await expect(queue.locator('.work-record-item')).toHaveCount(10);
   await expect(queue.getByText('Dossier ouvert hors filtre : LM-5019.', { exact: true })).toBeVisible();
   await queue.getByRole('searchbox').fill('RC-5020');
   const lastCase = queue.getByRole('button', { name: /LM-5020/ });
   await lastCase.focus(); await page.keyboard.press('Enter');
   await expect(page).toHaveURL(/record=RC-5020/);
   await expect(page).toHaveURL(/lang=fr/);
   await expect(queue.locator('.work-record-toggle')).toBeFocused();
   await expect(queue.locator('.work-record-toggle')).toHaveAttribute('aria-expanded', 'false');
   await expect(page.getByRole('heading', { name: 'LM-5020', exact: true })).toBeVisible();
   await page.reload();
   await expect(page.getByRole('heading', { name: 'LM-5020', exact: true })).toBeVisible();
   await page.goBack();
   await expect(page.getByRole('heading', { name: 'LM-5019', exact: true })).toBeVisible();
   await page.goForward();
   await expect(page.getByRole('heading', { name: 'LM-5020', exact: true })).toBeVisible();
   await page.setViewportSize({ width: 1440, height: 1000 });
   const selected = queue.locator('.work-record-item[aria-current="true"]');
   await expect.poll(async () => {
     const bounds = await queue.locator('.work-record-list').boundingBox(), item = await selected.boundingBox();
     return !!bounds && !!item && item.y >= bounds.y && item.y + item.height <= bounds.y + bounds.height + 1;
   }).toBe(true);
   await page.setViewportSize({ width: 1024, height: 900 });
   expect((await page.locator('.claims-decision').boundingBox())!.y).toBeLessThan((await page.locator('.claims-dossier').boundingBox())!.y);
   expect((await action.boundingBox())!.y).toBeLessThan(1000);
   await page.screenshot({ path: testInfo.outputPath('work-queue-tablet-after.png'), fullPage: true });
   await page.setViewportSize({ width: 390, height: 844 });
   expect((await new AxeBuilder({ page }).include('.claims-app').analyze()).violations).toEqual([]);
   await page.screenshot({ path: testInfo.outputPath('work-queue-mobile-after.png'), fullPage: true });
 });
 test('desktop search leaves the selected dossier in place and recovers from an empty filter', async ({ page }, testInfo) => {
   await setup(page, 'dark', 'en', false, 'ready', { volume: true });
   await page.setViewportSize({ width: 1440, height: 1000 });
   await page.goto('/work/reclamations/studio?record=RC-1043');
   const queue = page.locator('app-work-record-queue');
   await expect(page.getByRole('heading', { name: 'LM-1043', exact: true })).toBeVisible();
   await queue.getByRole('searchbox').fill('absent');
   await expect(queue.getByText('No results. Change the search or status.', { exact: true })).toBeVisible();
   await expect(page.getByRole('heading', { name: 'LM-1043', exact: true })).toBeVisible();
   await queue.getByRole('searchbox').fill('RC-1043');
   await expect(queue.locator('.work-record-item')).toHaveCount(1);
   await expect(queue.locator('.work-record-item')).toHaveAttribute('aria-current', 'true');
   await expect(queue.locator('.work-record-item')).toContainText('To investigate');
   await queue.getByRole('searchbox').fill('');
   expect((await new AxeBuilder({ page }).include('.claims-app').analyze()).violations).toEqual([]);
   await page.screenshot({ path: testInfo.outputPath('work-queue-desktop-after.png'), fullPage: true });
 });
 test('a recorded action is visible without inviting an accidental duplicate investigation', async ({ page }, testInfo) => {
   const posts = await setup(page, 'light', 'fr', false, null, { receipt: true });
   await page.goto('/work/reclamations/studio?record=RC-1042');
   await expect(page.getByRole('heading', { name: 'Action enregistrée', exact: true })).toBeVisible();
   await expect(page.getByRole('button', { name: 'Lancer l’enquête', exact: true })).toHaveCount(0);
   await expect(page.locator('app-work-action-receipt')).toContainText('Enquête transporteur ouverte');
   await page.locator('app-work-action-receipt summary').click();
   await expect(page.getByText('qa-existing-receipt', { exact: true })).toBeVisible();
   expect(posts).toEqual([]);
   expect((await new AxeBuilder({ page }).include('.claims-app').analyze()).violations).toEqual([]);
   await page.screenshot({ path: testInfo.outputPath('work-receipt-desktop-after.png'), fullPage: true });
   await page.setViewportSize({ width: 390, height: 844 });
   await expect(page.getByRole('heading', { name: 'Action enregistrée', exact: true })).toBeVisible();
   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
   await page.screenshot({ path: testInfo.outputPath('work-receipt-mobile-after.png'), fullPage: true });
   await page.locator('summary').filter({ hasText: 'Réexaminer le dossier' }).click();
   await page.getByRole('button', { name: 'Lancer une nouvelle enquête', exact: true }).click();
   await expect(page.getByRole('button', { name: 'Valider la proposition', exact: true })).toBeVisible();
   expect(posts).toHaveLength(1);
 });
 test('a failed benchmark mode check is actionable while automated aids stay unavailable', async ({ page }, testInfo) => {
   await setup(page, 'dark', 'fr', false, 'ready', { benchmarkUnavailable: true });
   let checks = 0;
   page.on('request', request => { if (new URL(request.url()).pathname.endsWith('/ecommerce-claims/benchmark')) checks++; });
   await page.goto('/work/reclamations/studio');
   const warning = page.locator('.benchmark-load-error');
   await expect(warning).toContainText('Impossible de vérifier le mode de travail');
   await expect(page.locator('.claims-triage, .claims-risk, .work-record-badge')).toHaveCount(0);
   await expect(page.getByRole('button', { name: 'Lancer l’enquête', exact: true })).toBeDisabled();
   const before = checks;
   await warning.getByRole('button', { name: 'Réessayer', exact: true }).click();
   await expect.poll(() => checks).toBeGreaterThan(before);
   await expect(warning).toBeVisible();
   await expect(page.getByRole('button', { name: 'Lancer l’enquête', exact: true })).toBeDisabled();
 });
 test('connection failure offers recovery with no synthetic data replacement', async ({ page }, testInfo) => {
   await setup(page, 'dark', 'fr', true); await page.goto('/work/reclamations/studio');
   await expect(page.getByRole('alert')).toContainText('Les dossiers sont temporairement indisponibles.');
   await expect(page.getByRole('alert')).toContainText('Les tables nécessaires ne sont pas disponibles dans cette base PostgreSQL.');
   await expect(page.getByRole('button', { name: /LM-1042/ })).toHaveCount(0);
   await expect(page.getByRole('button', { name: 'Réessayer', exact: true })).toBeVisible();
 });
});
