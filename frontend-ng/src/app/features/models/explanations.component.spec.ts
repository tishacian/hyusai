import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { CounterfactualPanelComponent, errorKey } from './counterfactual-panel.component';
import { ProductionDebugComponent, runErrorKey } from './production-debug.component';
import type { CounterfactualAnswer, CounterfactualRequest } from './explanations.vm';
import { canRun, type ProductionDebugView, type ProductionReport } from './production-debug.vm';

function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void;
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

// ---------------------------------------------------------------------------
// What would change the answer
// ---------------------------------------------------------------------------

function panel(task: 'classification' | 'regression' = 'classification') {
  let active = true;
  const requests: { id: string; body: CounterfactualRequest }[] = [];
  let pending = deferred<CounterfactualAnswer>();
  const component = Object.assign(Object.create(CounterfactualPanelComponent.prototype), {
    modelId: () => 'm1', task: () => task, row: () => ({ tenure: 6 }), version: () => null,
    selected: signal<string[]>([]), targetClass: signal(''), min: signal(''), maxValue: signal(''),
    busy: signal(false), error: signal(''), answer: signal<CounterfactualAnswer | null>(null), generation: 0,
    workspace: { captureRequestScope: () => 'w', isRequestScopeCurrent: () => active },
    models: { counterfactuals: (id: string, body: CounterfactualRequest) => { requests.push({ id, body }); return pending.promise; } },
  }) as CounterfactualPanelComponent;
  return {
    component, requests,
    answer: (value: CounterfactualAnswer) => pending.resolve(value),
    fail: (error: unknown) => pending.reject(error),
    reset: () => { pending = deferred<CounterfactualAnswer>(); },
    switchWorkspace: () => { active = false; },
  };
}

const found = { status: 'found', results: [], refused: [], fields: [], evaluated: 3, budget: 2000, exhausted: false, current: { prediction: '1' }, target: { class: '0' } } as CounterfactualAnswer;

test('no field selected: nothing is sent and the panel says what is missing', async () => {
  const h = panel();
  await h.component.search();
  assert.equal(h.requests.length, 0);
  assert.equal(h.component.error(), 'models.play.cf.error.fields');
});

test('a regression without a range is refused before any request', async () => {
  const h = panel('regression');
  h.component.toggle('tenure');
  await h.component.search();
  assert.equal(h.requests.length, 0);
  assert.equal(h.component.error(), 'models.play.cf.error.range');
});

test('one search at a time, and its answer lands', async () => {
  const h = panel();
  h.component.toggle('tenure');
  h.component.targetClass.set('0');
  const first = h.component.search();
  await h.component.search();
  assert.equal(h.requests.length, 1);
  assert.deepEqual(h.requests[0], { id: 'm1', body: { row: { tenure: 6 }, fields: ['tenure'], target: { class: '0' } } });
  h.answer(found);
  await first;
  assert.equal(h.component.answer(), found);
  assert.equal(h.component.busy(), false);
});

test('an answer from a previous workspace never reaches the panel', async () => {
  const h = panel();
  h.component.toggle('tenure');
  const request = h.component.search();
  h.switchWorkspace();
  h.answer(found);
  await request;
  assert.equal(h.component.answer(), null);
});

test('server refusals become dictionary keys, never raw messages', async () => {
  const h = panel();
  h.component.toggle('tenure');
  const request = h.component.search();
  h.fail(new HttpErrorResponse({ status: 429, error: { detail: { code: 'ML_RATE_LIMITED', message: 'raw' } } }));
  await request;
  assert.equal(h.component.error(), 'models.play.cf.error.rate');
  assert.equal(errorKey(new Error('x')), 'models.play.cf.error.failed');
  assert.equal(
    errorKey(new HttpErrorResponse({ status: 422, error: { detail: { code: 'ML_COUNTERFACTUAL_FIELDS_UNSUPPORTED' } } })),
    'models.play.cf.error.unsupported',
  );
});

// ---------------------------------------------------------------------------
// In production
// ---------------------------------------------------------------------------

function production(permissions: Record<string, boolean> | null, latest: ProductionReport | null = null) {
  let active = true;
  const runs: string[] = [];
  let pending = deferred<ProductionDebugView & { report: ProductionReport }>();
  const component = Object.assign(Object.create(ProductionDebugComponent.prototype), {
    modelId: () => 'm1', permissions: () => permissions, mode: () => 'evidence',
    view: signal<ProductionDebugView | null>(view(latest)), busy: signal(false), error: signal(''),
    generation: 0, timer: null, polls: 0,
    workspace: { captureRequestScope: () => 'w', isRequestScopeCurrent: () => active },
    models: { runProductionDebug: (id: string) => { runs.push(id); return pending.promise; } },
  }) as ProductionDebugComponent;
  // computed() fields are created by the constructor; run() reads this one.
  Object.assign(component, { runnable: () => canRun(component.view(), permissions) });
  return {
    component, runs,
    respond: (value: ProductionDebugView & { report: ProductionReport }) => pending.resolve(value),
    fail: (error: unknown) => pending.reject(error),
    switchWorkspace: () => { active = false; },
  };
}

function view(latest: ProductionReport | null): ProductionDebugView {
  return {
    supported: true, latest, series: [], fairness_columns: [],
    limits: { min_rows: 50, max_rows: 5000, interval_minutes: 1440, watch_gap: 0.05, alert_gap: 0.1, min_group_rows: 30 },
  };
}

function report(status: ProductionReport['status']): ProductionReport {
  return {
    id: 'r', model_id: 'm1', version: 1, trigger: 'manual', status, window: { from: null, until: null },
    counts: { labeled: 0, used: 0, excluded: {} }, metrics: {}, report: {}, fairness_badge: null,
    error_code: null, created_at: null, completed_at: null,
  };
}

test('a read-only member cannot start an analysis', async () => {
  const h = production({ read: true, score: false });
  await h.component.run();
  assert.equal(h.runs.length, 0);
});

test('an analysis already running is not started twice', async () => {
  const h = production({ score: true }, report('running'));
  await h.component.run();
  assert.equal(h.runs.length, 0);
});

test('a started analysis shows its staged report and polls while it runs', async () => {
  const h = production({ score: true });
  const run = h.component.run();
  assert.equal(h.component.busy(), true);
  h.respond({ ...view(report('queued')), report: report('queued') });
  await run;
  assert.equal(h.component.view()?.latest?.status, 'queued');
  assert.equal(h.component.busy(), false);
  const timer = (h.component as unknown as { timer: ReturnType<typeof setTimeout> | null }).timer;
  assert.notEqual(timer, null);
  clearTimeout(timer!);
});

test('a response from a previous workspace is dropped, and refusals are keys', async () => {
  const h = production({ score: true });
  const run = h.component.run();
  h.switchWorkspace();
  h.respond({ ...view(report('completed')), report: report('completed') });
  await run;
  assert.equal(h.component.view()?.latest, null);

  const refused = production({ score: true });
  const attempt = refused.component.run();
  refused.fail(new HttpErrorResponse({ status: 409, error: { detail: { code: 'ML_PRODUCTION_DEBUG_RUNNING' } } }));
  await attempt;
  assert.equal(refused.component.error(), 'models.production.error.running');
  assert.equal(runErrorKey(new Error('x')), 'models.production.error.failed');
});
