import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { Subject } from 'rxjs';
import { CanonicalApiService, type Skill } from '@app/core/canonical-api.service';
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

class CanonicalStub {
  readonly requests: Array<Subject<Skill[]>> = [];
  readonly options: Array<{ propagateErrors?: boolean } | undefined> = [];

  listSkills(options?: { propagateErrors?: boolean }) {
    const request = new Subject<Skill[]>();
    this.requests.push(request);
    this.options.push(options);
    return request.asObservable();
  }
}

function makeService(): { service: FlowCatalogService; canonical: CanonicalStub } {
  const canonical = new CanonicalStub();
  const injector = Injector.create({
    providers: [
      FlowCatalogService,
      { provide: CanonicalApiService, useValue: canonical },
      { provide: WorkspaceService, useValue: new WorkspaceStub() },
    ],
  });
  return { service: injector.get(FlowCatalogService), canonical };
}

test('catalog projection is stable and enriches every entry', () => {
  const projected = projectSkillCatalog([
    { id: 'z', slug: 'semantic_search_v1', name: 'Zulu', runtime_status: 'bound' },
    { id: 'a', slug: 'document_ingestion_v1', name: 'Alpha', runtime_status: 'stub' },
  ]);
  assert.deepEqual(projected.map((item) => item.label), ['Alpha', 'Zulu']);
  assert.deepEqual(projected.map((item) => item.skillCategory), ['Ingestion', 'Retrieval']);
  assert.deepEqual(projected.map((item) => item.runtimeStatus), ['stub', 'bound']);
});

test('loaded-empty and load-error are distinct, and Retry starts a fresh request', () => {
  const { service, canonical } = makeService();
  assert.equal(service.state(), 'loading');
  assert.equal(canonical.requests.length, 1);
  assert.deepEqual(canonical.options, [{ propagateErrors: true }]);

  canonical.requests[0].next([]);
  canonical.requests[0].complete();
  assert.equal(service.state(), 'loaded');
  assert.deepEqual(service.skillItems(), []);

  service.retry();
  assert.equal(service.state(), 'loading');
  assert.equal(canonical.requests.length, 2);
  assert.deepEqual(canonical.options[1], { propagateErrors: true });
  canonical.requests[1].error(new Error('catalog unavailable'));
  assert.equal(service.state(), 'error');
  assert.deepEqual(service.skillItems(), []);

  service.retry();
  assert.equal(canonical.requests.length, 3);
  canonical.requests[2].next([
    { id: 'skill-1', slug: 'calendar_read_v1', name: 'Calendar Read' },
  ]);
  canonical.requests[2].complete();
  assert.equal(service.state(), 'loaded');
  assert.equal(service.skillItems()[0]?.skillCategory, 'Connections');
});
