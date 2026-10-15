import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Injector } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Subject } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import { ModelExportService } from './model-export.service';

function setup() {
  const response = new Subject<Blob>(), requests: unknown[] = [];
  let current = true;
  const injector = Injector.create({ providers: [ModelExportService,
    { provide: WorkspaceService, useValue: { captureRequestScope: () => 'captured', isRequestScopeCurrent: () => current } },
    { provide: HttpClient, useValue: { get: (url: string, options: unknown) => { requests.push({url, options}); return response; } } },
  ] });
  return { service: injector.get(ModelExportService), response, requests, revoke: () => { current = false; } };
}
test('export downloads the exact version through authenticated HttpClient as a blob', async () => {
  const s = setup(), blob = new Blob(['archive']);
  const pending = s.service.download('version/with reserved');
  assert.deepEqual(s.requests, [{url:'/api/v1/ml-models/version%2Fwith%20reserved/export', options:{responseType:'blob'}}]);
  s.response.next(blob); s.response.complete();
  assert.equal(await pending, blob);
});
test('export drops archive bytes after workspace or principal scope changes', async () => {
  const s = setup(), pending = s.service.download('version');
  s.revoke(); s.response.next(new Blob(['old workspace'])); s.response.complete();
  assert.equal(await pending, null);
});
test('export preserves an HTTP refusal instead of manufacturing an archive', async () => {
  const s = setup(), pending = s.service.download('version');
  const error = Object.assign(new Error('forbidden'), {status:403});
  const rejection = assert.rejects(pending, value => value === error);
  s.response.error(error);
  await rejection;
});
