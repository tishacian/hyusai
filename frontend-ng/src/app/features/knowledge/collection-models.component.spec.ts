import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { of } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { CollectionModelsComponent } from './collection-models.component';

function harness(canWrite = true) {
  const calls: { path: string; body: any }[] = [];
  const current = { id: 'collection', slug: 'knowledge', permissions: { can_write: canWrite }, embedding_artifact_id: 'old-model', active_generation: 'old-index', chunk_count: 100 };
  const injector = Injector.create({ providers: [CollectionModelsComponent,
    { provide: I18nService, useValue: { t: (key: string) => key } },
    { provide: WorkspaceService, useValue: { captureRequestScope: () => ({ workspaceSlug: 'acme', epoch: 1 }), isRequestScopeCurrent: () => true, registerContextReset: () => () => undefined } },
    { provide: ApiService, useValue: {
      get: (path: string) => of(path === '/documents/collections' ? { items: [current] } : path === '/huggingface/artifacts' ? { artifacts: [] } : { items: [] }),
      post: (path: string, body: unknown) => { calls.push({ path, body }); return of({ job: { id: 'reindex', status: 'queued' }, pending_generation: 'new-index' }); },
    } },
  ] });
  const component = injector.get(CollectionModelsComponent); component.collectionId = 'knowledge';
  return { component, calls };
}

test('reindex requires confirmation and preserves the active model/index while queued', async () => {
  const h = harness(); await h.component.load(); h.component.embeddingId = 'new-model';
  await h.component.reindex(); assert.equal(h.calls.length, 0);
  h.component.confirmed = true; await h.component.reindex();
  assert.equal(h.calls[0].path, '/documents/collections/collection/embedding/reindex');
  assert.deepEqual(h.calls[0].body, { artifact_id: 'new-model', normalize_embeddings: true, batch_size: 32 });
  assert.equal(h.component.collection()?.embedding_artifact_id, 'old-model');
  assert.equal(h.component.collection()?.active_generation, 'old-index');
  assert.equal(h.component.collection()?.pending_generation, 'new-index'); h.component.ngOnDestroy();
});

test('read-only collection users cannot reindex or activate a reranker', async () => {
  const h = harness(false); await h.component.load(); h.component.embeddingId = 'new-model'; h.component.confirmed = true;
  await h.component.reindex(); await h.component.setReranker(); assert.equal(h.calls.length, 0); h.component.ngOnDestroy();
});
