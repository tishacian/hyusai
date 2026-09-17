/** Rendered Work approval contract. Synthetic API fixtures; never targets a live action. */
import assert from 'node:assert/strict';
import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';

const base = process.env.BASE ?? 'http://localhost:4200';
const out = process.env.OUT ?? '../docs/reports/mandate-experience/visual-qa';
mkdirSync(out, { recursive: true });
const browser = await chromium.launch(process.env.E2E_CHROMIUM_EXECUTABLE ? { executablePath: process.env.E2E_CHROMIUM_EXECUTABLE } : {});
const report = [];
try {
  for (const theme of ['light', 'dark']) for (const locale of ['fr', 'en']) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1200 }, timezoneId: 'Europe/Paris' });
    const ws = { id: 'mandate-qa', slug: 'showcase', name: 'Showcase', role: 'owner', role_template: 'workspace_owner', settings: { features: { experience_v1: true } } };
    const user = { id: 'reviewer', username: 'reviewer', email: 'reviewer@example.test', role: 'admin', is_active: true, workspaces: [ws] };
    const pending = { id: 'work-run-1', system_id: 'northforge', status: 'hitl_pending', flow_sha256: 'flow-version-3', hitl: {
      decision_id: 'gate-1', decision_status: 'proposed', node_id: 'review', decision_title: locale === 'fr' ? 'Partager le dossier d’intervention' : 'Share the intervention dossier',
      prompt: locale === 'fr' ? 'Examiner le destinataire et le dossier avant leur transmission.' : 'Review the recipient and dossier before sharing.',
      expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString().replace('Z', ''), upstream: { recipient: 'Maintenance', document: 'NF-04 · intervention summary · version 3' },
    } };
    let decided = false; const submissions = []; const errors = [];
    const proof = () => ({ run_id: pending.id, system_id: pending.system_id, status: decided ? 'running' : 'hitl_pending',
      applied: { state: 'not_recorded', policy_id: null, revision: null, snapshot_at: null, mode: null, version: null, spec: null },
      events: [{ id: 'decision:gate-1', kind: 'hitl_approval', facet: 'outbound', status: decided ? 'approved' : 'awaiting_human', at: '2026-09-17T10:00:00', node_id: 'review', invocation_id: null, decision_id: 'gate-1', rule: 'expert_review_required', details: { human_confirmed: decided } }],
      counts: { recorded_events: 1, blocked: 0, awaiting_human: decided ? 0 : 1 }, limitations: ['historical_mandate_spec_not_recorded'],
    });
    const experience = { id: 'review-app', slug: 'mandate-review', name: 'NorthForge', pattern: 'approval', languages: ['fr', 'en'] };
    const release = { id: 'release-1', renderer_version: 'certified-components-0.2.0', theme: { mode: theme }, languages: ['fr', 'en'], bindings_snapshot: [{ system_id: 'northforge' }], pages: { pages: [{ id: 'home', title: 'NorthForge', components: [] }] } };
    await context.addInitScript(({ theme, locale }) => {
      localStorage.setItem('agentium_token', 'Bearer local-qa-token'); localStorage.setItem('agentium_workspace_slug', 'showcase');
      localStorage.setItem('agentium_locale', locale); localStorage.setItem('agentium_theme', theme);
    }, { theme, locale });
    const page = await context.newPage(); page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => { if (m.type() === 'error' && /ERROR|NG[0-9]/.test(m.text())) errors.push(m.text()); });
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname.replace(/^\/api\/v1/, '');
      const json = body => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
      if (path === '/auth/validate') return json({ valid: true, user_id: user.id, role: 'admin' });
      if (path === '/auth/me') return json(user);
      if (path === '/auth/workspaces') return json([ws]);
      if (path === '/auth/workspaces/showcase') return json(ws);
      if (path === '/work/mandate-review') return json({ experience, release, channel: 'live' });
      if (path === '/work/mandate-review/validations') return json({ runs: decided ? [] : [pending] });
      if (path === '/runs/work-run-1/mandate') return json(proof());
      if (path === '/runs/work-run-1/hitl') {
        submissions.push(route.request().postDataJSON()); decided = true;
        return json({ ...pending, status: 'running', hitl: null });
      }
      if (path === '/runs/work-run-1') return json({ ...pending, status: decided ? 'running' : 'hitl_pending' });
      return json({});
    });
    await page.goto(`${base}/work/mandate-review/validations`, { waitUntil: 'domcontentloaded' });
    const review = page.getByRole('button', { name: locale === 'fr' ? 'Examiner la demande' : 'Review request', exact: true });
    await review.waitFor({ timeout: 25000 });
    assert.equal(await page.locator('app-work-decision-context').count(), 0);
    await review.click();
    await page.locator('app-work-decision-context').waitFor();
    assert.equal(submissions.length, 0, 'Review is not approval');
    assert.equal(await page.locator('.xp-work-hitl textarea').inputValue(), '');
    const scope = page.locator('app-work-decision-context');
    await scope.locator('summary').click();
    assert.match(await scope.innerText(), /Maintenance/);
    assert.match(await scope.innerText(), /flow-version-3/);
    assert.match(await scope.locator('a').getAttribute('href'), /\/runs\/work-run-1/);
    await page.screenshot({ path: `${out}/work-review-${theme}-${locale}.png` });
    await page.locator('.xp-work-hitl article .xp-work-hitl-actions button').first().click();
    await page.locator('.xp-work-hitl > .xp-work-note[role=status]').waitFor();
    assert.equal(submissions.length, 1);
    assert.equal(submissions[0].action, 'accept');
    assert.equal(submissions[0].expected_decision_id, 'gate-1');
    await page.locator('.xp-work-note app-run-mandate a').first().waitFor();
    assert.match(await page.locator('.xp-work-note app-run-mandate a').first().getAttribute('href'), /\/runs\/work-run-1/);
    await page.screenshot({ path: `${out}/work-decision-recorded-${theme}-${locale}.png` });
    assert.deepEqual(errors, []);
    report.push({ theme, locale, fixture: true, reviewed_before_submit: true, expected_decision_id: 'gate-1', exact_run_link: true, errors });
    await context.close();
  }
} finally {
  await browser.close(); writeFileSync(`${out}/work-visual-report.json`, JSON.stringify(report, null, 2));
}
console.log(`${report.length} Work review → approval → exact Run journeys passed; synthetic API fixtures.`);
