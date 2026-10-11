import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { firstValueFrom, throwError } from 'rxjs';
import { ApiService } from './api.service';
import { CanonicalApiService } from './canonical-api.service';

function serviceFor(error: Error): CanonicalApiService {
  const injector = Injector.create({
    providers: [
      CanonicalApiService,
      {
        provide: ApiService,
        useValue: {
          get: () => throwError(() => error),
        },
      },
    ],
  });
  return injector.get(CanonicalApiService);
}

test('version history keeps backwards-compatible empty/null fallbacks by default', async () => {
  const service = serviceFor(new Error('offline'));
  assert.deepEqual(await firstValueFrom(service.listSystemVersions('system-a')), {
    total: 0,
    limit: 0,
    offset: 0,
    versions: [],
  });
  assert.equal(await firstValueFrom(service.getSystemVersion('system-a', 2)), null);
});

test('truth-sensitive version history can propagate list and preview failures', async () => {
  const error = new Error('history unavailable');
  const service = serviceFor(error);
  await assert.rejects(
    firstValueFrom(service.listSystemVersions('system-a', { propagateErrors: true })),
    error,
  );
  await assert.rejects(
    firstValueFrom(service.getSystemVersion('system-a', 2, { propagateErrors: true })),
    error,
  );
});
