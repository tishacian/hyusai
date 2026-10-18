import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { computed, Injector, signal } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Subject } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import { ModelImportComponent } from './model-import.component';
import { ModelImportService } from './model-import.service';
import { canSubmit, importPhase, type ImportForm, type ImportJob, type ImportRefusal } from './model-import.vm';

function harness(allowed = true) {
  const calls: unknown[] = [], emitted: string[] = [];
  let finish!: (value: unknown) => void, fail!: (error: unknown) => void;
  const form = signal<ImportForm>({
    archive: new Blob(['zip']) as File, validation: new Blob(['{}']) as File,
    task: 'classification', name: 'Churn', target: 'churn', lineageModelId: null,
  });
  const busy = signal(false), canImport = signal(allowed);
  const job = signal<ImportJob | null>(null), refusal = signal<ImportRefusal | null>(null);
  const component = Object.assign(Object.create(ModelImportComponent.prototype), {
    canImport, form, busy, job, refusal, generation: 0, timer: null, polls: 0,
    ready: computed(() => canSubmit(form(), canImport(), busy())),
    imported: { emit: (id: string) => emitted.push(id) }, closed: { emit: () => emitted.push('closed') },
    api: {
      submit: (value: ImportForm) => { calls.push(['submit', value.name]); return new Promise((done, reject) => { finish = done; fail = reject; }); },
      status: (id: string) => { calls.push(['status', id]); return new Promise(done => { finish = done; }); },
    },
  }) as any;
  return { component, calls, emitted, finish: (value: unknown) => finish(value), fail: (error: unknown) => fail(error) };
}

test('no upload leaves the dialog without the M1 import capability', async () => {
  const h = harness(false);
  await h.component.submit();
  assert.deepEqual(h.calls, []);
});

test('an import is submitted once, polled while validating, and announced when accepted', async () => {
  const h = harness();
  const first = h.component.submit(); await h.component.submit();
  assert.deepEqual(h.calls, [['submit', 'Churn']]);
  h.finish({ job: { id: 'j1', status: 'queued', error: null, updated_at: null, result: {} } });
  await first;
  assert.equal(importPhase(h.component.job()), 'pending');
  assert.notEqual(h.component.timer, null);
  const generation = h.component.generation;
  const polled = h.component.poll(generation, 'j1');
  h.finish({ job: { id: 'j1', status: 'completed', error: null, updated_at: null, result: { verdict: 'accepted', model_id: 'm9' } } });
  await polled;
  assert.equal(importPhase(h.component.job()), 'accepted');
  assert.deepEqual(h.emitted, ['m9']);
  assert.equal(h.component.timer, null);
});

test('a synchronous refusal keeps its reason and leaves the form usable', async () => {
  const h = harness();
  const pending = h.component.submit();
  h.fail(new HttpErrorResponse({ status: 422, error: { detail: { code: 'ML_IMPORT_REJECTED', reason: 'pickle_serialization', message: 'raw' } } }));
  await pending;
  assert.equal(h.component.refusal().reason, 'pickle_serialization');
  assert.equal(h.component.busy(), false);
  h.component.retry();
  assert.equal(h.component.refusal(), null);
});

test('a reply that arrives after the dialog closed is dropped', async () => {
  const h = harness();
  const pending = h.component.submit();
  h.component.dismiss();
  h.finish({ job: { id: 'j1', status: 'queued', error: null, updated_at: null, result: {} } });
  await pending;
  assert.equal(h.component.job(), null);
  assert.deepEqual(h.emitted, ['closed']);
});

test('the service posts multipart fields and drops a reply from another workspace', async () => {
  let current = true;
  const reply = new Subject<unknown>(), requests: { url: string; body?: FormData }[] = [];
  const injector = Injector.create({ providers: [ModelImportService,
    { provide: WorkspaceService, useValue: { captureRequestScope: () => 'ws', isRequestScopeCurrent: () => current } },
    { provide: HttpClient, useValue: {
      post: (url: string, body: FormData) => { requests.push({ url, body }); return reply; },
      get: (url: string) => { requests.push({ url }); return reply; },
    } },
  ] });
  const service = injector.get(ModelImportService);
  const sent = service.submit({
    archive: new File(['zip'], 'model.zip'), validation: new File(['{}'], 'validation.json'),
    task: 'regression', name: ' Price ', target: 'price', lineageModelId: 'm1',
  });
  reply.next({ job: { id: 'j1' } });
  assert.deepEqual(await sent, { job: { id: 'j1' } });
  const body = requests[0].body!;
  assert.equal(requests[0].url, '/api/v1/ml-models/import');
  assert.deepEqual([body.get('task'), body.get('name'), body.get('target'), body.get('lineage_model_id')], ['regression', 'Price', 'price', 'm1']);
  assert.equal((body.get('archive') as File).name, 'model.zip');
  const status = service.status('a/b');
  current = false; reply.next({ job: { id: 'old' } });
  assert.equal(await status, null);
  assert.equal(requests[1].url, '/api/v1/ml-models/import/a%2Fb');
  reply.complete();
});
