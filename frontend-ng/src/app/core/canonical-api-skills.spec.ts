import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { firstValueFrom, of, throwError } from 'rxjs';
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

function systemsServiceFor(error: Error): CanonicalApiService {
  const injector = Injector.create({
    providers: [
      CanonicalApiService,
      {
        provide: ApiService,
        useValue: {
          get: (path: string) => {
            assert.equal(path, '/systems');
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

test('listSystems preserves fallback compatibility but can fail closed for Studio', async () => {
  assert.deepEqual(
    await firstValueFrom(systemsServiceFor(new Error('offline')).listSystems()),
    [],
  );
  const error = new Error('systems unavailable');
  await assert.rejects(
    firstValueFrom(systemsServiceFor(error).listSystems({ propagateErrors: true })),
    error,
  );
});

test('the shared model catalogue propagates failures and resolves with the explicit System context', async () => {
  const calls: Array<[string, unknown]> = [];
  const offline = new Error('catalogue unavailable');
  const api = Injector.create({ providers: [CanonicalApiService, {
    provide: ApiService, useValue: { get: (path: string, params?: unknown) => {
      calls.push([path, params]);
      return path === '/models' ? throwError(() => offline) : of({ provider: 'openai', model: 'gpt-example' });
    } },
  }] }).get(CanonicalApiService);
  await assert.rejects(firstValueFrom(api.listModelCatalog()), offline);
  await firstValueFrom(api.resolveModel('openai', 'gpt-example', 'system-a'));
  assert.deepEqual(calls[1], ['/models/resolve', { provider: 'openai', model: 'gpt-example', system_id: 'system-a' }]);
});
