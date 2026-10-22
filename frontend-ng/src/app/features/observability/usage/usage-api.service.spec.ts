import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { WorkspaceFetchService } from '@app/core/workspace-fetch.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { UsageApiError, UsageApiService } from './usage-api.service';

function setup(fetch: (url: string, init: RequestInit & { workspaceSlug?: string }) => Promise<Response>, current = () => true): UsageApiService {
  return Injector.create({ providers: [UsageApiService,
    { provide: AuthStore, useValue: { captureRequestScope: () => ({ epoch: 1 }), isRequestScopeCurrent: () => true } },
    { provide: WorkspaceFetchService, useValue: { fetch } },
    { provide: WorkspaceService, useValue: { captureRequestScope: () => ({ workspaceSlug: 'a' }), isRequestScopeCurrent: current } },
  ] }).get(UsageApiService);
}
test('budget activation uses optimistic revision and is never retried on a conflict', async () => {
  let calls = 0;
  const api = setup(async (url, init) => {
    calls++; assert.equal(url, '/api/v1/observability/usage/budgets'); assert.equal(init.workspaceSlug, 'a');
    assert.equal(JSON.parse(String(init.body)).expected_revision, 7); assert.equal(JSON.parse(String(init.body)).enabled, true);
    return Response.json({ detail: { code: 'USAGE_BUDGET_REVISION_CONFLICT' } }, { status: 409 });
  });
  await assert.rejects(api.saveBudget({ scope: 'workspace', expected_revision: 7, enabled: true, timezone: 'Europe/Paris', max_tokens: 100, currency_limits: { EUR: '10' } }), (error: unknown) => error instanceof UsageApiError && error.code === 'USAGE_BUDGET_REVISION_CONFLICT');
  assert.equal(calls, 1);
});
test('Run accounting does not apply a dashboard time window and keeps unknown total', async () => {
  const api = setup(async (url, init) => {
    const query = new URL(url, 'https://agentium.test').searchParams;
    assert.equal(query.get('run_id'), 'run-a'); assert.equal(query.get('run_scope'), 'tree'); assert.equal(query.get('offset'), '10');
    assert.equal(query.has('window'), false); assert.equal(init.workspaceSlug, 'a');
    return Response.json({ items: [], total: null, offset: 0, limit: 10, coverage: { complete: false } });
  });
  assert.equal((await api.calls({ run_id: 'run-a', run_scope: 'tree', offset: 10, limit: 10 })).total, null);
});
test('usage evidence arriving after workspace switch is discarded', async () => {
  const api = setup(async () => Response.json({ private: 'cost-data' }), () => false);
  await assert.rejects(api.summary({}), { name: 'AbortError' });
});
test('versioned tariff rates retain unknown cache prices', async () => {
  const api = setup(async () => Response.json({ can_manage: true, items: [{ id: 'tariff-a', revision: 2, provider: 'a', model: 'm', currency: 'EUR', rates: { input_per_million: '0', output_per_million: '4', cached_input_per_million: null } }] }));
  const tariff = (await api.tariffs()).items[0];
  assert.equal(tariff.input_per_million, '0'); assert.equal(tariff.cached_input_per_million, null); assert.equal(tariff.revision, 2);
});
test('tariff reads retain declared provenance and call reads retain their own historical snapshot', async () => {
  const oldSource={reference:'Original price sheet',observed_on:'2026-10-20'};
  const newSource={reference:'New price sheet',observed_on:'2026-10-22'};
  const api=setup(async url => Response.json(url.includes('/calls') ? {items:[{id:'call-a',tariff_snapshot:{id:'old',revision:1,currency:'EUR',rates:{input_per_million:'1'},provenance:oldSource}}],total:1,offset:0,limit:25} : {can_manage:true,items:[{id:'new',revision:2,currency:'EUR',rates:{input_per_million:'2',output_per_million:'4'},provenance:newSource}]}));
  const tariff=(await api.tariffs()).items[0];assert.equal(tariff.input_per_million,'2');assert.deepEqual(tariff.provenance,newSource);
  const call=(await api.calls({})).items[0];assert.deepEqual(call.tariff_snapshot?.provenance,oldSource);assert.equal(call.tariff_snapshot?.revision,1);
});
