import {expect, test, type Page, type Route} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.use({serviceWorkers: 'block', video: 'off', ignoreHTTPSErrors: false});
const workspace = {id: 'judge-qa', slug: 'judge-qa', name: 'Review QA', role: 'owner', role_template: 'workspace_owner', settings: {features: {skill_invocation_360_projection_v1: false}}, effective_features: {skill_invocation_360_projection_v1: false}};
const result = (locale: string, truncated: boolean) => ({
  schema_version: 2, evaluation_id: 'evaluation-1', status: 'failed', quality_status: 'unassessed', disposition: 'review',
  reason: truncated ? 'JUDGE_OUTPUT_TRUNCATED' : 'JUDGE_RESPONSE_INVALID',
  ...(truncated ? {} : {response_diagnostic: {category: 'evidence_quote', question_index: 0, citation_index: 0, message: 'PRIVATE_PROVIDER_TEXT'}}),
  questions: [{key: 'policy', question: locale === 'fr' ? 'Les preuves permettent-elles cette résolution ?' : 'Does the evidence support this resolution?'}],
  answers: {policy: {status: 'invalid', value: null, reason: truncated ? 'JUDGE_OUTPUT_TRUNCATED' : 'JUDGE_RESPONSE_INVALID', explanation: '', evidence: [], confidence: null}},
  coverage: {questions_answered: 0, questions_total: 1, evidence_examined: 0, evidence_total: 2, images_examined: 0, images_total: 0}, confidence: null,
  cost: {amount: .0928, currency: 'USD', measurement_coverage: 'complete'},
});

const nativeDecision = {
  schema_version:2,evaluation_id:'native-decision',status:'completed',quality_status:'passed',disposition:'review',confidence:null,
  questions:[{key:'priority',question:'Select the request priority',type:'choice',choices:['Urgent','Routine'],requires_evidence:false,required:true}],
  answers:{priority:{status:'answered',value:'Urgent',reason:null,explanation:'Typed provider decision; no generated explanation or answer citation.',evidence:[],confidence:null}},
  coverage:{questions_answered:1,questions_total:1,evidence_examined:1,evidence_total:1},
  typed_decisions:{protocol:'typesafe-decisions-v1',source:'provider_reported',answers:{priority:{type:'choice',choice:'option_0',confidence:.6,probabilities:{option_0:.8,option_1:.2},choice_labels:{option_0:'Urgent',option_1:'Routine'}}}},
};

async function setup(page: Page, locale: 'fr'|'en', truncated: boolean, typedDecision = false) {
  const requests: string[] = [], writes: string[] = [];
  let redacted = false;
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
  await page.addInitScript(({locale, slug}) => {
    localStorage.setItem('agentium_token', 'Bearer isolated-judge-qa');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_locale', locale);
    localStorage.setItem('agentium_theme', locale === 'fr' ? 'dark' : 'light');
  }, {locale, slug: workspace.slug});
  const json = (route: Route, body: unknown) => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
  await page.route('**/api/v1/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    requests.push(path); if (request.method() !== 'GET') writes.push(path);
    if (path === '/auth/validate') return json(route, {valid: true, user_id: 'qa-human', role: 'admin'});
    if (path === '/auth/me') return json(route, {id: 'qa-human', role: 'admin', is_active: true, workspaces: [workspace]});
    if (path === '/auth/workspaces') return json(route, [workspace]);
    if (path === '/auth/workspaces/' + workspace.slug) return json(route, workspace);
    if (path === '/runs/judge-run') return json(route, {id: 'judge-run', system_id: 'review-system', status: 'completed', skill_invocations: [{
      id: 'judge-invocation', run_id: 'judge-run', skill_slug: 'evaluate_v2', status: 'completed', latency_ms: 2500, output_ref: redacted ? {} : typedDecision ? nativeDecision : result(locale, truncated),
    }]});
    return json(route, {});
  });
  return {requests, writes, redact: () => {redacted = true;}};
}

test.describe('Typed Judge diagnostics — local read-only QA', () => {
  test.beforeEach(async ({}, info) => {
    test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1' || !['localhost', '127.0.0.1'].includes(new URL(String(info.project.use.baseURL)).hostname), 'Local mocked QA only.');
  });
  for (const locale of ['fr', 'en'] as const) for (const truncated of [false, true]) {
    test(`${locale}: ${truncated ? 'truncated response' : 'invalid citation'} separates the review from a completed call`, async ({page}, info) => {
      const api = await setup(page, locale, truncated);
      await page.setViewportSize({width: locale === 'fr' ? 1440 : 390, height: 900});
      await page.goto('/runs/judge-run/invocations/judge-invocation?lens=operate');
      const review = page.getByTestId('typed-judge-result'), failure = review.getByTestId('judge-failure');
      await expect(failure).toBeVisible();
      await expect(failure).toContainText(locale === 'fr' ? 'Évaluation interrompue' : 'Evaluation interrupted');
      await expect(failure).toContainText(truncated
        ? locale === 'fr' ? 'La réponse du juge est incomplète.' : 'The judge response is incomplete.'
        : locale === 'fr' ? 'Le texte cité ne correspond pas au passage de la source.' : 'The quoted text does not match the source passage.');
      await expect(failure).toContainText(locale === 'fr' ? 'responsable du Flow' : 'Flow owner');
      await expect(failure).toContainText(locale === 'fr' ? 'Aucune validation du juge n’est attestée.' : 'No judge approval is established.');
      if (truncated) await expect(failure).not.toContainText(locale === 'fr' ? 'Question concernée' : 'Affected question');
      else await expect(failure).toContainText(locale === 'fr' ? 'Les preuves permettent-elles cette résolution ?' : 'Does the evidence support this resolution?');
      await expect(review).not.toContainText('PRIVATE_PROVIDER_TEXT');
      await expect(review).not.toContainText('JUDGE_');
      const header = page.locator('ck-object-header');
      await expect(header).toContainText(locale === 'fr' ? 'Exécution de l’appel' : 'Call execution');
      await expect(header).toContainText(locale === 'fr' ? 'Terminé' : 'Completed');
      await expect(header).toContainText(locale === 'fr' ? 'Évaluation interrompue' : 'Evaluation interrupted');
      const measurements = review.getByTestId('judge-technical-details');
      await expect(measurements).not.toHaveAttribute('open');
      await measurements.locator('summary').focus(); await page.keyboard.press('Enter');
      await expect(measurements).toHaveAttribute('open', '');
      await expect(measurements).toContainText('0.0928 USD');
      await measurements.locator('summary').press('Enter');
      expect(await review.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
      expect((await new AxeBuilder({page}).include('app-typed-judge-result').analyze()).violations).toEqual([]);
      await review.screenshot({path: info.outputPath(`judge-${locale}-${truncated ? 'truncated' : 'citation'}.png`)});
      expect(api.requests.filter(path => path.includes('/invocations/') || path.includes('/perspectives'))).toEqual([]);
      expect(api.writes.filter(path => !['/auth/validate', '/audit'].includes(path) && !path.includes('/navigation'))).toEqual([]);
      api.redact(); await page.reload();
      await expect(page.getByTestId('skill-invocation-audit')).toBeVisible();
      await expect(page.getByTestId('typed-judge-result')).toHaveCount(0);
      await expect(page.locator('ck-object-header')).not.toContainText(locale === 'fr' ? 'Évaluation interrompue' : 'Evaluation interrupted');
    });
  }
});

for (const locale of ['fr', 'en'] as const) {
  test(`Jev probabilities remain distinct from rubric confidence (${locale})`, async ({page}, info) => {
    const api = await setup(page, locale, false, true);
    await page.setViewportSize({width: locale === 'fr' ? 1440 : 390, height: 900});
    await page.goto('/runs/judge-run/invocations/judge-invocation?lens=operate');
    const review = page.getByTestId('typed-judge-result');
    const native = review.getByTestId('judge-provider-decision');
    await expect(native).toBeVisible();
    await expect(review).toContainText(locale === 'fr' ? 'Ce moteur ne produit pas de justification rédigée' : 'This engine does not produce a written explanation');
    await expect(review).not.toContainText('Typed provider decision;');
    await native.locator('summary').focus(); await page.keyboard.press('Enter');
    await expect(native).toContainText(locale === 'fr' ? 'non qualifiée sur cette grille' : 'not qualified for this rubric');
    await expect(native).toContainText('60 %');
    await expect(native).toContainText('Urgent: 80 %');
    await expect(native).toContainText('Routine: 20 %');
    await expect(native).toContainText(locale === 'fr' ? 'validation humaine' : 'human approval');
    await review.getByTestId('judge-technical-details').locator('summary').click();
    await expect(review.getByTestId('judge-technical-details')).toContainText(locale === 'fr' ? 'Non mesuré' : 'Not measured');
    expect(await review.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    expect((await new AxeBuilder({page}).include('app-typed-judge-result').analyze()).violations).toEqual([]);
    await review.screenshot({path:info.outputPath('jev-probabilities-'+locale+'.png')});
    api.redact(); await page.reload();
    await expect(page.getByTestId('typed-judge-result')).toHaveCount(0);
    expect(api.writes.filter(path => !['/auth/validate','/audit'].includes(path) && !path.includes('/navigation'))).toEqual([]);
  });
}
