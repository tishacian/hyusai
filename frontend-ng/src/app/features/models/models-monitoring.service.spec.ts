import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Injector } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Subject } from 'rxjs';
import { ModelsService } from './models.service';

test('monitoring policy sends only the supported contract and waits for canonical state', async () => {
  const response = new Subject<unknown>(), requests: unknown[] = [];
  const injector = Injector.create({ providers: [ModelsService, { provide: HttpClient, useValue: {
    post: (url: string, body: unknown) => { requests.push({ url, body }); return response; },
  } }] });
  const service = injector.get(ModelsService);
  const result = service.configureMonitoringPolicy('model-version', { enabled: false, propose_retraining: true, interval_minutes: 360, system_id: 'forged' } as any);
  assert.deepEqual(requests, [{ url: '/api/v1/ml-models/model-version/monitoring/policy', body: { enabled: false, propose_retraining: true, interval_minutes: 360 } }]);
  const canonical = { config: { enabled: false, propose_retraining: true, interval_minutes: 360 }, can_configure: true };
  response.next({ monitoring: canonical }); response.complete();
  assert.equal(await result, canonical);
});

test('forbidden configuration propagates the server refusal', async () => {
  const response = new Subject<unknown>();
  const injector = Injector.create({ providers: [ModelsService, { provide: HttpClient, useValue: { post: () => response } }] });
  const result = injector.get(ModelsService).configureMonitoringPolicy('model-version', { enabled: true, propose_retraining: true, interval_minutes: 60 });
  const rejected = assert.rejects(result, (error: HttpErrorResponse) => error.status === 403);
  response.error(new HttpErrorResponse({ status: 403, error: { detail: { code: 'ML_MONITORING_FORBIDDEN' } } }));
  await rejected;
});
