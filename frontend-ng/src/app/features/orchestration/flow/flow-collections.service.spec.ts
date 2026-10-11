import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { Subject } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { FlowCollectionsService } from './flow-collections.service';

interface RequestRecord {
  path: string;
  response: Subject<unknown>;
}

class ApiStub {
  readonly requests: RequestRecord[] = [];

  get<T>(path: string) {
    const response = new Subject<T>();
    this.requests.push({ path, response: response as Subject<unknown> });
    return response.asObservable();
  }
}

class WorkspaceStub {
  private epoch = 1;
  private resetter: ((transition: WorkspaceContextTransition) => void) | null = null;

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({
      workspaceSlug: `workspace-${this.epoch}`,
      workspaceId: `workspace-${this.epoch}`,
      epoch: this.epoch,
    });
  }

  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean {
    return scope.epoch === this.epoch;
  }

  registerContextReset(resetter: (transition: WorkspaceContextTransition) => void): () => void {
    this.resetter = resetter;
    return () => { this.resetter = null; };
  }

  contextEpoch(): number {
    return this.epoch;
  }

  transition(): void {
    const previousEpoch = this.epoch;
    this.epoch += 1;
    this.resetter?.({
      previousSlug: `workspace-${previousEpoch}`,
      nextSlug: `workspace-${this.epoch}`,
      previousEpoch,
      nextEpoch: this.epoch,
    });
  }
}

function makeService(): {
  service: FlowCollectionsService;
  api: ApiStub;
  workspace: WorkspaceStub;
} {
  const api = new ApiStub();
  const workspace = new WorkspaceStub();
  const injector = Injector.create({
    providers: [
      FlowCollectionsService,
      { provide: ApiService, useValue: api },
      { provide: WorkspaceService, useValue: workspace },
    ],
  });
  return { service: injector.get(FlowCollectionsService), api, workspace };
}

test('collection catalogue loads once, merges both payload shapes and sorts unique slugs', () => {
  const { service, api } = makeService();
  assert.equal(service.state(), 'idle');

  service.ensureLoaded();
  service.ensureLoaded();
  assert.equal(api.requests.length, 1);
  assert.equal(api.requests[0].path, '/documents/collections');
  assert.equal(service.state(), 'loading');

  api.requests[0].response.next({
    collections: ['zeta', 'alpha', 'zeta'],
    items: [{ slug: 'beta' }, { name: 'alpha' }, {}, { slug: '' }],
  });
  api.requests[0].response.complete();

  assert.equal(service.state(), 'loaded');
  assert.deepEqual(service.collections(), ['alpha', 'beta', 'zeta']);
});

test('document catalogue is URL-scoped, paginated, deduplicated and sorted', () => {
  const { service, api } = makeService();
  service.ensureDocumentsLoaded(' secure deposit ');
  service.ensureDocumentsLoaded('secure deposit');

  assert.equal(api.requests.length, 1, 'a loading collection is not requested twice');
  assert.equal(
    api.requests[0].path,
    '/documents/list?collection_name=secure%20deposit&limit=1000&offset=0',
  );
  assert.equal(service.documentStates()['secure deposit'], 'loading');

  api.requests[0].response.next({
    documents: [
      { document_id: 'doc-z', filename: 'Zulu.pdf', status: 'ready' },
      { document_id: 'doc-a', filename: 'Alpha.pdf', status: null },
      { document_id: 'doc-z', filename: 'Duplicate.pdf', status: 'failed' },
      { document_id: '', filename: 'Ignored.pdf' },
    ],
    total: 1204,
    has_more: true,
  });
  api.requests[0].response.complete();

  assert.deepEqual(service.documentsFor('secure deposit'), [
    { id: 'doc-a', filename: 'Alpha.pdf', status: null },
    { id: 'doc-z', filename: 'Zulu.pdf', status: 'ready' },
  ]);
  assert.equal(service.documentTotals()['secure deposit'], 1204);
  assert.equal(service.documentHasMore()['secure deposit'], true);
  assert.equal(service.documentStates()['secure deposit'], 'loaded');

  service.ensureDocumentsLoaded('secure deposit');
  assert.equal(api.requests.length, 1, 'a loaded catalogue remains cached');

  service.loadMoreDocuments('secure deposit');
  assert.equal(api.requests.length, 2);
  assert.equal(
    api.requests[1].path,
    '/documents/list?collection_name=secure%20deposit&limit=1000&offset=4',
  );
  api.requests[1].response.next({
    documents: [
      { document_id: 'doc-b', filename: 'Bravo.pdf', status: 'ready' },
      { document_id: 'doc-a', filename: 'Alpha duplicate.pdf', status: 'failed' },
    ],
    total: 1204,
    has_more: false,
  });
  api.requests[1].response.complete();

  assert.deepEqual(service.documentsFor('secure deposit'), [
    { id: 'doc-a', filename: 'Alpha.pdf', status: null },
    { id: 'doc-b', filename: 'Bravo.pdf', status: 'ready' },
    { id: 'doc-z', filename: 'Zulu.pdf', status: 'ready' },
  ]);
  assert.equal(service.documentHasMore()['secure deposit'], false);
});

test('document error is explicit and force retry starts a fresh request', () => {
  const { service, api } = makeService();
  service.ensureDocumentsLoaded('legal');
  api.requests[0].response.error(new Error('offline'));

  assert.equal(service.documentStates()['legal'], 'error');
  assert.deepEqual(service.documentsFor('legal'), []);

  service.ensureDocumentsLoaded('legal', true);
  assert.equal(api.requests.length, 2);
  assert.equal(service.documentStates()['legal'], 'loading');
  api.requests[1].response.next({ documents: [], total: 0 });
  api.requests[1].response.complete();
  assert.equal(service.documentStates()['legal'], 'loaded');
});

test('workspace transition clears both catalogues and ignores late document responses', async () => {
  const { service, api, workspace } = makeService();
  service.ensureLoaded();
  service.ensureDocumentsLoaded('private-a');
  workspace.transition();

  assert.deepEqual(service.collections(), []);
  assert.deepEqual(service.documents(), {});
  assert.deepEqual(service.documentStates(), {});
  assert.deepEqual(service.documentHasMore(), {});

  api.requests[1].response.next({
    documents: [{ document_id: 'leak-a', filename: 'A.pdf' }],
    total: 1,
  });
  api.requests[1].response.complete();
  assert.deepEqual(service.documents(), {}, 'late workspace-A data is discarded');

  await new Promise<void>((resolve) => queueMicrotask(resolve));
  assert.equal(api.requests.length, 3, 'the previously started collection catalogue reloads for B');
  assert.equal(api.requests[2].path, '/documents/collections');
});
