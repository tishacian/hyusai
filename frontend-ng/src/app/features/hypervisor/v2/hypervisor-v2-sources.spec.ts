import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ElementRef, Injector, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Subject, of, throwError, type Observable } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type DecisionRow } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { HypervisorV2Component } from './hypervisor-v2.component';
import type { HypervisorSeriesResponse } from './hypervisor-v2-series';

const SERIES: HypervisorSeriesResponse = {
  window: '30d',
  from: '2026-09-01',
  to: '2026-09-03',
  systems: [],
} as unknown as HypervisorSeriesResponse;

const DECISION = {
  id: 'dec-1',
  scope: 'portfolio',
  kind: 'budget',
  title: 'Raise the budget',
  status: 'proposed',
  created_at: '2026-09-02T00:00:00Z',
} as unknown as DecisionRow;

type Responder = () => Observable<unknown>;

/** A component wired to stub services; `routes` answers each raw GET by path. */
function impactView(routes: Record<string, Responder>) {
  const calls: string[] = [];
  const http = {
    get: (path: string) => {
      calls.push(path);
      const respond = routes[path];
      return respond ? respond() : of(null);
    },
  };
  const canonical = {
    hypervisorViews: () => of(null),
    listCapabilities: () => of([]),
    hypervisorBalanceSheet: () => of(null),
    hypervisorMapSettings: () => of(null),
  };
  const injector = Injector.create({
    providers: [
      { provide: ElementRef, useValue: new ElementRef({ querySelector: () => null }) },
      { provide: ApiService, useValue: http },
      { provide: CanonicalApiService, useValue: canonical },
      { provide: ActivatedRoute, useValue: {} },
      { provide: Router, useValue: { url: '/hypervisor', navigate: () => Promise.resolve(true) } },
      {
        provide: WorkspaceService,
        useValue: {
          current: signal(null),
          captureRequestScope: () => ({}),
          isRequestScopeCurrent: () => true,
          registerContextReset: () => () => {},
        },
      },
      {
        provide: I18nService,
        useValue: {
          t: (key: string, params?: Record<string, unknown>) =>
            params ? `${key} ${JSON.stringify(params)}` : key,
          locale: signal('fr'),
        },
      },
      { provide: HypervisorV2Component, useFactory: () => new HypervisorV2Component() },
    ],
  });
  return { view: injector.get(HypervisorV2Component), calls };
}

const fail = (status = 500): Responder => () => throwError(() => ({ status }));

test('a failed decisions request leaves the series, bases and recommendations rendered', () => {
  const { view } = impactView({
    '/hypervisor/series': () => of(SERIES),
    '/hypervisor/value-bases': () => of({ items: [{ capability_id: 'cap-1', name: 'Invoices' }] }),
    '/hypervisor/recommendations': () => of({ items: [{ id: 'r-1', title: 'Tune', scope: 'portfolio' }] }),
    '/hypervisor/decisions': fail(),
  });
  view.reload();

  assert.equal(view.loading(), false);
  assert.equal(view.loadProblem(), null, 'one failure is not a page problem');
  assert.deepEqual(view.sourceStates(), {
    series: 'ready',
    bases: 'ready',
    decisions: 'unavailable',
    recos: 'ready',
  });
  assert.ok(view.series(), 'the series still renders');
  assert.equal(view.bases().length, 1);
  assert.equal(view.recommendations().length, 1);
  assert.equal(view.decisions().length, 0);
});

test('a failed series keeps the decisions and is never shown as an empty series', () => {
  const { view } = impactView({
    '/hypervisor/series': fail(502),
    '/hypervisor/value-bases': () => of({ items: [] }),
    '/hypervisor/recommendations': () => of({ items: [] }),
    '/hypervisor/decisions': () => of({ items: [DECISION] }),
  });
  view.reload();

  assert.equal(view.sourceStates().series, 'unavailable');
  assert.equal(view.series(), null);
  assert.equal(view.decisions().length, 1);
  assert.equal(view.firstProposed()?.id, 'dec-1');
});

test('retry re-requests only the failed source and restores its block', () => {
  let decisionsUp = false;
  const pending = new Subject<unknown>();
  const { view, calls } = impactView({
    '/hypervisor/series': () => of(SERIES),
    '/hypervisor/value-bases': () => of({ items: [] }),
    '/hypervisor/recommendations': () => of({ items: [] }),
    '/hypervisor/decisions': () => (decisionsUp ? pending : throwError(() => ({ status: 500 }))),
  });
  view.reload();
  assert.equal(view.sourceStates().decisions, 'unavailable');
  const before = calls.length;

  decisionsUp = true;
  view.retrySource('decisions');
  assert.deepEqual(calls.slice(before), ['/hypervisor/decisions'], 'only the failed source is requested again');
  assert.equal(view.sourceStates().decisions, 'loading');
  assert.equal(view.sourceRetrying('decisions'), true);

  view.retrySource('decisions');
  assert.equal(calls.length, before + 1, 'a retry in flight is not doubled');

  pending.next({ items: [DECISION] });
  pending.complete();
  assert.equal(view.sourceStates().decisions, 'ready');
  assert.equal(view.decisions().length, 1);
  assert.equal(view.sourceStates().series, 'ready', 'other sources are untouched');
  assert.match(view.sourceAnnouncement(), /hypervisor\.v2\.source\.loaded/);
});

test('a retry that fails again stays unavailable without an announcement', () => {
  const { view } = impactView({
    '/hypervisor/series': () => of(SERIES),
    '/hypervisor/value-bases': fail(),
    '/hypervisor/recommendations': () => of({ items: [] }),
    '/hypervisor/decisions': () => of({ items: [] }),
  });
  view.reload();
  view.retrySource('bases');
  assert.equal(view.sourceStates().bases, 'unavailable');
  assert.equal(view.sourceAnnouncement(), '');
});

test('denied series access and a total outage stay page-level problems', () => {
  const denied = impactView({ '/hypervisor/series': fail(403) }).view;
  denied.reload();
  assert.equal(denied.loadProblem(), 'experience.adoption.access_denied');

  const down = impactView({
    '/hypervisor/series': fail(),
    '/hypervisor/value-bases': fail(),
    '/hypervisor/recommendations': fail(),
    '/hypervisor/decisions': fail(),
  }).view;
  down.reload();
  assert.equal(down.loadProblem(), 'experience.adoption.load_failed');
});

test('the ratio fact is secondary and the hero reads as one sentence', () => {
  const { view } = impactView({
    '/hypervisor/series': () => of(SERIES),
    '/hypervisor/value-bases': () => of({ items: [] }),
    '/hypervisor/recommendations': () => of({ items: [] }),
    '/hypervisor/decisions': () => of({ items: [] }),
  });
  view.reload();
  assert.equal(view.pageTitle(), 'hypervisor.v2.page.title');
  assert.equal(view.riversTitle(), 'hypervisor.v2.rivers.title.hours');
  assert.equal(view.valueDeclaredShare(), '', 'no declared value, no share');

  Object.assign(view, {
    monument: () => ({ value: '2 496', unit: 'h' }),
    provenance: () => ({ measured: 0.38, declared: 0.62, measuredPct: '38 %', declaredPct: '62 %' }),
    dayCount: () => 91,
  });
  assert.equal(view.measuredPart(), 'hypervisor.v2.hero.measured_part.hours {"pct":"38 %"}');
  const label = view.monumentLabel();
  assert.match(label, /^hypervisor\.v2\.hero\.monument_label_measured /);
  assert.match(label, /"amount":"2 496"/, 'the hours unit is carried by the sentence, not repeated');
  assert.match(label, /hero\.sentence\.hours/);
  assert.match(label, /measured_part\.hours/);
});
