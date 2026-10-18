import '@angular/compiler';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { Injector, ɵChangeDetectionScheduler as ChangeDetectionScheduler, ɵEffectScheduler as EffectScheduler } from '@angular/core';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { BehaviorSubject, of } from 'rxjs';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceFetchService } from '@app/core/workspace-fetch.service';
import { AuthStore } from '@app/store/auth.store';
import { WorkspaceMonitorComponent } from '../workspace-monitor.component';
import { ActivitiesComponent } from './activities.component';
import { ActivitySeriesComponent } from './activity-series.component';
import { ActivityApiError, ActivityApiService } from './activity-api.service';
import type { StreamOptions } from './activity-stream';
import type { ActivityDetail, ActivityEvent, ActivityFeatures, ActivityPage } from './activity.models';

const features: ActivityFeatures = { enabled: true, scopes: ['workspace', 'system'], kinds: ['compute_run'], statuses: ['running', 'cancelled'] };
const detail: ActivityDetail = { id: 'compute:1', native_id: '1', kind: 'compute_run', workspace_id: 'a', system_id: 's1', run_id: null, parent_activity_id: null,
  status: 'running', native_status: 'running', version: 7, created_at: '2026-10-15T00:00:00Z', started_at: null, finished_at: null, updated_at: '2026-10-15T00:00:00Z', progress: null,
  measurements: { duration_ms: 3, provider_cost_usd: null, cost_known: false }, links: [], capabilities: { cancel: true }, attempts: [], evidence: [], events: [], commands: [] };
const page: ActivityPage = { items: [detail], total: 800, has_more: true, offset: 0, limit: 25, aggregates: { total: 800, by_kind: { compute_run: 800 }, by_status: { running: 800 } }, snapshot_cursor: 'c1' };

function setup(overrides: Record<string, unknown> = {}, query: Record<string, string> = {}) {
  const params = new BehaviorSubject(convertToParamMap(query));
  const effects = new Set<{ dirty: boolean; run(): void }>();
  const seriesQueries: URLSearchParams[] = [];
  const navigations: unknown[] = []; let platformCalls = 0; let listCalls = 0; let reset: (() => void) | undefined;
  const api = { features: async () => features, list: async () => { listCalls++; return page; }, detail: async () => detail,
    events: async () => ({ items: [], next_cursor: '', has_more: false }), platform: async () => { platformCalls++; return {}; },
    follow: async (options: { state: (state: string) => void }) => options.state('live'), ...overrides };
  const injector = Injector.create({ providers: [ActivitiesComponent, ActivitySeriesComponent, WorkspaceMonitorComponent,
    { provide: AuthStore, useValue: { registerContextReset: () => () => undefined, captureRequestScope: () => ({}), isRequestScopeCurrent: () => true } },
    { provide: CanonicalApiService, useValue: { listSystems: () => of([]) } },
    { provide: I18nService, useValue: { t: (key: string) => key, locale: () => 'fr' } },
    { provide: WorkspaceService, useValue: { current: () => ({ id: 'workspace-a' }), captureRequestScope: () => ({}), isRequestScopeCurrent: () => true, registerContextReset: (callback: () => void) => { reset = callback; return () => undefined; } } },
    { provide: WorkspaceFetchService, useValue: { fetch: async (url: string) => { seriesQueries.push(new URL(url, 'https://agentium.test').searchParams); return Response.json({}); } } },
    { provide: ChangeDetectionScheduler, useValue: { notify() {} } },
    { provide: EffectScheduler, useValue: {
      add: (effect: { dirty: boolean; run(): void }) => effects.add(effect),
      schedule: (effect: { dirty: boolean; run(): void }) => effects.add(effect),
      remove: (effect: { dirty: boolean; run(): void }) => effects.delete(effect),
    } },
    { provide: ActivatedRoute, useValue: { queryParamMap: params.asObservable() } },
    { provide: Router, useValue: { navigate: (_: unknown, options: unknown) => { navigations.push(options); return Promise.resolve(true); } } },
    { provide: ActivityApiService, useValue: api },
  ] });
  const component = injector.get(ActivitiesComponent);
  const flush = () => {
    for (let pass = 0; pass < 20; pass++) {
      const dirty = [...effects].filter(effect => effect.dirty);
      if (!dirty.length) return;
      for (const effect of dirty) effect.run();
    }
    throw new Error('effects did not settle');
  };
  return { component, params, navigations, injector, flush, seriesQueries, counts: () => ({ listCalls, platformCalls }), reset: () => reset?.() };
}

test('feature off does not load activities; operations is an independent facet', async () => {
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

test('revocation closes the entire monitor including series and late refreshes cannot reopen it', async () => {
  let onState!: (state: string) => void;
  let resolveLate!: (page: ActivityPage) => void;
  let reads = 0;
  const state = setup({
    features: async () => ({ ...features, activity_series_enabled: true }),
    list: async () => ++reads === 1 ? page : new Promise<ActivityPage>(resolve => { resolveLate = resolve; }),
    follow: async (options: { state: (state: string) => void }) => { onState = options.state; onState('live'); },
  }, { activityId: detail.id });
  try {
    await state.component.ngOnInit();
    assert.equal(state.component.features()?.activity_series_enabled, true);
    assert.equal(state.component.detail()?.id, detail.id);
    const late = state.component.reload();
    onState('revoked');
    // @if(features()?.enabled) owns the complete subtree, including series.
    assert.equal(state.component.features(), null);
    assert.equal(state.component.page(), null); assert.equal(state.component.detail(), null);
    assert.deepEqual(state.component.systems(), []); assert.equal(state.component.selectedId(), '');
    assert.equal(state.component.streamState(), 'revoked'); assert.equal(state.component.error(), 'forbidden');
    resolveLate(page); await late;
    assert.equal(state.component.page(), null); assert.equal(state.component.features(), null);
    await state.component.reload(); assert.equal(reads, 2);
    assert.equal(state.component.loading(), false);
  } finally { state.injector.destroy(); }
});

test('a revoked stream at connection time cannot load the selected detail afterwards', async () => {
  let detailReads = 0;
  const { component, injector } = setup({
    features: async () => ({ ...features, activity_series_enabled: true }),
    detail: async () => { detailReads++; return detail; },
    follow: async (options: { state: (state: string) => void }) => options.state('revoked'),
  }, { activityId: detail.id });
  try {
    await component.ngOnInit();
    assert.equal(component.features(), null); assert.equal(component.page(), null);
    assert.equal(component.detail(), null); assert.equal(detailReads, 0);
  } finally { injector.destroy(); }
});

test('destroying a series clears cached measures and rejects a late response', async () => {
  const state = setup({ features: async () => ({ ...features, activity_series_enabled: true }) });
  try {
    const chart = state.injector.get(ActivitySeriesComponent);
    state.flush(); await new Promise(resolve => setImmediate(resolve));
    assert.notEqual(chart.data(), null); assert.equal(chart.enabled(), true);
    let resolveLate!: (response: Response) => void;
    state.injector.get(WorkspaceFetchService).fetch = async () => new Promise<Response>(resolve => { resolveLate = resolve; });
    chart.mode.set('skill_cost'); state.flush(); await new Promise(resolve => setImmediate(resolve));
    chart.ngOnDestroy();
    assert.equal(chart.data(), null); assert.equal(chart.enabled(), false);
    resolveLate(Response.json({ totals: { total: 999 } }));
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(chart.data(), null); assert.equal(chart.enabled(), false);
  } finally { state.injector.destroy(); }
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

test('fixed period anchors use identical inclusive lower and exclusive upper bounds',async()=>{
 let requested:Record<string,unknown>={}; const {component}=setup({list:async(filters:Record<string,unknown>)=>{requested=filters;return page;}},{since:'24h',as_of:'2026-10-16T12:00:00Z'});
 await component.ngOnInit();assert.equal(requested['since'],'2026-10-15T12:00:00.000Z');assert.equal(requested['until'],'2026-10-16T12:00:00.000Z');component.ngOnDestroy();
});

test('the Running tile opens exactly pending, running and waiting with the original System and clock', () => {
  const { injector } = setup();
  try {
    const monitor = injector.get(WorkspaceMonitorComponent);
    monitor.systemId.set('system-a'); monitor.window.set('30d'); monitor.asOf.set('2026-10-18T09:33:42.737Z');
    const source = readFileSync('src/app/features/observability/workspace-monitor.component.ts', 'utf8');
    const tile = source.match(/<a\b[^>]*data-testid="operations-tile-running"[^>]*>/)?.[0];
    assert.match(tile || '', /\[queryParams\]="tileQuery\(activeStatusFilter\)"/);
    assert.deepEqual(monitor.tileQuery(monitor.activeStatusFilter), {
      facet: 'activities', systemId: 'system-a', since: '30d', as_of: '2026-10-18T09:33:42.737Z',
      kind: 'run', status: 'pending,running,waiting',
    });
    assert.equal(monitor.tileQuery('failed').status, 'failed');
    assert.equal(monitor.tileQuery().status, null);
  } finally { injector.destroy(); }
});

test('active drill-down keeps list and series filters across pagination, drafts, application and browser reload', async () => {
  const requests: Array<Record<string, unknown>> = [];
  let query: Record<string, string> = {
    facet: 'activities', systemId: 'system-a', kind: 'run', status: 'pending,running,waiting',
    since: '30d', as_of: '2026-10-18T09:33:42.737Z',
  };
  const overrides = {
    features: async () => ({ ...features, activity_series_enabled: true, statuses: ['pending', 'running', 'waiting', 'failed'] }),
    list: async (filters: Record<string, unknown>) => { requests.push(filters); return page; },
  };
  const state = setup(overrides, query);
  try {
    await state.component.ngOnInit();
    const chart = state.injector.get(ActivitySeriesComponent);
    // Use the same bindings as the real template while retaining Angular signal tracking.
    const template = readFileSync('src/app/features/observability/activities/activities.component.html', 'utf8');
    for (const key of ['systemId', 'kind', 'status', 'since', 'asOf'] as const) {
      assert.ok(template.includes(`[${key}]="appliedFilters().${key}"`));
      Object.defineProperty(chart, key, { value: () => state.component.appliedFilters()[key] });
    }
    assert.match(template, /<option \[value\]="activeStatusFilter">{{ t\('status_active'\) }}<\/option>/);
    state.flush(); await new Promise(resolve => setImmediate(resolve));
    const assertConsistent = (status: string, offset: number) => {
      const list = requests.at(-1)!; const series = state.seriesQueries.at(-1)!;
      assert.equal(list['status'], status); assert.equal(series.get('status'), status);
      assert.equal(list['kind'], 'run'); assert.equal(series.get('kind'), 'run');
      assert.equal(list['system_id'], 'system-a'); assert.equal(series.get('system_id'), 'system-a');
      assert.equal(list['since'], series.get('from')); assert.equal(list['until'], series.get('until'));
      assert.equal(list['offset'], offset);
    };
    const applyNavigation = async () => {
      const navigation = state.navigations.at(-1) as { queryParams: Record<string, string | number | null>; queryParamsHandling: string };
      assert.equal(navigation.queryParamsHandling, 'merge');
      for (const [key, value] of Object.entries(navigation.queryParams)) {
        if (value === null) delete query[key]; else query[key] = String(value);
      }
      state.params.next(convertToParamMap(query));
      state.flush(); await new Promise(resolve => setImmediate(resolve));
    };
    assertConsistent('pending,running,waiting', 0);
    state.component.nextPage(1); await applyNavigation();
    assertConsistent('pending,running,waiting', 25);
    // A draft edit must not change either population during an SSE-triggered refresh.
    state.component.status = 'failed';
    await state.component.reload(); state.flush();
    assertConsistent('pending,running,waiting', 25);
    state.component.applyFilters(); await applyNavigation();
    assertConsistent('failed', 0);
    state.component.status = state.component.activeStatusFilter;
    state.component.applyFilters(); await applyNavigation();
    assertConsistent('pending,running,waiting', 0);
    const reloaded = setup(overrides, query);
    try {
      await reloaded.component.ngOnInit();
      assert.equal(reloaded.component.status, 'pending,running,waiting');
      assert.equal(reloaded.component.appliedFilters().status, 'pending,running,waiting');
      assert.equal(requests.at(-1)!['status'], 'pending,running,waiting');
    } finally { reloaded.injector.destroy(); }
  } finally { state.injector.destroy(); }
});

test('nonstandard status unions remain visible in the filter rather than appearing as All', async () => {
  const { component, injector } = setup({}, { status: 'failed,cancelled' });
  try {
    await component.ngOnInit();
    assert.equal(component.status, 'failed,cancelled');
    assert.equal(component.statusFilterLabel(component.status), 'failed / cancelled');
    const template = readFileSync('src/app/features/observability/activities/activities.component.html', 'utf8');
    assert.match(template, /<option \[value\]="status">{{ statusFilterLabel\(status\) }}<\/option>/);
  } finally { injector.destroy(); }
});

test('cost series retain the selected state union while declaring their own kind and finished basis', async () => {
  const state = setup({ features: async () => ({ ...features, activity_series_enabled: true }) });
  try {
    const chart = state.injector.get(ActivitySeriesComponent);
    Object.defineProperty(chart, 'status', { value: () => 'failed,cancelled' });
    Object.defineProperty(chart, 'kind', { value: () => 'run' });
    Object.defineProperty(chart, 'asOf', { value: () => '2026-10-18T09:33:42.737Z' });
    for (const [mode, kind] of [['skill_cost', 'skill_invocation'], ['compute_cost', 'compute_run']] as const) {
      chart.mode.set(mode); state.flush(); await new Promise(resolve => setImmediate(resolve));
      const query = state.seriesQueries.at(-1)!;
      assert.equal(query.get('status'), 'failed,cancelled');
      assert.equal(query.get('metric'), 'cost'); assert.equal(query.get('kind'), kind);
      assert.equal(query.get('time_basis'), 'finished');
    }
  } finally { state.injector.destroy(); }
});
for(const [status,expected] of [[404,'disabled'],[403,'forbidden'],[500,'load_error']] as const)test(`discovery ${status} remains explicit and never opens a stream`,async()=>{
 let streams=0;const {component,counts}=setup({features:async()=>{throw new ActivityApiError(status,'ERROR');},follow:async()=>{streams++;}});await component.ngOnInit();assert.equal(component.error(),expected);assert.equal(counts().listCalls,0);assert.equal(streams,0);component.ngOnDestroy();
});

test('resync replaces the stream with a fresh snapshot cursor and deduplicates its replay', async () => {
  const streams: StreamOptions[] = []; let reads = 0;
  const event = { id: 'event-42', activity_id: detail.id, sequence: 42 } as ActivityEvent;
  const { component } = setup({
    list: async () => ({ ...page, snapshot_cursor: `snapshot-${++reads}` }),
    detail: async () => ({ ...detail, events: [event] }),
    follow: async (options: StreamOptions) => { streams.push(options); options.state('live'); },
  }, { activityId: detail.id });
  try {
    await component.ngOnInit();
    assert.equal(streams[0].cursor, 'snapshot-1');
    streams[0].resync();
    assert.equal(streams[0].signal.aborted, true);
    assert.equal(component.detail(), null);
    assert.equal(component.canCancel(), false);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(streams.length, 2);
    assert.equal(streams[1].cursor, 'snapshot-2');
    streams[1].frame({ event: 'activity.updated', id: 'resume-42', data: JSON.stringify(event) });
    assert.equal(component.events().length, 1);
    assert.equal(component.events()[0].id, event.id);
  } finally { component.ngOnDestroy(); }
});
