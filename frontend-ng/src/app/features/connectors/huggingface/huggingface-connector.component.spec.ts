import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { Subject, of } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { HuggingfaceConnectorComponent } from './huggingface-connector.component';
import type { HubConfig, HubRepository } from './huggingface.models';

const settings: HubConfig = { connection: { endpoint: 'https://huggingface.co', source: 'workspace', token_set: true }, policy: {}, limits: {}, can_configure: true, can_import_models: true, can_import_datasets: true, can_admin_platform: false };
const repository: HubRepository = { metadata: { hub_endpoint: settings.connection.endpoint, kind: 'model', repo_id: 'a/b', revision: 'a'.repeat(40), requested_ref: 'main', license: 'mit', gated: false, private: false, files: [{ path: 'model.safetensors', size_bytes: 123 }] }, license: { license: 'mit', license_class: 'allowed', accepted: false }, license_text: 'MIT' };
function harness() {
  let epoch = 1;
  let slug = 'a';
  let resetter: ((transition: { nextEpoch: number }) => void) | undefined;
  const calls: { method: string; path: string; body?: any; scope?: any }[] = [];
  const replies = new Map<string, unknown>([['GET /huggingface/config', settings], ['GET /huggingface/artifacts', { artifacts: [] }], ['GET /huggingface/jobs', { jobs: [] }]]);
  const answer = (method: string, path: string, body?: unknown, scope?: unknown) => {
    calls.push({ method, path, body, scope });
    const value = replies.get(`${method} ${path}`);
    return value instanceof Subject ? value : of(value ?? {});
  };
  const injector = Injector.create({ providers: [
    HuggingfaceConnectorComponent,
    { provide: ApiService, useValue: { get: (p: string, params: unknown, scope: unknown) => answer('GET', p, params, scope), post: (p: string, body: unknown, scope: unknown) => answer('POST', p, body, scope), put: (p: string, body: unknown, scope: unknown) => answer('PUT', p, body, scope) } },
    { provide: I18nService, useValue: { t: (key: string) => key, locale: () => 'en' } },
    { provide: WorkspaceService, useValue: { captureRequestScope: () => ({ workspaceSlug: slug, workspaceId: slug, epoch }), isRequestScopeCurrent: (scope: { epoch: number }) => scope.epoch === epoch, contextEpoch: () => epoch, registerContextReset: (fn: typeof resetter) => { resetter = fn; return () => undefined; } } },
  ] });
  const component = injector.get(HuggingfaceConnectorComponent);
  component.config.set(settings);
  return { component, calls, replies, switchWorkspace: () => { resetter?.({ nextEpoch: epoch + 1 }); epoch++; slug = 'b'; } };
}

test('imports resolved SHA and exact files, never edited branch input', async () => {
  const h = harness(); h.component.repository.set(repository); h.component.chooseFormat('safetensors'); h.component.revision = 'changed-main';
  h.replies.set('POST /huggingface/imports', { artifact: { artifact_id: 'artifact' }, job: { id: 'job', status: 'completed' } });
  await h.component.importSelection();
  const call = h.calls.find(c => c.method === 'POST')!;
  assert.equal(call.body.revision, repository.metadata.revision);
  assert.deepEqual(call.body.files, ['model.safetensors']);
  assert.equal(call.scope.workspaceSlug, 'a');
  h.component.ngOnDestroy();
});

test('blocked or unaccepted license and reader role cannot submit imports', async () => {
  const h = harness(); h.component.repository.set({ ...repository, license: { ...repository.license, license_class: 'acceptance_required' } }); h.component.chooseFormat('safetensors');
  await h.component.importSelection(); assert.equal(h.calls.length, 0);
  h.component.repository.set(repository); h.component.config.set({ ...settings, can_import_models: false });
  await h.component.importSelection(); assert.equal(h.calls.length, 0);
  h.component.ngOnDestroy();
});

test('workspace switch clears secrets and rejects a stale repository response', async () => {
  const h = harness(); const pending = new Subject<HubRepository>(); h.replies.set('GET /huggingface/repository', pending);
  const action = h.component.inspect('a/private', 'main'); h.component.token = 'hf_secret';
  h.switchWorkspace(); pending.next(repository); pending.complete(); await action;
  assert.equal(h.component.token, ''); assert.equal(h.component.repository(), null); assert.deepEqual(h.component.selectedFiles(), []);
  h.component.ngOnDestroy();
});

test('saving a connection sends the token once and clears it immediately', async () => {
  const h = harness(); h.component.token = 'hf_secret'; const pending = new Subject(); h.replies.set('PUT /huggingface/config', pending);
  const action = h.component.saveConnection(); assert.equal(h.component.token, '');
  assert.deepEqual(h.calls[0].body.values, { endpoint: 'https://huggingface.co', token: 'hf_secret' });
  pending.next({}); pending.complete(); await action;
  h.component.ngOnDestroy();
});

test('dataset imports preserve projection order and row cap; a blank projection means all columns', async () => {
  const h = harness();
  h.component.repository.set({ ...repository, metadata: { ...repository.metadata, kind: 'dataset', files: [{ path: 'train.parquet', size_bytes: 12 }] } });
  h.component.chooseFormat('parquet'); h.component.selectedFiles.set(['train.parquet']); h.component.columns = ' label, feature '; h.component.maxRows = 25;
  h.replies.set('POST /huggingface/imports', { artifact: { artifact_id: 'dataset' }, job: { id: 'job', status: 'completed' } });
  await h.component.importSelection();
  const first = h.calls.find(c => c.method === 'POST')!;
  assert.deepEqual(first.body.columns, ['label', 'feature']); assert.equal(first.body.max_rows, 25);
  h.component.columns = ''; await h.component.importSelection();
  assert.equal('columns' in h.calls.filter(c => c.method === 'POST')[1].body, false);
  h.component.ngOnDestroy();
});
