import {expect, test, type Page} from '@playwright/test';
import {writeFile} from 'node:fs/promises';
import {expectOk} from '../fixtures/api';
import {resolveNativeInvocation, visibleNativeInvocation, type NativeInvocationEvidence} from '../fixtures/native-invocation';
import type {RunExecutionView} from '../../src/app/features/runs/run-execution.models';

// Real service, selected existing Runs only. This recipe does not create a Run,
// edit a Flow, revoke a grant, inject an event or qualify live transitions.
test.use({trace: 'off', video: 'off', screenshot: 'off', serviceWorkers: 'block', ignoreHTTPSErrors: false});

interface NativeRun {
  id: string; system_id: string | null; status: string;
  flow_evidence: {flow_version_id: string | null; flow_snapshot_sha256: string | null};
}
interface Features {enabled: boolean; execution_view_enabled: boolean; activity_series_enabled: boolean}

function selectedRuns(): string[] {
  const value = process.env['E2E_FLOW_RUN_IDS'] || '';
  const parsed: unknown = value.trim().startsWith('[') ? JSON.parse(value) : value.split(',').map(id => id.trim()).filter(Boolean);
  if (!Array.isArray(parsed) || !parsed.length || parsed.some(id => typeof id !== 'string' || !/^[a-zA-Z0-9_-]{1,100}$/.test(id))) {
    throw new Error('E2E_FLOW_RUN_IDS must list existing Run IDs, as JSON or comma-separated values. No synthetic fallback is allowed.');
  }
  return [...new Set(parsed as string[])];
}

async function releaseState(page: Page, revision: string): Promise<Features> {
  for (const path of ['/api/v1/build-info', '/build-info.json']) {
    const build = await expectOk<{revision: string; revision_verified: boolean}>(page, path);
    expect(build.revision, `${path}: exact deployed revision`).toBe(revision);
    expect(build.revision_verified).toBe(true);
  }
  const features = await expectOk<Features>(page, '/api/v1/observability/activities/features');
  expect(features.enabled, 'The durable activity journal must be open').toBe(true);
  expect(features.execution_view_enabled, 'Stop acceptance if the Flow read capability is closed').toBe(true);
  expect(features.activity_series_enabled, 'This release declares both R2 and R4 open').toBe(true);
  return features;
}

// Independent real transport read. Retain only frame names, never event payloads
// or authorization headers. A heartbeat proves connection, not a state change.
async function streamHandshake(page: Page, runId: string, cursor: string) {
  return page.evaluate(async ({runId, cursor}) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15_000);
    const names: string[] = [];
    let status = 0;
    let eventStream = false;
    try {
      const response = await fetch(`/api/v1/observability/activity-events/stream?${new URLSearchParams({run_id: runId, subtree: 'true', cursor})}`, {
        signal: controller.signal, cache: 'no-store', headers: {
          Accept: 'text/event-stream', 'Last-Event-ID': cursor,
          Authorization: localStorage.getItem('agentium_token') || '',
          'X-Workspace-Slug': localStorage.getItem('agentium_workspace_slug') || '',
        },
      });
      status = response.status;
      eventStream = response.headers.get('content-type')?.includes('text/event-stream') === true;
      if (!response.ok || !eventStream || !response.body) return {status, eventStream, names};
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      try {
        while (!names.includes('heartbeat') && names.length < 30) {
          const chunk = await reader.read();
          if (chunk.done) break;
          buffer += decoder.decode(chunk.value, {stream: true});
          let boundary: number;
          while ((boundary = buffer.indexOf('\n\n')) !== -1) {
            const frame = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const name = /^event:\s*([^\r\n]+)$/m.exec(frame)?.[1];
            if (name) names.push(name);
          }
        }
      } finally { await reader.cancel().catch(() => undefined); }
    } catch { /* Return protocol facts only, without leaking a fetch error. */ }
    finally { clearTimeout(timeout); controller.abort(); }
    return {status, eventStream, names};
  }, {runId, cursor});
}

async function visibleJobs(page: Page, expected: RunExecutionView): Promise<void> {
  const view = page.getByTestId('run-execution-view');
  await expect(page.getByTestId('execution-graph')).toBeVisible();
  await expect(view.locator('.job')).toHaveCount(expected.items.length);
  for (const item of expected.items) {
    const card = page.getByTestId(`execution-job-${item.native_id}`);
    await expect(card).toHaveCount(1);
    await expect(card.locator('p.mono').first()).toContainText(item.native_id);
    await expect(card.locator('dd').nth(0)).toHaveText(item.source);
    if (item.passage_id) await expect(card.locator('dd').nth(1)).toHaveText(item.passage_id);
    if (item.attempt_index != null) await expect(card.locator('dd').nth(2)).toHaveText(String(item.attempt_index));
    for (const link of item.links) {
      expect(link.href.startsWith('/') && !link.href.startsWith('//'), 'Native links remain application-scoped').toBe(true);
      expect(await card.locator('a').evaluateAll((anchors, href) => anchors.some(anchor => {
        const actual = new URL((anchor as HTMLAnchorElement).href);
        const wanted = new URL(href, location.origin);
        return actual.origin === wanted.origin && actual.pathname === wanted.pathname
          && [...wanted.searchParams].every(([key, value]) => actual.searchParams.get(key) === value);
      }), link.href), 'Each authorized API link remains attached to its own native job').toBe(true);
    }
  }
  await expect(view.locator('[role="alert"]')).toHaveCount(0);
  await expect(page.locator('app-flow-builder')).toHaveCount(0);
}

test('existing Flow Runs: native historical graph, jobs, keyboard, reload and real SSE handshake', async ({page}, info) => {
  test.setTimeout(240_000);
  const ids = selectedRuns();
  const username = process.env['E2E_USERNAME'];
  const password = process.env['E2E_PASSWORD'];
  const revision = process.env['E2E_EXPECTED_REVISION'] || '';
  const workspaceSlug = process.env['E2E_SHOWCASE_WORKSPACE_SLUG'] || 'agentium-showcase';
  expect(!!username && !!password, 'Explicit recipe credentials are required; no default account fallback').toBe(true);
  expect(/^[a-f0-9]{40}$/.test(revision), 'Pin the full deployed revision').toBe(true);
  const blockedWrites: string[] = [];
  const completed: string[] = [];
  const runs: Array<Record<string, unknown>> = [];
  const observedUiStreams: Array<{run_id: string; subtree: boolean; has_cursor: boolean; cursor_header_agrees: boolean}> = [];
  let suppressedTelemetry = 0;
  let accepted = false;
  await page.route('**/*', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (['GET', 'HEAD', 'OPTIONS'].includes(request.method()) ||
      (request.method() === 'POST' && ['/api/v1/auth/login', '/api/v1/auth/validate'].includes(path))) {
      await route.continue();
    } else {
      if (request.method() === 'POST' && path === '/api/v1/audit') suppressedTelemetry++;
      else blockedWrites.push(`${request.method()} ${path}`);
      await route.abort('blockedbyclient');
    }
  });
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname !== '/api/v1/observability/activity-events/stream') return;
    const cursor = url.searchParams.get('cursor');
    observedUiStreams.push({run_id: url.searchParams.get('run_id') || '', subtree: url.searchParams.get('subtree') === 'true',
      has_cursor: !!cursor, cursor_header_agrees: !!cursor && request.headers()['last-event-id'] === cursor});
  });
  try {
    await page.goto('/auth/signin');
    const login = await page.evaluate(async ({email, password, workspaceSlug}) => {
      const response = await fetch('/api/v1/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email, password, remember_me: false})});
      const body = await response.json().catch(() => ({}));
      if (!response.ok || typeof body.token !== 'string') return {ok: false, status: response.status};
      localStorage.setItem('agentium_token', `Bearer ${body.token}`);
      if (typeof body.refresh_token === 'string') localStorage.setItem('agentium_refresh_token', body.refresh_token);
      localStorage.setItem('agentium_workspace_slug', workspaceSlug);
      return {ok: true, status: response.status};
    }, {email: username!, password: password!, workspaceSlug});
    expect(login.ok, `Authentication must succeed (HTTP ${login.status})`).toBe(true);
    await releaseState(page, revision);
    const workspaces = await expectOk<Array<{slug: string}>>(page, '/api/v1/auth/workspaces');
    expect(workspaces.some(workspace => workspace.slug === workspaceSlug), 'Explicit Showcase membership').toBe(true);

    for (const id of ids) {
      const native = await expectOk<NativeRun>(page, `/api/v1/runs/${encodeURIComponent(id)}`);
      const endpoint = `/api/v1/runs/${encodeURIComponent(id)}/execution-view?limit=50`;
      const initial = await expectOk<RunExecutionView>(page, endpoint);
      expect(initial.schema_version).toBe(1);
      expect(initial.run.id).toBe(id);
      expect(initial.run.system_id).toBe(native.system_id);
      expect(initial.run.native_status).toBe(native.status);
      expect(initial.run.flow_version_id).toBe(native.flow_evidence.flow_version_id);
      expect(initial.graph.available, 'A frozen historical graph is required for this selected Run').toBe(true);
      expect(initial.graph.nodes.length).toBeGreaterThan(0);
      expect(initial.total, 'A recorded native job or checkpoint is required').toBeGreaterThan(0);
      expect(initial.capabilities.read_only).toBe(true);
      const record: Record<string, unknown> = {id, system_id: native.system_id, status: native.status,
        flow_version_id: initial.run.flow_version_id, flow_sha256: initial.run.flow_sha256,
        flow_snapshot_sha256: native.flow_evidence.flow_snapshot_sha256, coverage: initial.coverage,
        total: initial.total, first_page_items: initial.items.length, graph_nodes: initial.graph.nodes.length,
        sources: [...new Set(initial.items.map(item => item.source))],
        attempts: initial.items.filter(item => item.attempt_index != null).length,
        waiting: initial.items.filter(item => item.waiting_reason).length,
        subruns: initial.items.filter(item => item.source === 'run').length};
      runs.push(record);
      const invocation = initial.items.find(item => item.source === 'skill_invocation');
      let nativeInvocation: NativeInvocationEvidence | null = null;
      if (invocation) {
        const expectedPath = `/runs/${encodeURIComponent(id)}/invocations/${encodeURIComponent(invocation.native_id)}`;
        expect(invocation.links.some(link => link.rel === 'invocation' && link.href === expectedPath), 'Invocation link keeps the native Run and invocation identities').toBe(true);
        nativeInvocation = await resolveNativeInvocation(page, {
          runId: id, invocationId: invocation.native_id, workspaceSlug,
        });
        record.resolved_invocation = invocation.native_id;
        record.invocation_resolution = nativeInvocation;
      }
      const projected = initial.items.find(item => item.activity_id);
      if (projected) {
        const activity = await expectOk<{id: string; native_id: string; run_id: string | null}>(page,
          `/api/v1/observability/activities/${encodeURIComponent(projected.activity_id!)}`);
        expect(activity.id).toBe(projected.activity_id);
        expect(activity.native_id).toBe(projected.native_id);
        // A child Run's activity identifies that child; other jobs belong to
        // the selected root. Never infer ownership by timestamps or Skill name.
        expect(activity.run_id).toBe(projected.source === 'run' ? projected.native_id : id);
        record.resolved_activity = projected.activity_id;
      }
      for (const width of [1440, 390]) {
        await page.setViewportSize({width, height: 1000});
        await page.goto(`/runs/${encodeURIComponent(id)}?view=flow`);
        await visibleJobs(page, initial);
        if (nativeInvocation) {
          const expectedPath = `/runs/${encodeURIComponent(id)}/invocations/${encodeURIComponent(nativeInvocation.invocation_id)}`;
          const card = page.getByTestId(`execution-job-${nativeInvocation.invocation_id}`);
          const link = card.locator(`a[href="${expectedPath}"], a[href^="${expectedPath}?"]`).first();
          await expect(link).toBeVisible();
          await link.focus();
          await link.press('Enter');
          await visibleNativeInvocation(page, nativeInvocation);
          await page.reload();
          await visibleNativeInvocation(page, nativeInvocation);
          await page.goBack();
          await expect.poll(() => new URL(page.url()).pathname).toBe(`/runs/${encodeURIComponent(id)}`);
          await expect.poll(() => new URL(page.url()).searchParams.get('view')).toBe('flow');
          await visibleJobs(page, initial);
          completed.push(`${id}-${width}-native-invocation-keyboard-reload-back`);
        }
        const view = page.getByTestId('run-execution-view');
        await expect(view.locator('.execution-node')).toHaveCount(initial.graph.nodes.length);
        expect(await view.locator('.execution-node strong').allTextContents()).toEqual(initial.graph.nodes.map(node => node.label));
        const item = initial.items.find(candidate => initial.graph.nodes.some(node => node.id === candidate.node_id));
        expect(!!item, 'A job with an explicit snapshot node is required for node selection').toBe(true);
        const nodeIndex = initial.graph.nodes.findIndex(node => node.id === item!.node_id);
        const node = view.locator('nav.nodes').first().getByRole('button').nth(nodeIndex + 1);
        await node.focus();
        await node.press('Enter');
        await expect.poll(() => new URL(page.url()).searchParams.get('nodeId')).toBe(item!.node_id);
        const filtered = await expectOk<RunExecutionView>(page, `${endpoint}&node_id=${encodeURIComponent(item!.node_id!)}`);
        await visibleJobs(page, filtered);
        const selected = page.getByTestId(`execution-job-${filtered.items[0].native_id}`);
        await selected.locator('h3 button').focus();
        await selected.locator('h3 button').press('Enter');
        await expect.poll(() => new URL(page.url()).searchParams.get('attemptId')).toBe(filtered.items[0].id);
        await page.reload();
        await visibleJobs(page, filtered);
        await expect(selected).toHaveClass(/selected/);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'No viewport-wide horizontal overflow').toBe(true);
        await page.getByTestId('execution-graph').screenshot({path: info.outputPath(`historical-flow-${id}-${width}.png`)});
        await selected.screenshot({path: info.outputPath(`historical-job-${id}-${width}.png`)});
        completed.push(`${id}-${width}-historical-node-job-keyboard-reload`);
      }
      const fresh = await expectOk<RunExecutionView>(page, endpoint);
      expect(fresh.graph).toEqual(initial.graph);
      expect(fresh.run.flow_sha256).toBe(initial.run.flow_sha256);
      expect(fresh.run.flow_version_id).toBe(initial.run.flow_version_id);
      const freshNative = await expectOk<NativeRun>(page, `/api/v1/runs/${encodeURIComponent(id)}`);
      expect(freshNative.flow_evidence.flow_snapshot_sha256).toBe(native.flow_evidence.flow_snapshot_sha256);
      // This subscription is created by the application before the independent
      // transport probe below. It establishes cursor wiring, not live recovery.
      const uiStreams = observedUiStreams.filter(stream => stream.run_id === id);
      expect(uiStreams.length).toBeGreaterThan(0);
      expect(uiStreams.every(stream => stream.subtree && stream.has_cursor && stream.cursor_header_agrees)).toBe(true);
      record.ui_stream_requests = uiStreams.length;
      record.transport_handshake = await streamHandshake(page, id, fresh.snapshot_cursor);
      const handshake = record.transport_handshake as Awaited<ReturnType<typeof streamHandshake>>;
      expect(handshake.status).toBe(200);
      expect(handshake.eventStream).toBe(true);
      expect(handshake.names).toContain('snapshot');
      expect(handshake.names).toContain('heartbeat');
      expect(handshake.names).not.toContain('error');
      completed.push(`${id}-native-sse-handshake-historical-snapshot-stable`);
    }
    await releaseState(page, revision);
    expect(blockedWrites, 'No business mutation may be attempted').toEqual([]);
    accepted = true;
  } finally {
    const path = info.outputPath('flow-historical-evidence.json');
    await writeFile(path, JSON.stringify({revision, workspace: workspaceSlug, accepted, completed, runs,
      blocked_business_writes: blockedWrites, suppressed_navigation_audits: suppressedTelemetry,
      coverage: 'Existing historical Runs and real SSE handshake only',
      not_qualified: ['new composite execution', 'edit/publish between historical versions', 'live state transition',
        'disconnect during transition and durable replay', 'permission revocation', 'other IAM profiles']}, null, 2));
    await info.attach('flow-historical-evidence', {contentType: 'application/json', path});
  }
});
