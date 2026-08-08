import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { Subject, of } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import {
  CanonicalApiService,
  type Capability,
  type Skill,
} from '@app/core/canonical-api.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { FlowCatalogService, projectSkillCatalog } from './flow-catalog.service';

class WorkspaceStub {
  private epoch = 1;

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({
      workspaceSlug: 'workspace-a',
      workspaceId: 'workspace-a',
      epoch: this.epoch,
    });
  }

  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean {
    return scope.epoch === this.epoch;
  }

  registerContextReset(_resetter: (transition: WorkspaceContextTransition) => void): () => void {
    return () => undefined;
  }

  contextEpoch(): number {
    return this.epoch;
  }
}

class ApiStub {
  readonly calls: Array<{ path: string; params?: Record<string, string> }> = [];
  readonly responses: Array<Subject<unknown>> = [];

  get(path: string, params?: Record<string, string>) {
    this.calls.push({ path, params });
    const response = new Subject<unknown>();
    this.responses.push(response);
    return response.asObservable();
  }
}

class CanonicalStub {
  constructor(private readonly capabilities: Capability[] = []) {}

  listCapabilities() {
    return of(this.capabilities);
  }
}

function makeService(capabilities: Capability[] = []): {
  service: FlowCatalogService;
  api: ApiStub;
} {
  const api = new ApiStub();
  const injector = Injector.create({
    providers: [
      FlowCatalogService,
      { provide: ApiService, useValue: api },
      { provide: CanonicalApiService, useValue: new CanonicalStub(capabilities) },
      { provide: WorkspaceService, useValue: new WorkspaceStub() },
    ],
  });
  return { service: injector.get(FlowCatalogService), api };
}

test('catalog projection is stable and carries usage plus carriers', () => {
  const projected = projectSkillCatalog([
    {
      id: 'z',
      slug: 'semantic_search_v1',
      name: 'Zulu',
      category: 'Retrieval',
      runtime_status: 'bound',
      metrics: { calls: 4 },
      visibility: { visible: true, reason: 'capability', capabilities: ['ticket_triage'] },
    } as Skill,
    {
      id: 'a',
      slug: 'document_ingestion_v1',
      name: 'Alpha',
      category: 'Ingestion',
      runtime_status: 'stub',
    },
  ]);
  assert.deepEqual(projected.map((item) => item.label), ['Alpha', 'Zulu']);
  assert.deepEqual(projected.map((item) => item.skillCategory), ['Ingestion', 'Retrieval']);
  assert.deepEqual(projected.map((item) => item.usageCalls), [0, 4]);
  assert.deepEqual(projected[1].capabilitySlugs, ['ticket_triage']);
  assert.equal(projected[1].unavailableReason, undefined);
});

test('the excluded rows are kept apart from what a Flow may drop', () => {
  const { service, api } = makeService([
    { id: 'cap-1', slug: 'ticket_triage', name: 'Ticket triage', description: 'Route tickets' },
  ]);
  assert.deepEqual(api.calls, [{ path: '/skills', params: { include_filtered: 'true' } }]);

  api.responses[0].next({
    skills: [
      {
        id: 'v',
        slug: 'answer_v1',
        name: 'Answer',
        category: 'LLM',
        visibility: { visible: true, reason: 'capability', capabilities: ['ticket_triage'] },
      },
      {
        id: 'f',
        slug: 'invoice_extract_v1',
        name: 'Invoice extract',
        category: 'Ingestion',
        visibility: {
          visible: false,
          reason: 'industry_not_allowed',
          capabilities: [],
          key: 'government',
        },
      },
    ],
    catalog: {
      total: 85,
      visible: 28,
      filtered: 57,
      policy: { allowed_industries_source: 'inferred' },
    },
  });

  assert.equal(service.state(), 'loaded');
  assert.deepEqual(service.skillItems().map((item) => item.label), ['Answer']);
  assert.deepEqual(
    service.filteredItems().map((item) => [item.unavailableReason, item.unavailableKey]),
    [['industry_not_allowed', 'government']],
  );
  assert.deepEqual(service.summary(), {
    total: 85,
    visible: 28,
    filtered: 57,
    industriesConfigured: false,
  });
  assert.deepEqual(service.capabilities(), [
    { slug: 'ticket_triage', name: 'Ticket triage', description: 'Route tickets' },
  ]);
});

test('loaded-empty and load-error are distinct, and Retry starts a fresh request', () => {
  const { service, api } = makeService();
  assert.equal(service.state(), 'loading');

  api.responses[0].next({ skills: [], catalog: { total: 0, visible: 0, filtered: 0 } });
  assert.equal(service.state(), 'loaded');
  assert.deepEqual(service.skillItems(), []);

  service.retry();
  assert.equal(service.state(), 'loading');
  assert.equal(api.calls.length, 2);
  api.responses[1].error(new Error('catalog unavailable'));
  assert.equal(service.state(), 'error');
  assert.deepEqual(service.skillItems(), []);
  assert.deepEqual(service.filteredItems(), []);

  service.retry();
  api.responses[2].next({
    skills: [{ id: 'skill-1', slug: 'calendar_read_v1', name: 'Calendar Read', category: 'Connections' }],
  });
  assert.equal(service.state(), 'loaded');
  assert.equal(service.skillItems()[0]?.skillCategory, 'Connections');
  // An older backend serving no `catalog` block still yields a usable summary.
  assert.deepEqual(service.summary(), {
    total: 1,
    visible: 1,
    filtered: 0,
    industriesConfigured: false,
  });
});
