import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { WorkspaceFetchService } from '@app/core/workspace-fetch.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { ActivityApiError, ActivityApiService } from './activity-api.service';

function setup(fetch: (url: string, init: RequestInit & { workspaceSlug?: string }) => Promise<Response>, current = () => true): ActivityApiService {
  return Injector.create({ providers: [ActivityApiService,
    { provide: AuthStore, useValue: { captureRequestScope: () => ({ epoch: 1 }), isRequestScopeCurrent: () => true } },
    { provide: WorkspaceFetchService, useValue: { fetch } },
    { provide: WorkspaceService, useValue: { captureRequestScope: () => ({ workspaceSlug: 'a' }), isRequestScopeCurrent: current } },
  ] }).get(ActivityApiService);
}

test('commands submit expected version and stable key once; errors are never replaced with a success or retried', async () => {
  let calls = 0;
  const api = setup(async (url, init) => {
    calls++; assert.equal(url, '/api/v1/observability/activities/compute%3Aid/commands');
    assert.equal(init.workspaceSlug, 'a'); assert.equal(init.method, 'POST');
    assert.deepEqual(JSON.parse(String(init.body)), { action: 'cancel', expected_version: 17, idempotency_key: 'stable-key' });
    return new Response('{"detail":{"code":"ACTIVITY_VERSION_CONFLICT"}}', { status: 409 });
  });
  await assert.rejects(api.command('compute:id', 17, 'stable-key'), (error: unknown) => error instanceof ActivityApiError && error.status === 409);
  assert.equal(calls, 1);
});

test('list preserves server totals, pagination and immutable workspace scope', async () => {
  const api = setup(async (url, init) => {
    const parsed = new URL(url, 'https://agentium.test');
    assert.equal(parsed.searchParams.get('offset'), '25'); assert.equal(parsed.searchParams.get('system_id'), 'system-a');
    assert.equal(init.workspaceSlug, 'a');
    return Response.json({ items: [], total: 3011, has_more: true, offset: 25, limit: 25 });
  });
  assert.equal((await api.list({ offset: 25, limit: 25, system_id: 'system-a' })).total, 3011);
});

test('a late response after workspace switch is discarded', async () => {
  const api = setup(async () => Response.json({ items: ['private-data'] }), () => false);
  await assert.rejects(api.list({}), (error: unknown) => error instanceof Error && error.name === 'AbortError');
});

test('shell and view share capability discovery; one caller abort does not cancel another reader', async () => {
 let calls=0;let resolve!: (value:Response)=>void;const api=setup(async()=>{calls++;return new Promise<Response>(done=>{resolve=done;});});const stop=new AbortController();const shell=api.features(stop.signal);const view=api.features();stop.abort();resolve(Response.json({enabled:true,scopes:['workspace'],kinds:[],statuses:[]}));await assert.rejects(shell,{name:'AbortError'});assert.equal((await view).enabled,true);assert.equal((await api.features()).enabled,true);assert.equal(calls,1);
});
