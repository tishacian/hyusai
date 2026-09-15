import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { firstValueFrom, of, throwError } from 'rxjs';
import { ApiService } from './api.service';
import { CanonicalApiService, type SystemOverview } from './canonical-api.service';

const payload: SystemOverview = {
  window: '30d',
  since: '2026-08-16T00:00:00',
  generated_at: '2026-09-15T00:00:00',
  system: { id: 'system-a', name: 'System A', objective: 'Answer', status: 'active' },
  readiness: {
    state: 'ready',
    label: 'Ready to run',
    can_run: true,
    blockers: [],
    primary_action: { label: 'Run System', href: '/systems/system-a/run' },
  },
  publication: {
    state: 'published',
    version_id: 'version-a',
    version_number: 2,
    published_at: '2026-09-14T00:00:00',
    flow_sha256: 'abc',
  },
  runs: {
    total: 1,
    completed: 1,
    failed: 0,
    active: 0,
    success_rate: 100,
    avg_latency_ms: 42,
    latest: null,
  },
  quality: {
    state: 'not_measured',
    score: null,
    hallucination_rate: null,
    measured_at: null,
    sample_count: 0,
  },
};

test('System Overview uses the canonical scoped endpoint and keeps errors visible', async () => {
  const calls: Array<{ path: string; params?: Record<string, unknown> }> = [];
  const service = Injector.create({
    providers: [
      CanonicalApiService,
      {
        provide: ApiService,
        useValue: {
          get: (path: string, params?: Record<string, unknown>) => {
            calls.push({ path, params });
            return of(payload);
          },
        },
      },
    ],
  }).get(CanonicalApiService);

  assert.equal((await firstValueFrom(service.getSystemOverview('system/a', '7d'))).system.id, 'system-a');
  assert.deepEqual(calls, [{ path: '/systems/system%2Fa/overview', params: { window: '7d' } }]);

  const error = new Error('overview offline');
  const failing = Injector.create({
    providers: [
      CanonicalApiService,
      { provide: ApiService, useValue: { get: () => throwError(() => error) } },
    ],
  }).get(CanonicalApiService);
  await assert.rejects(firstValueFrom(failing.getSystemOverview('system-a')), error);
});
