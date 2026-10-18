import {expect, test, type Page} from '@playwright/test';
import {writeFile} from 'node:fs/promises';
import {expectOk} from '../fixtures/api';
import {resolveNativeInvocation, visibleNativeInvocation} from '../fixtures/native-invocation';

// Real, read-only release acceptance. Missing credentials or evidence is a failure,
// never a skip. No traces, payload logs, stored sessions or automatic screenshots.
test.use({trace: 'off', video: 'off', screenshot: 'off', serviceWorkers: 'block', ignoreHTTPSErrors: false});

interface EvaluationRow {
  id: string; run_id?: string; status?: string; composite_score?: number | null;
  scores?: Record<string, number>; created_at?: string;
}
interface Excerpt {
  id: string; text?: string | null; availability?: string; invocation_id?: string;
  document_ref?: string; page?: number;
}
interface Evaluation {
  evaluation_id?: string; status: string;
  claim_audit?: {claims?: Array<{excerpt_ids?: string[]}>};
  metadata?: {excerpts?: Excerpt[]};
}
interface RecordedRun {id: string}
interface Selection {row: EvaluationRow; claim: number; excerpt: Excerpt}
interface Features {enabled: boolean; execution_view_enabled: boolean; activity_series_enabled: boolean}

const measured = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

async function releaseState(page: Page, revision: string): Promise<Features> {
  for (const path of ['/api/v1/build-info', '/build-info.json']) {
    const build = await expectOk<{revision: string; revision_verified: boolean}>(page, path);
    expect(build.revision, `${path}: exact deployed revision`).toBe(revision);
    expect(build.revision_verified, `${path}: verified revision`).toBe(true);
  }
  const features = await expectOk<Features>(page, '/api/v1/observability/activities/features');
  expect(features.enabled, 'Existing activity supervision remains enabled').toBe(true);
  const expectedFlag = (name: string): boolean => {
    const value = process.env[name] ?? 'false';
    expect(['true', 'false'].includes(value), `${name} must be true or false`).toBe(true);
    return value === 'true';
  };
  expect(features.execution_view_enabled, 'R4 matches the declared release state').toBe(expectedFlag('E2E_EXPECT_EXECUTION_VIEW'));
  expect(features.activity_series_enabled, 'R2 matches the declared release state').toBe(expectedFlag('E2E_EXPECT_ACTIVITY_SERIES'));
  return features;
}

async function selectRealProof(page: Page, rows: EvaluationRow[]): Promise<Selection> {
  // The chart itself displays only these 20 rows. Do not silently expand the
  // corpus or create/re-evaluate a Run to make production acceptance pass.
  for (const row of rows) {
    if (!row.run_id || !measured(row.composite_score) || !Object.values(row.scores || {}).some(measured)) continue;
    const evaluation = await expectOk<Evaluation>(page, `/api/v1/evaluation/by-run/${encodeURIComponent(row.run_id)}`);
    if (evaluation.evaluation_id !== row.id || !['completed', 'partial', 'historical'].includes(evaluation.status)) continue;
    const claims = evaluation.claim_audit?.claims || [];
    for (let claim = 0; claim < claims.length; claim++) {
      const excerpt = evaluation.metadata?.excerpts?.find(item =>
        claims[claim].excerpt_ids?.includes(String(item.id)) && item.availability !== 'source_unavailable'
        && typeof item.text === 'string' && item.text.trim().length > 0);
      if (!excerpt) continue;
      const run: RecordedRun = await expectOk<RecordedRun>(page, `/api/v1/runs/${encodeURIComponent(row.run_id)}`);
      if (run.id === row.run_id) return {row, claim, excerpt};
    }
  }
  throw new Error('Showcase acceptance blocked: no measured evaluation with a real claim, available excerpt and matching recorded Run in the 20-row window.');
}

async function visibleProof(page: Page, selection: Selection): Promise<void> {
  const investigation = page.locator('app-run-investigation');
  await expect(investigation).toBeVisible();
  const claim = investigation.locator('button.claim').nth(selection.claim);
  await claim.focus();
  await claim.press('Enter');
  await expect(claim).toHaveAttribute('aria-pressed', 'true');
  await expect.poll(() => new URL(page.url()).searchParams.get('claim')).toBe(String(selection.claim));
  // Compare proof contents in the browser, returning only a boolean so an
  // assertion failure cannot copy the document into a reporter or CI log.
  await expect.poll(() => investigation.locator('.excerpt').evaluateAll((elements, expected) => elements.some(el =>
    el.querySelector('blockquote')?.textContent?.trim() === expected.text?.trim()
    && (!expected.document_ref || el.querySelector('strong')?.textContent?.includes(expected.document_ref))
    && (!expected.page || el.querySelector('strong')?.textContent?.includes(String(expected.page)))
    && (!expected.invocation_id || !!el.querySelector(`a[href*="/invocations/${encodeURIComponent(expected.invocation_id)}"]`))), selection.excerpt),
  {message: 'The selected claim exposes the real recorded excerpt and its source metadata'}).toBe(true);
}

test('Showcase release: point and matrix retain the real Run and proof on desktop and at 390 px', async ({page}, info) => {
  test.setTimeout(180_000);
  const username = process.env['E2E_USERNAME'];
  const password = process.env['E2E_PASSWORD'];
  const revision = process.env['E2E_EXPECTED_REVISION'];
  const workspaceSlug = process.env['E2E_SHOWCASE_WORKSPACE_SLUG'] || 'agentium-showcase';
  expect(!!username && !!password, 'Set explicit E2E_USERNAME and E2E_PASSWORD for the Showcase account').toBe(true);
  expect(!!revision && /^[a-f0-9]{40}$/.test(revision), 'E2E_EXPECTED_REVISION must be the full deployed commit').toBe(true);
  const asOf = new Date().toISOString();
  const scope = new URLSearchParams({since: '30d', as_of: asOf});
  const blockedWrites: string[] = [];
  let blockedTelemetry = 0;
  const completed: string[] = [];
  const evidence: Record<string, unknown> = {revision, workspace: workspaceSlug, as_of: asOf, since: '30d', completed};
  let accepted = false;

  // Abort rather than mock all writes. Automatic navigation telemetry is
  // suppressed explicitly; any attempted business mutation fails acceptance.
  await page.route('**/*', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (['GET', 'HEAD', 'OPTIONS'].includes(request.method()) ||
      (request.method() === 'POST' && ['/api/v1/auth/login', '/api/v1/auth/refresh', '/api/v1/auth/validate'].includes(path))) {
      await route.continue();
    } else {
      if (request.method() === 'POST' && path === '/api/v1/audit') blockedTelemetry++;
      else blockedWrites.push(`${request.method()} ${path}`);
      await route.abort('blockedbyclient');
    }
  });

  try {
    await page.goto('/auth/signin');
    // Do not use loginAsAlice: its failure message includes the auth body.
    const login = await page.evaluate(async ({credentials, workspaceSlug}) => {
      const response = await fetch('/api/v1/auth/login', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({...credentials, remember_me: false}),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || typeof body.token !== 'string') return {status: response.status, ok: false};
      localStorage.setItem('agentium_token', `Bearer ${body.token}`);
      if (typeof body.refresh_token === 'string') localStorage.setItem('agentium_refresh_token', body.refresh_token);
      localStorage.setItem('agentium_workspace_slug', workspaceSlug);
      return {status: response.status, ok: true};
    }, {credentials: {email: username!, password: password!}, workspaceSlug});
    expect(login.ok, `Authentication must succeed (HTTP ${login.status}); no retry with default credentials`).toBe(true);
    const workspaces = await expectOk<Array<{id: string; slug: string}>>(page, '/api/v1/auth/workspaces');
    const workspace = workspaces.find(item => item.slug === workspaceSlug);
    expect(!!workspace, 'The authenticated account must explicitly have Showcase membership').toBe(true);
    evidence.workspace_id = workspace!.id;
    evidence.features = await releaseState(page, revision!);
    completed.push('revision-and-declared-R2-R4');

    const history = await expectOk<{evaluations: EvaluationRow[]}>(page, `/api/v1/evaluation/history?limit=20&${scope}`);
    expect(history.evaluations.length, 'A real Showcase evaluation corpus is required').toBeGreaterThan(0);
    expect(history.evaluations.length).toBeLessThanOrEqual(20);
    const selection = await selectRealProof(page, history.evaluations);
    const {row, excerpt} = selection;
    evidence.ids = {evaluation: row.id, run: row.run_id, invocation: excerpt.invocation_id, excerpt: excerpt.id, claim: selection.claim};
    evidence.invocation_link_available = !!excerpt.invocation_id;
    // Retrieval excerpts are valid document proofs without a Skill invocation.
    // The four proof journeys remain mandatory; invocation coverage is separate.
    const nativeInvocation = excerpt.invocation_id ? await resolveNativeInvocation(page, {
      runId: row.run_id!, invocationId: excerpt.invocation_id, workspaceSlug,
    }) : null;
    if (nativeInvocation) evidence.invocation_resolution = nativeInvocation;
    const latest = await expectOk<{evaluation: EvaluationRow | null}>(page, `/api/v1/evaluation/latest?${scope}`);
    expect(Object.values(latest.evaluation?.scores || {}).some(measured), 'Radar requires measured dimensions').toBe(true);
    const ordered = [...history.evaluations].reverse();
    const rowIndex = ordered.findIndex(item => item.id === row.id);
    const dimensions = [...new Set(history.evaluations.flatMap(item => Object.keys(item.scores || {})))].sort();
    const dimensionIndex = dimensions.findIndex(dimension => measured(row.scores?.[dimension]));
    const qualityUrl = `/observability?facet=quality&${scope}`;

    await page.setViewportSize({width: 1440, height: 1000});
    await page.goto(`/observability?${scope}`);
    await expect(page.locator('app-workspace-monitor')).toBeVisible();
    await expect(page.getByTestId('observability-facets').getByRole('button')).toHaveCount(5);
    expect(await page.evaluate(() => localStorage.getItem('agentium_workspace_slug'))).toBe(workspaceSlug);
    completed.push('operations-default-and-five-facets');

    for (const width of [1440, 390]) {
      await page.setViewportSize({width, height: 1000});
      for (const origin of ['point', 'matrix'] as const) {
        await page.goto(qualityUrl);
        const chart = page.locator('app-quality-evidence-charts');
        await expect(chart).toBeVisible();
        await expect(chart.locator('.plot svg [role="button"]')).toHaveCount(history.evaluations.length);
        const target = origin === 'point' ? chart.locator('.plot svg [role="button"]').nth(rowIndex)
          : chart.locator('button.cell').nth(dimensionIndex * ordered.length + rowIndex);
        await target.focus();
        await target.press(origin === 'point' ? 'Enter' : 'Space');
        await expect.poll(() => new URL(page.url()).searchParams.get('evaluationId')).toBe(row.id);
        const link = chart.locator('.selection a');
        const href = await link.getAttribute('href');
        expect(new URL(href!, page.url()).pathname).toBe(`/runs/${row.run_id}`);
        await page.screenshot({path: info.outputPath(`quality-${origin}-${width}.png`), fullPage: true});
        await link.click();
        await expect.poll(() => new URL(page.url()).pathname).toBe(`/runs/${row.run_id}`);
        await visibleProof(page, selection);
        await page.reload();
        await visibleProof(page, selection);
        await page.locator('app-run-investigation .excerpt').first().scrollIntoViewIfNeeded();
        await page.locator('app-run-investigation').screenshot({path: info.outputPath(`proof-${origin}-${width}.png`)});
        if (nativeInvocation) {
          const invocation = page.locator(`app-run-investigation .excerpt a[href*="/invocations/${encodeURIComponent(nativeInvocation.invocation_id)}"]`).first();
          await invocation.click();
          await expect.poll(() => new URL(page.url()).pathname).toBe(`/runs/${row.run_id}/invocations/${excerpt.invocation_id}`);
          await visibleNativeInvocation(page, nativeInvocation);
          await page.reload();
          await visibleNativeInvocation(page, nativeInvocation);
          await page.goBack();
          await visibleProof(page, selection);
          completed.push(`${origin}-${width}-native-invocation-reload`);
        }
        await page.goBack();
        await expect(chart).toBeVisible();
        await page.reload();
        await expect(chart.locator('.selection a')).toHaveAttribute('href', href!);
        const query = new URL(page.url()).searchParams;
        expect(query.get('evaluationId')).toBe(row.id);
        expect(query.get('since')).toBe('30d');
        expect(query.get('as_of')).toBe(asOf);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'No page-wide horizontal overflow').toBe(true);
        completed.push(`${origin}-${width}-exact-run-proof-back-reload-keyboard`);
      }
      const details = page.locator('app-quality-dashboard details').filter({has: page.locator('canvas')});
      await details.locator('summary').click();
      const canvases = details.locator('canvas');
      await expect(canvases).toHaveCount(2);
      for (const canvas of await canvases.all()) {
        await canvas.scrollIntoViewIfNeeded();
        await expect(canvas).toBeVisible();
        expect(await canvas.evaluate(element => element instanceof HTMLCanvasElement && element.width > 0 && element.height > 0), 'Chart has nonzero rendering dimensions').toBe(true);
      }
      await details.screenshot({path: info.outputPath(`radar-history-${width}.png`)});
      completed.push(`radar-history-${width}`);
    }
    evidence.final_features = await releaseState(page, revision!);
    expect(blockedWrites.length, 'No business mutation may be attempted').toBe(0);
    expect(await page.evaluate(() => localStorage.getItem('agentium_workspace_slug'))).toBe(workspaceSlug);
    accepted = true;
  } finally {
    // Attach only identifiers and booleans; never full API responses, credentials,
    // document text, authorization headers or browser storage.
    const evidencePath = info.outputPath('showcase-quality-evidence.json');
    await writeFile(evidencePath, JSON.stringify({...evidence, accepted, blocked_business_writes: blockedWrites.length, blocked_business_paths: blockedWrites,
      suppressed_navigation_audits: blockedTelemetry}, null, 2));
    await info.attach('showcase-quality-evidence', {contentType: 'application/json', path: evidencePath});
  }
});
