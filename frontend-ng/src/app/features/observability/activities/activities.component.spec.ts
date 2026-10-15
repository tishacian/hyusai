import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { BehaviorSubject, of } from 'rxjs';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { ActivitiesComponent } from './activities.component';
import { ActivityApiError, ActivityApiService } from './activity-api.service';
import type { ActivityDetail, ActivityFeatures, ActivityPage } from './activity.models';

const features: ActivityFeatures = { enabled: true, scopes: ['workspace', 'system'], kinds: ['compute_run'], statuses: ['running', 'cancelled'] };
const detail: ActivityDetail = { id: 'compute:1', native_id: '1', kind: 'compute_run', workspace_id: 'a', system_id: 's1', run_id: null, parent_activity_id: null,
  status: 'running', native_status: 'running', version: 7, created_at: '2026-10-15T00:00:00Z', started_at: null, finished_at: null, updated_at: '2026-10-15T00:00:00Z', progress: null,
  measurements: { duration_ms: 3, provider_cost_usd: null, cost_known: false }, links: [], capabilities: { cancel: true }, attempts: [], evidence: [], events: [], commands: [] };
const page: ActivityPage = { items: [detail], total: 800, has_more: true, offset: 0, limit: 25, aggregates: { total: 800, by_kind: { compute_run: 800 }, by_status: { running: 800 } }, snapshot_cursor: 'c1' };

function setup(overrides: Record<string, unknown> = {}, query: Record<string, string> = {}) {
  const params = new BehaviorSubject(convertToParamMap(query));
  const navigations: unknown[] = []; let platformCalls = 0; let listCalls = 0; let reset: (() => void) | undefined;
  const api = { features: async () => features, list: async () => { listCalls++; return page; }, detail: async () => detail,
    events: async () => ({ items: [], next_cursor: '', has_more: false }), platform: async () => { platformCalls++; return {}; },
    follow: async (options: { state: (state: string) => void }) => options.state('live'), ...overrides };
  const injector = Injector.create({ providers: [ActivitiesComponent,
    { provide: AuthStore, useValue: { registerContextReset: () => () => undefined, captureRequestScope: () => ({}), isRequestScopeCurrent: () => true } },
    { provide: CanonicalApiService, useValue: { listSystems: () => of([]) } },
    { provide: I18nService, useValue: { t: (key: string) => key, locale: () => 'fr' } },
    { provide: WorkspaceService, useValue: { captureRequestScope: () => ({}), isRequestScopeCurrent: () => true, registerContextReset: (callback: () => void) => { reset = callback; return () => undefined; } } },
    { provide: ActivatedRoute, useValue: { queryParamMap: params.asObservable() } },
    { provide: Router, useValue: { navigate: (_: unknown, options: unknown) => { navigations.push(options); return Promise.resolve(true); } } },
    { provide: ActivityApiService, useValue: api },
  ] });
  const component = injector.get(ActivitiesComponent);
  return { component, params, navigations, counts: () => ({ listCalls, platformCalls }), reset: () => reset?.() };
}

test('feature off preserves legacy operations and never loads activities', async () => {
  const { component, counts } = setup({ features: async () => ({ ...features, enabled: false }) });
  await component.ngOnInit(); assert.equal(component.features()?.enabled, false); assert.equal(counts().listCalls, 0); component.ngOnDestroy();
});

test('platform query parameter cannot grant platform scope to a workspace owner', async () => {
  const { component, counts } = setup({}, { scope: 'platform' });
  await component.ngOnInit(); assert.equal(counts().platformCalls, 0); assert.equal(component.error(), 'forbidden'); component.ngOnDestroy();
});

test('pagination retains exact server total and merges links with System and period context', async () => {
  const { component, navigations } = setup({}, { systemId: 's1', since: '30d' });
  await component.ngOnInit(); assert.equal(component.scope(), 'system'); assert.equal(component.page()?.total, 800);
  component.nextPage(1); assert.deepEqual((navigations[0] as { queryParams: unknown }).queryParams, { offset: 25, activityId: null });
  assert.equal((navigations[0] as { queryParamsHandling: string }).queryParamsHandling, 'merge'); component.ngOnDestroy();
});

test('an interrupted command reuses its exact idempotency key and version; applied never claims termination', async () => {
  const commands: Array<{ version: number; key: string }> = [];
  const { component } = setup({ command: async (_id: string, version: number, key: string) => {
    commands.push({ version, key }); if (commands.length === 1) throw new TypeError('connection lost');
    return { id: 'cmd1', activity_id: detail.id, action: 'cancel', status: 'applied', created_at: detail.created_at, error_code: null };
  } }, { activityId: detail.id });
  await component.ngOnInit(); await component.cancel();
  assert.equal(component.commandUncertain(), true); assert.equal(component.detail()?.status, 'running');
  await component.cancel(); assert.deepEqual(commands[0], commands[1]); assert.equal(commands[0].version, 7);
  assert.equal(component.command()?.status, 'applied'); assert.equal(component.detail()?.status, 'running'); component.ngOnDestroy();
});

test('version conflict reloads evidence and requires a new deliberate confirmation', async () => {
  const { component } = setup({ command: async () => { throw new ActivityApiError(409, 'ACTIVITY_VERSION_CONFLICT'); } }, { activityId: detail.id });
  await component.ngOnInit(); component.confirmCancel.set(true); await component.cancel();
  assert.equal(component.confirmCancel(), false); assert.equal(component.commandUncertain(), false); assert.equal(component.detailError(), 'conflict'); component.ngOnDestroy();
});

test('stale streams disable mutation and permission revocation purges cached data', async () => {
  let state: ((state: string) => void) | undefined; let commandCalls = 0;
  const { component } = setup({ follow: async (options: { state: (state: string) => void }) => { state = options.state; state('live'); }, command: async () => { commandCalls++; } }, { activityId: detail.id });
  await component.ngOnInit(); assert.equal(component.canCancel(), true);
  state!('reconnecting'); await component.cancel(); assert.equal(commandCalls, 0); assert.equal(component.canCancel(), false);
  state!('revoked'); assert.equal(component.page(), null); assert.equal(component.detail(), null); assert.equal(component.events().length, 0); component.ngOnDestroy();
});

test('losing access to the selected native Run clears its detail on revalidation', async () => {
  let allowed = true;
  const { component } = setup({ detail: async () => { if (!allowed) throw new ActivityApiError(404, 'ACTIVITY_NOT_FOUND'); return detail; } }, { activityId: detail.id });
  await component.ngOnInit(); assert.equal(component.detail()?.id, detail.id);
  allowed = false; await component.loadDetail(detail.id);
  assert.equal(component.detail(), null); assert.equal(component.events().length, 0); assert.equal(component.canCancel(), false);
  assert.equal(component.detailError(), 'detail_unavailable'); component.ngOnDestroy();
});

test('the newest command is selected from the server descending ledger', async () => {
  const { component } = setup({ detail: async () => ({ ...detail, commands: [
    { id: 'new', status: 'requested' }, { id: 'old', status: 'failed' },
  ] }) }, { activityId: detail.id });
  await component.ngOnInit(); assert.equal(component.command()?.id, 'new'); assert.equal(component.canCancel(), false); component.ngOnDestroy();
});
