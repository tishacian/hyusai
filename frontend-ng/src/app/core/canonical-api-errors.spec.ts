import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { firstValueFrom, throwError, type Observable } from 'rxjs';
import { ApiService } from './api.service';
import { CanonicalApiService } from './canonical-api.service';

const migratedCalls: Array<[string, (api: CanonicalApiService) => Observable<unknown>]> = [
  ['control policies', api => api.controlPolicies()],
  ['adaptive policies', api => api.adaptivePolicies()],
  ['create system', api => api.createSystem({ name: 'Review' })],
  ['update system', api => api.updateSystem('system-a', { name: 'Review' })],
  ['create context', api => api.createContext({ name: 'Evidence' })],
  ['update context', api => api.updateContext('context-a', { name: 'Evidence' })],
  ['rollback system version', api => api.rollbackSystemVersion('system-a', 2)],
  ['persist context', api => api.persistContext('context-a')],
  ['impact simulation', api => api.hypervisorWhatIf({ scope: 'workspace', levers: {} })],
  ['delete context', api => api.deleteContext('context-a')],
  ['rerun', api => api.rerunRun('run-a')],
  ['human decision', api => api.resolveRunHitl('run-a', { action: 'accept', expected_decision_id: 'decision-a' })],
  ['step', api => api.stepRun('run-a', { action: 'step' })],
  ['recommendations', api => api.generateProactiveRecommendations()],
  ['create decision', api => api.createDecision({ scope: 'workspace', kind: 'review', title: 'Review' })],
  ['accept decision', api => api.acceptDecision('decision-a')],
  ['reject decision', api => api.rejectDecision('decision-a')],
  ['replay', api => api.replayRun('run-a')],
  ['evaluation preset', api => api.updateEvaluationPreset({ enabled: false })],
  ['delete canonical answer', api => api.deleteCanonicalAnswer('answer-a')],
  ['override outcome', api => api.overrideRunOutcome('run-a', { value: 42 })],
];

for (const status of [0, 403, 500, 504]) {
  test(`migrated canonical methods propagate ${status} by default, with the original error`, async () => {
    const failure = { status, error: { detail: { code: 'unavailable' } } };
    const fail = () => throwError(() => failure);
    const injector = Injector.create({ providers: [CanonicalApiService, {
      provide: ApiService, useValue: { get: fail, post: fail, put: fail, patch: fail, delete: fail },
    }] });
    try {
      const api = injector.get(CanonicalApiService);
      for (const [name, call] of migratedCalls) {
        await assert.rejects(firstValueFrom(call(api)), error => error === failure, name);
      }
    } finally { injector.destroy(); }
  });
}

test('a human decision without its expected id is refused before any request', async () => {
  let writes = 0;
  const injector = Injector.create({ providers: [CanonicalApiService, {
    provide: ApiService, useValue: { post: () => { writes++; throw new Error('must not send'); } },
  }] });
  try {
    await assert.rejects(firstValueFrom(injector.get(CanonicalApiService).resolveRunHitl('run-a', {
      action: 'accept', expected_decision_id: undefined,
    })), (error: unknown) => {
      assert.equal((error as { status: number }).status, 409);
      return true;
    });
    assert.equal(writes, 0);
  } finally { injector.destroy(); }
});
