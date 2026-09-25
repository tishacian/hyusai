import '@angular/compiler';
import assert from 'node:assert/strict';
import test from 'node:test';
import { missionRoomRoutes } from './mission-room.routes';
import {
  missionRoomImpactTarget,
  missionRoomImpactUrl,
} from './mission-room-redirects';

test('Mission Room routes are Impact redirects only (L13a)', () => {
  assert.equal(missionRoomRoutes.length, 6);
  assert.deepEqual(
    missionRoomRoutes.map((route) => ({
      path: route.path,
      hasRedirect: typeof route.redirectTo === 'function' || typeof route.redirectTo === 'string',
      pathMatch: route.pathMatch ?? null,
    })),
    [
      { path: '', hasRedirect: true, pathMatch: 'full' },
      { path: 'securite/monitor', hasRedirect: true, pathMatch: null },
      { path: 'veille-sociale', hasRedirect: true, pathMatch: null },
      { path: 'agenda/meeting/:event_id', hasRedirect: true, pathMatch: null },
      { path: 'recherche', hasRedirect: true, pathMatch: null },
      { path: ':view', hasRedirect: true, pathMatch: null },
    ],
  );
  for (const route of missionRoomRoutes) {
    assert.equal(route.loadComponent, undefined, `${route.path} must not load a component`);
  }
});

test('Mission Room redirect table maps every legacy address (replaceUrl targets)', () => {
  const cases: Array<[string, string]> = [
    ['/hypervisor/mission-room/cockpit', '/hypervisor?theme=presentation'],
    ['/hypervisor/mission-room', '/hypervisor?theme=presentation'],
    ['/hypervisor/mission-room/agenda', '/hypervisor?view=agenda'],
    ['/hypervisor/mission-room/agenda/meeting/evt-1', '/hypervisor?view=reunion&eventId=evt-1'],
    ['/hypervisor/mission-room/veille-sociale', '/hypervisor?view=veille'],
    ['/hypervisor/mission-room/reputation', '/hypervisor?view=veille'],
    ['/hypervisor/mission-room/presse', '/hypervisor?view=veille'],
    ['/hypervisor/mission-room/securite', '/hypervisor?view=securite'],
    ['/hypervisor/mission-room/securite/monitor', '/hypervisor?view=securite'],
    ['/hypervisor/mission-room/strategie', '/hypervisor?view=carte'],
    ['/hypervisor/mission-room/monitor', '/hypervisor?view=carte'],
    ['/hypervisor/mission-room/decisions', '/hypervisor?facet=decisions'],
  ];
  for (const [from, to] of cases) {
    assert.equal(missionRoomImpactUrl(from), to, from);
  }
  const recherche = missionRoomImpactTarget('/hypervisor/mission-room/recherche');
  assert.deepEqual(recherche, {
    path: '/hypervisor',
    queryParams: {},
    openPalette: true,
  });
});
