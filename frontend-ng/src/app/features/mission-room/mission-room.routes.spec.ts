import '@angular/compiler';
import assert from 'node:assert/strict';
import test from 'node:test';
import { missionRoomRoutes } from './mission-room.routes';

test('Mission Room extension preserves its exact public route table', () => {
  assert.equal(missionRoomRoutes.length, 1);
  const root = missionRoomRoutes[0];
  assert.equal(root.path, '');
  assert.equal(typeof root.loadComponent, 'function');

  const children = root.children ?? [];
  assert.deepEqual(
    children.map((route) => ({
      path: route.path,
      redirectTo: route.redirectTo ?? null,
      pathMatch: route.pathMatch ?? null,
    })),
    [
      { path: '', redirectTo: 'cockpit', pathMatch: 'full' },
      { path: 'securite/monitor', redirectTo: null, pathMatch: null },
      { path: 'veille-sociale', redirectTo: null, pathMatch: null },
      { path: 'agenda/meeting/:event_id', redirectTo: null, pathMatch: null },
      { path: ':view', redirectTo: null, pathMatch: null },
    ],
  );
  for (const route of children.slice(1)) {
    assert.equal(typeof route.loadComponent, 'function');
  }
});
