import assert from 'node:assert/strict';
import test from 'node:test';
import {
  MISSION_ROOM_EXTENSION,
  SENTINEL_MISSION_ROOM_PROFILE,
  missionRoomExtensionState,
  missionRoomUsesImmersiveShell,
} from './mission-room.extension';
import {
  findOctocityForbiddenPresentationTerms,
  presentMissionRoomText,
} from './mission-room.presentation';

const SENTINEL = {
  mode: 'demo',
  settings: {
    demo_profile: 'government_mission_room',
    workspace_app_shell: 'immersive',
    workspace_app_label: 'SENTINEL-CI',
    actions: {
      enabled_packs: ['global_voice_v1', 'sentinel_ci_aya_v1', 'sentinel_ci_aya_security_v1'],
    },
    mission_room: {
      enabled: true,
      profile: SENTINEL_MISSION_ROOM_PROFILE,
      label: 'AYA',
    },
  },
};

const OCTOCITY = {
  mode: 'demo',
  settings: {
    demo_profile: 'octocity_mission_room',
    workspace_app_shell: 'immersive',
    workspace_app_label: 'Octocity Mission Room',
    actions: {
      enabled_packs: ['global_voice_v1', 'octave_mission_room_v1', 'octave_security_v1'],
    },
    mission_room: {
      enabled: true,
      profile: 'octocity_institutional_v1',
      assistant_label: 'OCTAVE',
      brand: { label: 'Octocity Mission Room' },
    },
  },
};

test('Mission Room extension keeps the existing route and API contract', () => {
  assert.deepEqual(MISSION_ROOM_EXTENSION, {
    id: 'mission-room',
    routeRoot: '/hypervisor/mission-room',
    defaultRoute: '/hypervisor/mission-room/cockpit',
    apiPrefix: '/api/v1/mission-room',
  });
});

test('Sentinel resolves its own brand, assistant and action packs', () => {
  const state = missionRoomExtensionState(SENTINEL);

  assert.equal(state.enabled, true);
  assert.equal(state.profile, SENTINEL_MISSION_ROOM_PROFILE);
  assert.equal(state.label, 'SENTINEL-CI');
  assert.equal(state.assistantLabel, 'AYA');
  assert.deepEqual(state.actionPacks, [
    'global_voice_v1',
    'sentinel_ci_aya_v1',
    'sentinel_ci_aya_security_v1',
  ]);
  assert.doesNotMatch(JSON.stringify(state), /Octocity|OCTAVE|octave_/);
});

test('Octocity resolves its own brand, assistant and action packs without Sentinel terms', () => {
  const state = missionRoomExtensionState(OCTOCITY);

  assert.equal(state.enabled, true);
  assert.equal(state.profile, 'octocity_institutional_v1');
  assert.equal(state.label, 'Octocity Mission Room');
  assert.equal(state.assistantLabel, 'OCTAVE');
  assert.deepEqual(state.actionPacks, [
    'global_voice_v1',
    'octave_mission_room_v1',
    'octave_security_v1',
  ]);
  assert.doesNotMatch(JSON.stringify(state), /SENTINEL-CI|AYA|sentinel_ci_aya_/);
});

test('immersive shell is restricted to an enabled demo extension route', () => {
  assert.equal(
    missionRoomUsesImmersiveShell(SENTINEL, '/hypervisor/mission-room/cockpit'),
    true,
  );
  assert.equal(missionRoomUsesImmersiveShell(SENTINEL, '/systems'), false);
  assert.equal(
    missionRoomUsesImmersiveShell(
      { ...SENTINEL, settings: { ...SENTINEL.settings, mission_room: { enabled: false } } },
      '/hypervisor/mission-room/cockpit',
    ),
    false,
  );
});

test('legacy Sentinel demo profile resolves to the canonical extension profile', () => {
  const legacy = {
    ...SENTINEL,
    settings: {
      ...SENTINEL.settings,
      mission_room: { enabled: true, label: 'AYA' },
    },
  };

  assert.equal(missionRoomExtensionState(legacy).profile, SENTINEL_MISSION_ROOM_PROFILE);
});

test('Octocity last-mile presentation removes every Sentinel vocabulary family', () => {
  const source = [
    'SENTINEL-CI · AYA flag · Vice Premier Ministre · VPM · Côte d’Ivoire',
    'Ambassadeur de France · BCEAO · UEMOA · XOF · CFA',
    'Abidjan · Yamoussoukro · Bouaké · Korhogo · Bouna · Kong · San Pedro',
    'Vridi · Nawa · Soubre · Napié · CEDEAO · FANCI · Préfecture · Préfet',
    "cacao · anacarde · Afrique de l'Ouest · West Africa · Sahel · Gulf of Guinea · CI",
  ].join(' | ');

  const rendered = presentMissionRoomText('octocity_institutional_v1', source);
  assert.deepEqual(findOctocityForbiddenPresentationTerms(rendered), []);
  assert.match(rendered, /Octocity Mission Room/);
  assert.match(rendered, /OCTAVE flag/);
  assert.match(rendered, /Alliance Aurora/);
  assert.match(rendered, /Asteria/);
  assert.match(rendered, /Meridian/);
});

test('presentation is profile-scoped and bounded around the CI token', () => {
  const source = 'AYA · Indice CEDEAO · OCTOCITY DECISION · CI';
  assert.equal(presentMissionRoomText(SENTINEL_MISSION_ROOM_PROFILE, source), source);
  assert.equal(
    presentMissionRoomText('octocity_institutional_v1', source),
    'OCTAVE · Indice Alliance Aurora · OCTOCITY DECISION · AS',
  );
});
