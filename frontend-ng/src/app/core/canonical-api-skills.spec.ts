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
          get: (path: string) => {
            assert.equal(path, '/skills');
            return throwError(() => error);
          },
        },
      },
    ],
  });
  return injector.get(CanonicalApiService);
}

test('listSkills keeps the backwards-compatible empty fallback by default', async () => {
  const skills = await firstValueFrom(serviceFor(new Error('offline')).listSkills());
  assert.deepEqual(skills, []);
});

test('listSkills can propagate transport errors to truth-sensitive catalogs', async () => {
  const error = new Error('catalog offline');
  await assert.rejects(
    firstValueFrom(serviceFor(error).listSkills({ propagateErrors: true })),
    error,
  );
});
