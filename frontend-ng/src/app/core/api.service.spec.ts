import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { HttpClient } from '@angular/common/http';
import { Injector, runInInjectionContext } from '@angular/core';
import { firstValueFrom, of } from 'rxjs';
import { ApiService } from './api.service';

test('POST composes an explicit workspace with an idempotency header', async () => {
  const calls: Array<{
    url: string;
    body: unknown;
    options: { headers?: Record<string, string> };
  }> = [];
  const injector = Injector.create({
    providers: [
      ApiService,
      {
        provide: HttpClient,
        useValue: {
          post: (url: string, body: unknown, options: { headers?: Record<string, string> }) => {
            calls.push({ url, body, options });
            return of({ ok: true });
          },
        },
      },
    ],
  });
  const service = runInInjectionContext(injector, () => injector.get(ApiService));

  await firstValueFrom(service.post(
    '/systems/system-a/value-loop/scenarios',
    { source_run_id: 'run-a' },
    {
      workspaceSlug: 'showcase',
      headers: { 'Idempotency-Key': 'value-loop-ui:system-a:create:nonce' },
    },
  ));

  assert.deepEqual(calls, [{
    url: '/api/v1/systems/system-a/value-loop/scenarios',
    body: { source_run_id: 'run-a' },
    options: {
      headers: {
        'X-Workspace-Slug': 'showcase',
        'Idempotency-Key': 'value-loop-ui:system-a:create:nonce',
      },
    },
  }]);
});
