import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Injector } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Subject } from 'rxjs';
import { ModelsService } from './models.service';

test('shadow configuration sends only the supported contract and waits for canonical state', async () => {
  const response = new Subject<unknown>(), requests: unknown[] = [];
  const injector = Injector.create({ providers: [ModelsService, { provide: HttpClient, useValue: {
    post: (url: string, body: unknown) => { requests.push({ url, body }); return response; },
  } }] });
  const service = injector.get(ModelsService);
  const result = service.configureShadow('model-version', { enabled: false, sample_percent: 25, timeout_s: 30, challenger_id: 'forged' } as any);
  assert.deepEqual(requests, [{ url: '/api/v1/ml-models/model-version/shadow', body: { enabled: false, sample_percent: 25, timeout_s: 30 } }]);
  const canonical = { config: { enabled: false, sample_percent: 25, timeout_s: 30 }, can_configure: true };
  response.next({ shadow: canonical }); response.complete();
  assert.equal(await result, canonical);
});

test('forbidden configuration propagates the server refusal', async () => {
  const response = new Subject<unknown>();
  const injector = Injector.create({ providers: [ModelsService, { provide: HttpClient, useValue: { post: () => response } }] });
  const result = injector.get(ModelsService).configureShadow('model-version', { enabled: true, sample_percent: 10, timeout_s: 15 });
  const rejected = assert.rejects(result, (error: HttpErrorResponse) => error.status === 403);
  response.error(new HttpErrorResponse({ status: 403, error: { detail: { code: 'ML_SHADOW_FORBIDDEN' } } }));
  await rejected;
});
