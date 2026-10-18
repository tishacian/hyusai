import {expect, test, type Page} from '@playwright/test';
import {writeFile} from 'node:fs/promises';
import {expectOk} from '../fixtures/api';
import {resolveNativeInvocation, visibleNativeInvocation} from '../fixtures/native-invocation';

// Native invocation deep links are independent of the Flow and series gates.
// This test does not qualify navigation from an open Flow or live transitions.
test.use({trace: 'off', video: 'off', screenshot: 'off', serviceWorkers: 'block', ignoreHTTPSErrors: false});

interface Target {runId: string; invocationId: string}
interface Features {enabled: boolean; activity_series_enabled: boolean; execution_view_enabled: boolean; scopes: string[]}
const profiles = {
  owner: {role: 'user', membership: 'owner', scopes: ['workspace', 'system']},
  restricted: {role: 'user', membership: 'member', scopes: ['workspace', 'system']},
  platform_admin: {role: 'admin', membership: 'member', scopes: ['workspace', 'system', 'platform']},
} as const;

function targets(): Target[] {
  const value: unknown = JSON.parse(process.env['E2E_INVOCATION_TARGETS'] || 'null');
  const id = (item: unknown): item is string => typeof item === 'string' && /^[a-zA-Z0-9_-]{1,100}$/.test(item);
  if (!Array.isArray(value) || !value.length || value.length > 10
    || value.some(item => !item || !id(item.runId) || !id(item.invocationId))) {
    throw new Error('E2E_INVOCATION_TARGETS must be a JSON array of 1–10 existing {runId, invocationId} pairs.');
  }
  return value.map(({runId, invocationId}) => ({runId, invocationId}));
}

async function releaseState(page: Page, revision: string): Promise<Features> {
  for (const path of ['/api/v1/build-info', '/build-info.json']) {
    const build = await expectOk<{revision: string; revision_verified: boolean}>(page, path);
    expect(build.revision).toBe(revision);
    expect(build.revision_verified).toBe(true);
  }
  const features = await expectOk<Features>(page, '/api/v1/observability/activities/features');
  expect(features.enabled).toBe(true);
  for (const [field, variable] of [
    ['activity_series_enabled', 'E2E_EXPECT_ACTIVITY_SERIES'],
    ['execution_view_enabled', 'E2E_EXPECT_EXECUTION_VIEW'],
  ] as const) {
    const expected = process.env[variable] || 'false';
    expect(['true', 'false'], `${variable} must be explicit true or false`).toContain(expected);
    expect(features[field], variable).toBe(expected === 'true');
  }
  return features;
}

test('native invocation links: exact authorized audit or projection survives reload on desktop and mobile', async ({page}, info) => {
  test.setTimeout(240_000);
  const username = process.env['E2E_USERNAME'];
  const password = process.env['E2E_PASSWORD'];
  const revision = process.env['E2E_EXPECTED_REVISION'] || '';
  const workspaceSlug = process.env['E2E_SHOWCASE_WORKSPACE_SLUG'] || 'agentium-showcase';
  const requestedProfile = process.env['E2E_OBSERVABILITY_PROFILE'] || 'owner';
  expect(Object.keys(profiles)).toContain(requestedProfile);
  const expectedProfile = profiles[requestedProfile as keyof typeof profiles];
  expect(Boolean(username && password), 'Explicit live credentials are required').toBe(true);
  expect(revision, 'Pin the exact deployed revision').toMatch(/^[a-f0-9]{40}$/);
  const selected = targets();
  const completed: string[] = [];
  const blockedWrites: string[] = [];
  const evidence: Record<string, unknown> = {revision, workspace: workspaceSlug, profile: requestedProfile,
    checked_at: new Date().toISOString(), targets: selected, completed,
    coverage: 'Native invocation deep links and reload only; no open Flow navigation or transitions'};
  let suppressedTelemetry = 0;
  let accepted = false;
  await page.route('**/*', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (['GET', 'HEAD', 'OPTIONS'].includes(request.method()) ||
      (request.method() === 'POST' && ['/api/v1/auth/login', '/api/v1/auth/refresh', '/api/v1/auth/validate'].includes(path))) {
      await route.continue();
    } else {
      if (request.method() === 'POST' && path === '/api/v1/audit') suppressedTelemetry++;
      else blockedWrites.push(`${request.method()} ${path}`);
      await route.abort('blockedbyclient');
    }
  });
  try {
    await page.goto('/auth/signin');
    const login = await page.evaluate(async ({username, password, workspaceSlug}) => {
      const response = await fetch('/api/v1/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email: username, password, remember_me: false})});
      const body = await response.json().catch(() => ({}));
      if (!response.ok || typeof body.token !== 'string') return {ok: false, status: response.status};
      localStorage.setItem('agentium_token', `Bearer ${body.token}`);
      if (typeof body.refresh_token === 'string') localStorage.setItem('agentium_refresh_token', body.refresh_token);
      localStorage.setItem('agentium_workspace_slug', workspaceSlug);
      return {ok: true, status: response.status};
    }, {username: username!, password: password!, workspaceSlug});
    expect(login.ok, `Authentication succeeds (HTTP ${login.status})`).toBe(true);
    const profile = await expectOk<{id: string; role: string; workspaces: Array<{slug: string; role: string}>}>(page, '/api/v1/auth/me');
    expect(profile.role).toBe(expectedProfile.role);
    expect(profile.workspaces.find(item => item.slug === workspaceSlug)?.role).toBe(expectedProfile.membership);
    evidence.principal_id = profile.id;
    const features = await releaseState(page, revision);
    expect([...features.scopes].sort()).toEqual([...expectedProfile.scopes].sort());
    evidence.initial_features = features;
    const resolved = [];
    for (const target of selected) {
      const invocation = await resolveNativeInvocation(page, {...target, workspaceSlug});
      resolved.push(invocation);
      for (const width of [1440, 390]) {
        await page.setViewportSize({width, height: 1000});
        await page.goto(`/runs/${encodeURIComponent(target.runId)}/invocations/${encodeURIComponent(target.invocationId)}`);
        await visibleNativeInvocation(page, invocation);
        await page.reload();
        await visibleNativeInvocation(page, invocation);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'No viewport-wide horizontal overflow').toBe(true);
        await page.locator('app-skill-invocation-view').screenshot({path: info.outputPath(`native-invocation-${target.invocationId}-${width}.png`)});
        completed.push(`${target.invocationId}-${width}-exact-native-view-and-reload`);
      }
    }
    evidence.resolved = resolved;
    evidence.final_features = await releaseState(page, revision);
    expect(blockedWrites).toEqual([]);
    accepted = true;
  } finally {
    const path = info.outputPath('native-invocation-evidence.json');
    await writeFile(path, JSON.stringify({...evidence, accepted, blocked_business_writes: blockedWrites,
      suppressed_navigation_audits: suppressedTelemetry}, null, 2));
    await info.attach('native-invocation-evidence', {contentType: 'application/json', path});
  }
});
