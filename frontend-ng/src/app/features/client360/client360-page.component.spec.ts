import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { HttpClient } from '@angular/common/http';
import { Injector } from '@angular/core';
import { Subject } from 'rxjs';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { Client360PageComponent } from './client360-page.component';

interface HttpCall {
  url: string;
  body?: unknown;
  options?: { headers?: Record<string, string> };
  response: Subject<unknown>;
}

class WorkspaceStub {
  private slug = 'andritz';
  private epoch = 7;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({ workspaceSlug: this.slug, epoch: this.epoch });
  }

  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean {
    return scope.workspaceSlug === this.slug && scope.epoch === this.epoch;
  }

  registerContextReset(resetter: (transition: WorkspaceContextTransition) => void): () => void {
    this.resetters.add(resetter);
    return () => this.resetters.delete(resetter);
  }

  isDemoSafeMode(): boolean {
    return false;
  }

  switchWorkspace(): void {
    const transition: WorkspaceContextTransition = {
      previousSlug: this.slug,
      nextSlug: 'sentinel-ci',
      previousEpoch: this.epoch,
      nextEpoch: this.epoch + 1,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
    this.slug = transition.nextSlug;
    this.epoch = transition.nextEpoch;
  }
}

function createHarness() {
  const workspace = new WorkspaceStub();
  const patchCalls: HttpCall[] = [];
  const postCalls: HttpCall[] = [];
  const getCalls: HttpCall[] = [];
  const record = (calls: HttpCall[], url: string, options?: HttpCall['options'], body?: unknown) => {
    const response = new Subject<unknown>();
    calls.push({ url, body, options, response });
    return response.asObservable();
  };
  const http = {
    patch: (url: string, body: unknown, options?: HttpCall['options']) => record(patchCalls, url, options, body),
    post: (url: string, body: unknown, options?: HttpCall['options']) => record(postCalls, url, options, body),
    get: (url: string, options?: HttpCall['options']) => record(getCalls, url, options),
  };
  const injector = Injector.create({
    providers: [
      Client360PageComponent,
      { provide: WorkspaceService, useValue: workspace },
      { provide: HttpClient, useValue: http },
    ],
  });
  return {
    component: injector.get(Client360PageComponent),
    workspace,
    patchCalls,
    postCalls,
    getCalls,
  };
}

function workspaceHeader(call: HttpCall): string | undefined {
  return call.options?.headers?.['X-Workspace-Slug'];
}

test('Client360 pins validateMapping -> reload/run to A and cancels the chain on A -> B', () => {
  const harness = createHarness();
  const { component, workspace, patchCalls, postCalls, getCalls } = harness;

  try {
    component.validateMapping({ id: 'mapping-a', confidence: 0.4 } as never);
    assert.equal(workspaceHeader(patchCalls[0]), 'andritz');

    patchCalls[0].response.next({ mapping: { id: 'mapping-a' } });
    assert.equal(workspaceHeader(getCalls[0]), 'andritz', 'mapping reload stays pinned to A');
    assert.equal(workspaceHeader(postCalls[0]), 'andritz', 'engine run stays pinned to A');

    workspace.switchWorkspace();
    assert.equal(getCalls[0].response.observed, false);
    assert.equal(postCalls[0].response.observed, false);

    postCalls[0].response.next({ status: 'late-andritz-result' });
    assert.equal(component.engineResult(), null);
    assert.equal(getCalls.length, 1, 'a late A engine response cannot launch the refresh reads');
  } finally {
    component.ngOnDestroy();
  }
});

test('Client360 pins and cancels every runEngine refresh read before it can mutate B', () => {
  const harness = createHarness();
  const { component, workspace, postCalls, getCalls } = harness;

  try {
    component.runEngine(false);
    assert.equal(workspaceHeader(postCalls[0]), 'andritz');

    postCalls[0].response.next({ status: 'completed' });
    assert.deepEqual(
      getCalls.map((call) => call.url),
      [
        '/api/v1/client360/summary',
        '/api/v1/client360/mail-settings',
        '/api/v1/client360/mappings',
        '/api/v1/client360/opportunities',
        '/api/v1/client360/customers',
        '/api/v1/client360/alerts',
      ],
    );
    assert.deepEqual(getCalls.map(workspaceHeader), Array(6).fill('andritz'));

    workspace.switchWorkspace();
    assert.equal(component.loading(), false);
    assert.equal(component.engineResult(), null);
    assert.ok(getCalls.every((call) => !call.response.observed));

    getCalls[0].response.next({ positioning: {} });
    getCalls[1].response.next({ mail_settings: {} });
    getCalls[2].response.next({ items: [] });
    getCalls[3].response.next({ items: [] });
    getCalls[4].response.next({ items: [], total: 0, facets: { countries: [], technologies: [] } });
    getCalls[5].response.next({ alerts: [] });
    assert.equal(component.summary(), null);
    assert.equal(component.mailSettings(), null);
    assert.equal(component.mappingsResponse(), null);
    assert.equal(component.opportunitiesResponse(), null);
    assert.equal(component.customersResponse(), null);
    assert.equal(component.alertsResponse(), null);
  } finally {
    component.ngOnDestroy();
  }
});

test('Client360 annuaire selection pre-fills targeting and posts customer_keys on create', () => {
  const harness = createHarness();
  const { component, postCalls } = harness;

  try {
    component.toggleDirectoryCustomer('septona');
    component.toggleDirectoryCustomer('mogul');
    component.toggleDirectoryCustomer('mogul');
    component.toggleDirectoryCustomer('mogul');
    assert.deepEqual(component.directorySelection(), ['septona', 'mogul']);
    assert.equal(component.isDirectoryCustomerSelected('septona'), true);

    component.startCampaignFromSelection();
    assert.equal(component.view(), 'campaigns');
    assert.deepEqual(component.campaignTargetCustomerKeys(), ['septona', 'mogul']);
    assert.ok(component.campaignName.trim().length > 0, 'campaign name is pre-filled');

    component.campaignDueWithinWeeks = 12;
    component.createCampaign();
    const createCall = postCalls.find((call) => call.url === '/api/v1/client360/campaigns');
    assert.ok(createCall, 'campaign creation is posted');
    const body = createCall.body as {
      selection_criteria: { customer_keys?: string[]; due_within_weeks?: number };
    };
    assert.deepEqual(body.selection_criteria.customer_keys, ['septona', 'mogul']);
    assert.equal(body.selection_criteria.due_within_weeks, 12);

    createCall.response.next({
      campaign: {
        id: 'camp-1',
        name: 'Campagne annuaire (2 clients)',
        campaign_type: 'first_replacement',
        status: 'draft',
        selection_criteria: { customer_keys: ['septona', 'mogul'], due_within_weeks: 12 },
        targeted_count: 0,
        drafts_count: 0,
      },
    });
    assert.deepEqual(component.campaignTargetCustomerKeys(), [], 'targeting cleared after create');
    assert.deepEqual(component.directorySelection(), [], 'annuaire selection cleared after create');
  } finally {
    component.ngOnDestroy();
  }
});

test('Client360 surfaces dedup outcomes after campaign draft generation', () => {
  const harness = createHarness();
  const { component, postCalls } = harness;

  try {
    component.selectCampaign({
      id: 'camp-9',
      name: 'Batch',
      campaign_type: 'free',
      status: 'draft',
      selection_criteria: {},
      targeted_count: 4,
      drafts_count: 0,
    } as never);
    component.generateCampaignDrafts(false);
    const draftsCall = postCalls.find(
      (call) => call.url === '/api/v1/client360/campaigns/camp-9/drafts',
    );
    assert.ok(draftsCall, 'draft generation is posted');

    draftsCall.response.next({
      campaign: {
        id: 'camp-9',
        name: 'Batch',
        campaign_type: 'free',
        status: 'active',
        selection_criteria: {},
        targeted_count: 4,
        drafts_count: 1,
      },
      created: 1,
      skipped: { missing_contact_email: 2, active_campaign_conflict: 1 },
      drafts: [],
    });

    const outcome = component.campaignDraftsOutcome();
    assert.ok(outcome, 'dedup outcome is stored');
    assert.equal(outcome.campaignId, 'camp-9');
    assert.equal(outcome.followUp, false);
    assert.equal(outcome.created, 1);
    assert.equal(outcome.skippedTotal, 3);
    assert.deepEqual(
      outcome.skipped.map((entry) => entry.reason),
      ['missing_contact_email', 'active_campaign_conflict'],
    );
    assert.equal(outcome.skipped[0].label, 'email de contact manquant');
    assert.equal(component.campaignStatus(), '1 brouillon(s) genere(s) · 3 ignore(s)');
  } finally {
    component.ngOnDestroy();
  }
});

test('Client360 fiche next-due CTA targets the customer with a due window', () => {
  const harness = createHarness();
  const { component } = harness;

  try {
    component.startCampaignFromNextDue({
      customer: { id: 'septona', name: 'Septona', countries: [], hubs: [], technologies: [] },
      opportunities: [],
      mail_drafts: [],
      impact_events: [],
      market_signals: [],
      data_gaps: [],
    } as never);
    assert.equal(component.view(), 'campaigns');
    assert.deepEqual(component.campaignTargetCustomerKeys(), ['septona']);
    assert.equal(component.campaignDueWithinWeeks, 26);
    assert.equal(component.campaignType, 'renewal');
    assert.ok(component.campaignName.includes('Septona'));

    component.clearCampaignTargeting();
    assert.deepEqual(component.campaignTargetCustomerKeys(), []);
    assert.equal(component.campaignDueWithinWeeks, null);
  } finally {
    component.ngOnDestroy();
  }
});

test('Client360 fiche loads in two phases: payload without AI summary, then async summary merge', () => {
  const harness = createHarness();
  const { component, getCalls } = harness;

  try {
    component.selectDirectoryCustomer({ customer_key: 'septona', customer_name: 'Septona S.A.' } as never);
    const detailCall = getCalls.find((call) => call.url === '/api/v1/client360/customers/septona');
    assert.ok(detailCall, 'fiche payload requested');
    const params = (detailCall.options as { params?: { get(name: string): string | null } }).params;
    assert.equal(params?.get('include_ai_summary'), 'false', 'fast path skips the AI summary');
    assert.equal(component.customerDetailLoading(), true);

    detailCall.response.next({
      customer: { id: 'septona', name: 'Septona S.A.', countries: [], hubs: [], technologies: [] },
      ai_summary: null,
      opportunities: [],
      mail_drafts: [],
      impact_events: [],
      market_signals: [],
      data_gaps: [],
    });
    assert.equal(component.customerDetailLoading(), false, 'fiche renders before the summary');
    assert.equal(component.customerSummaryLoading(), true, 'summary fetch starts after the fiche');

    const summaryCall = getCalls.find(
      (call) => call.url === '/api/v1/client360/customers/septona/summary',
    );
    assert.ok(summaryCall, 'summary requested asynchronously');
    summaryCall.response.next({
      ai_summary: { text: 'Resume genere.', generation_mode: 'ai_assisted', highlights: [] },
    });
    assert.equal(component.customerSummaryLoading(), false);
    assert.equal(component.selectedCustomer()?.ai_summary?.text, 'Resume genere.');
  } finally {
    component.ngOnDestroy();
  }
});

test('Client360 fiche pages long lists client-side with show-more increments', () => {
  const harness = createHarness();
  const { component, getCalls } = harness;

  try {
    component.selectDirectoryCustomer({ customer_key: 'septona', customer_name: 'Septona S.A.' } as never);
    const detailCall = getCalls.find((call) => call.url === '/api/v1/client360/customers/septona');
    assert.ok(detailCall);
    detailCall.response.next({
      customer: { id: 'septona', name: 'Septona S.A.', countries: [], hubs: [], technologies: [] },
      ai_summary: null,
      opportunities: Array.from({ length: 130 }, (_, i) => ({ id: `opp-${i}` })),
      purchases: Array.from({ length: 40 }, (_, i) => ({ part_reference: `ref-${i}` })),
      timeline: Array.from({ length: 30 }, (_, i) => ({ at: `2026-01-${(i % 28) + 1}`, kind: 'impact', label: `e${i}` })),
      mail_drafts: [],
      impact_events: [],
      market_signals: [],
      data_gaps: [],
    });

    assert.equal(component.fichePurchases().length, 15, 'purchases capped at first page');
    assert.equal(component.ficheOpportunities().length, 24, 'opportunity chips capped at first page');
    assert.equal(component.ficheTimeline().length, 12, 'timeline capped at first page');

    component.showMoreFichePurchases();
    assert.equal(component.fichePurchases().length, 40, 'show-more reveals the remaining purchases');
    component.showMoreFicheOpportunities();
    assert.equal(component.ficheOpportunities().length, 124);

    component.selectDirectoryCustomer({ customer_key: 'mogul', customer_name: 'Mogul' } as never);
    assert.equal(component.fichePurchasesLimit(), 15, 'limits reset when switching customer');
    assert.equal(component.ficheOpportunitiesLimit(), 24);
  } finally {
    component.ngOnDestroy();
  }
});

test('Client360 pins syncFromCollection to A and cancels refresh on A -> B', () => {
  const harness = createHarness();
  const { component, workspace, postCalls, getCalls } = harness;

  try {
    component.syncFromCollection(false);
    assert.equal(postCalls[0].url, '/api/v1/client360/sources/sync-from-collection');
    assert.equal(workspaceHeader(postCalls[0]), 'andritz');
    assert.equal(component.syncBusy(), true);

    postCalls[0].response.next({
      collection_slug: 'andritz-client360-installed-base',
      dry_run: false,
      sources_upserted: 3,
      records_seen: 120,
    });
    assert.equal(component.syncBusy(), false);
    assert.equal(component.syncResult()?.sources_upserted, 3);
    assert.equal(getCalls[0]?.url, '/api/v1/client360/summary');
    assert.equal(workspaceHeader(getCalls[0]), 'andritz');

    workspace.switchWorkspace();
    assert.equal(component.syncResult(), null);
    assert.equal(component.syncBusy(), false);
    assert.ok(getCalls.every((call) => !call.response.observed));

    getCalls[0].response.next({ data_sources: [] });
    assert.equal(component.summary(), null);
  } finally {
    component.ngOnDestroy();
  }
});
