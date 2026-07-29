import '@angular/compiler';
import assert from 'node:assert/strict';
import test from 'node:test';
import { runsRoutes } from './runs.routes';

test('SkillInvocation is a dedicated Run child resource before the generic Run route', async () => {
  assert.deepEqual(runsRoutes.map((route) => route.path), [
    '',
    ':runId/invocations/:invocationId',
    ':runId',
  ]);

  const invocationRoute = runsRoutes[1];
  const runRoute = runsRoutes[2];
  assert.equal(typeof invocationRoute.loadComponent, 'function');
  assert.equal(typeof runRoute.loadComponent, 'function');
  assert.notEqual(invocationRoute.loadComponent, runRoute.loadComponent);
  assert.equal(invocationRoute.path?.includes('skills'), false, 'catalog Skill keeps its separate /skills route');
  assert.equal((await invocationRoute.loadComponent!()).name, 'SkillInvocationViewComponent');
  assert.equal((await runRoute.loadComponent!()).name, 'RunViewComponent');
});
