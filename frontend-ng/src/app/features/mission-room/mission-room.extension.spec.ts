import assert from 'node:assert/strict';
import test from 'node:test';
import {
  GENERIC_MISSION_ROOM_PROVIDER_ENDPOINTS,
  GENERIC_MISSION_ROOM_PROVIDER_KIND,
  MISSION_ROOM_EXTENSION,
  OCTOCITY_MISSION_ROOM_PROFILE,
  SENTINEL_MISSION_ROOM_PROFILE,
  missionRoomExtensionState,
  missionRoomUsesImmersiveShell,
} from './mission-room.extension';
import {
  findOctocityForbiddenPresentationTerms,
  presentMissionRoomText,
} from './mission-room.presentation';
import type {
  WorkspaceAppRuntimeMissionRoom,
  WorkspaceAppRuntimeProjection,
} from '@app/core/workspace.service';

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
      profile: OCTOCITY_MISSION_ROOM_PROFILE,
      assistant_label: 'OCTAVE',
      brand: { label: 'Octocity Mission Room' },
    },
  },
};

function authoritativeMissionRuntime(
  appId: string,
  brandingNamespace: string,
  missionRoom: WorkspaceAppRuntimeMissionRoom,
  actionPacks: string[],
): WorkspaceAppRuntimeProjection {
  return {
    schema_version: 1,
    mode: 'authoritative',
    enabled: true,
    valid: true,
    installations: [{
      app_id: appId,
      version: missionRoom.version,
      manifest_digest: missionRoom.manifest_digest,
      category: 'workspace_extension',
      routes: ['/hypervisor/mission-room'],
      primary_surface_id: 'mission-room',
      default_route: '/hypervisor/mission-room/cockpit',
      branding_namespace: brandingNamespace,
      api_prefixes: ['/api/v1/mission-room'],
      action_packs: actionPacks,
      entitlement_keys: [],
    }],
    experience: {
      shell: 'immersive',
      routes: ['/hypervisor/mission-room'],
      primary_surface_ids: ['mission-room'],
      default_routes: { [appId]: '/hypervisor/mission-room/cockpit' },
      branding_namespaces: [brandingNamespace],
      api_prefixes: ['/api/v1/mission-room'],
      action_packs: actionPacks,
      mission_room: missionRoom,
    },
  };
}

const SENTINEL_RUNTIME_MISSION: WorkspaceAppRuntimeMissionRoom = {
  profile: SENTINEL_MISSION_ROOM_PROFILE,
  assistant_profile: 'vigie_executive',
  label: 'SENTINEL-CI',
  assistant_label: 'AYA',
  brand_style: 'sentinel',
  navigation_keys: ['cockpit', 'strategie', 'securite'],
  app_id: 'sentinel.mission-room',
  version: '1.0.0',
  manifest_digest: 'sentinel-runtime-digest',
  default_route: '/hypervisor/mission-room/cockpit',
  primary_surface_id: 'mission-room',
};

const OCTOCITY_RUNTIME_MISSION: WorkspaceAppRuntimeMissionRoom = {
  profile: OCTOCITY_MISSION_ROOM_PROFILE,
  assistant_profile: 'octave_executive',
  label: 'Octocity Mission Room',
  assistant_label: 'OCTAVE',
  brand_style: 'agentium',
  navigation_keys: ['cockpit', 'strategie', 'securite'],
  app_id: 'octocity.mission-room',
  version: '1.0.0',
  manifest_digest: 'octocity-runtime-digest',
  default_route: '/hypervisor/mission-room/cockpit',
  primary_surface_id: 'mission-room',
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
  assert.equal(state.legacyMorningDismissedStorageKey, 'sentinel-ci-aya-morning-dismissed');
  assert.doesNotMatch(JSON.stringify(state), /Octocity|OCTAVE|octave_/);
});

test('Octocity resolves its own brand, assistant and action packs without Sentinel terms', () => {
  const state = missionRoomExtensionState(OCTOCITY);

  assert.equal(state.enabled, true);
  assert.equal(state.profile, OCTOCITY_MISSION_ROOM_PROFILE);
  assert.equal(state.label, 'Octocity Mission Room');
  assert.equal(state.assistantLabel, 'OCTAVE');
  assert.deepEqual(state.actionPacks, [
    'global_voice_v1',
    'octave_mission_room_v1',
    'octave_security_v1',
  ]);
  assert.equal(state.legacyMorningDismissedStorageKey, null);
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
  assert.equal(
    missionRoomExtensionState(legacy).legacyMorningDismissedStorageKey,
    'sentinel-ci-aya-morning-dismissed',
  );
});

test('authoritative Sentinel runtime ignores every tampered Octocity legacy field', () => {
  const runtime = authoritativeMissionRuntime(
    'sentinel.mission-room',
    'sentinel',
    SENTINEL_RUNTIME_MISSION,
    ['global_voice_v1', 'sentinel_ci_aya_v1', 'sentinel_ci_aya_security_v1'],
  );
  const workspace = {
    ...OCTOCITY,
    settings: {
      ...OCTOCITY.settings,
      features: { workspace_app_platform_v1: true },
    },
    workspace_app_runtime: runtime,
  };
  const state = missionRoomExtensionState(workspace);

  assert.equal(state.authority, 'workspace_app_runtime');
  assert.equal(state.enabled, true);
  assert.equal(state.profile, SENTINEL_MISSION_ROOM_PROFILE);
  assert.equal(state.label, 'SENTINEL-CI');
  assert.equal(state.assistantLabel, 'AYA');
  assert.equal(state.assistantProfile, 'vigie_executive');
  assert.equal(state.brandStyle, 'sentinel');
  assert.deepEqual(state.actionPacks, runtime.experience?.action_packs);
  assert.doesNotMatch(JSON.stringify(state), /octocity|octave/i);
  assert.equal(missionRoomUsesImmersiveShell(workspace, '/hypervisor/mission-room/cockpit'), true);
});

test('authoritative Octocity runtime ignores every tampered Sentinel legacy field', () => {
  const runtime = authoritativeMissionRuntime(
    'octocity.mission-room',
    'octocity',
    OCTOCITY_RUNTIME_MISSION,
    ['global_voice_v1', 'octave_mission_room_v1', 'octave_security_v1'],
  );
  const workspace = {
    ...SENTINEL,
    settings: {
      ...SENTINEL.settings,
      features: { workspace_app_platform_v1: true },
    },
    workspace_app_runtime: runtime,
  };
  const state = missionRoomExtensionState(workspace);

  assert.equal(state.authority, 'workspace_app_runtime');
  assert.equal(state.enabled, true);
  assert.equal(state.profile, OCTOCITY_MISSION_ROOM_PROFILE);
  assert.equal(state.label, 'Octocity Mission Room');
  assert.equal(state.assistantLabel, 'OCTAVE');
  assert.equal(state.assistantProfile, 'octave_executive');
  assert.equal(state.brandStyle, 'agentium');
  assert.deepEqual(state.actionPacks, runtime.experience?.action_packs);
  assert.doesNotMatch(JSON.stringify(state), /sentinel|\baya\b|vigie/i);
  assert.equal(missionRoomUsesImmersiveShell(workspace, '/hypervisor/mission-room/cockpit'), true);
});

test('enabled Workspace App platform never falls back to legacy Mission Room settings', () => {
  const workspace = {
    ...SENTINEL,
    settings: {
      ...SENTINEL.settings,
      features: { workspace_app_platform_v1: true },
    },
    workspace_app_runtime: {
      mode: 'authoritative',
      enabled: true,
      valid: false,
      installations: [],
      experience: null,
    } as WorkspaceAppRuntimeProjection,
  };
  const state = missionRoomExtensionState(workspace);

  assert.deepEqual(state, {
    authority: 'fail_closed',
    enabled: false,
    profile: null,
    label: null,
    assistantLabel: null,
    assistantProfile: null,
    brandStyle: null,
    actionPacks: [],
    providerKind: null,
    providerEndpoints: [],
    genericProvider: false,
    legacyMorningDismissedStorageKey: null,
  });
  assert.equal(missionRoomUsesImmersiveShell(workspace, '/hypervisor/mission-room/cockpit'), false);
});

test('generic 1.0 and 1.1 installs stay fail closed without a provider contract', () => {
  const genericMission: WorkspaceAppRuntimeMissionRoom = {
    profile: 'board-room',
    assistant_profile: 'facilitator',
    label: 'Mission Room',
    assistant_label: 'Assistant',
    brand_style: 'agentium',
    navigation_keys: ['cockpit', 'strategie', 'securite'],
    app_id: 'mission-room.extension',
    version: '1.1.0',
    manifest_digest: 'generic-runtime-digest',
    default_route: '/hypervisor/mission-room/cockpit',
    primary_surface_id: 'mission-room',
  };
  const workspace = {
    mode: 'demo',
    settings: {
      features: { workspace_app_platform_v1: true },
      mission_room: {
        enabled: true,
        profile: SENTINEL_MISSION_ROOM_PROFILE,
        assistant_label: 'AYA',
      },
    },
    workspace_app_runtime: authoritativeMissionRuntime(
      'mission-room.extension',
      'mission-room',
      genericMission,
      ['global_voice_v1'],
    ),
  };

  const state = missionRoomExtensionState(workspace);

  assert.equal(state.authority, 'fail_closed');
  assert.equal(state.enabled, false);
  assert.equal(state.profile, null);
  assert.deepEqual(state.actionPacks, []);
  assert.equal(
    missionRoomUsesImmersiveShell(workspace, '/hypervisor/mission-room/cockpit'),
    false,
  );

  const legacy10 = structuredClone(workspace);
  const legacy10Mission = legacy10.workspace_app_runtime.experience?.mission_room;
  if (legacy10Mission) legacy10Mission.version = '1.0.0';
  legacy10.workspace_app_runtime.installations[0].version = '1.0.0';
  assert.equal(missionRoomExtensionState(legacy10).enabled, false);
  assert.equal(missionRoomExtensionState(legacy10).genericProvider, false);
});

test('generic 1.2 runtime is enabled only by the exact provider contract', () => {
  const genericMission: WorkspaceAppRuntimeMissionRoom = {
    profile: 'generic',
    assistant_profile: 'default',
    label: 'Mission Room',
    assistant_label: 'Assistant',
    brand_style: 'agentium',
    navigation_keys: ['cockpit', 'strategie', 'securite', 'reputation', 'agenda', 'presse', 'decisions'],
    app_id: 'mission-room.extension',
    version: '1.2.0',
    manifest_digest: 'generic-1.2-runtime-digest',
    default_route: '/hypervisor/mission-room/cockpit',
    primary_surface_id: 'mission-room',
    provider_kind: GENERIC_MISSION_ROOM_PROVIDER_KIND,
    provider_endpoints: [...GENERIC_MISSION_ROOM_PROVIDER_ENDPOINTS],
  };
  const workspace = {
    mode: 'demo',
    settings: { features: { workspace_app_platform_v1: true } },
    workspace_app_runtime: authoritativeMissionRuntime(
      'mission-room.extension',
      'mission-room',
      genericMission,
      ['global_voice_v1'],
    ),
  };

  const state = missionRoomExtensionState(workspace);

  assert.equal(state.authority, 'workspace_app_runtime');
  assert.equal(state.enabled, true);
  assert.equal(state.genericProvider, true);
  assert.equal(state.providerKind, GENERIC_MISSION_ROOM_PROVIDER_KIND);
  assert.deepEqual(state.providerEndpoints, GENERIC_MISSION_ROOM_PROVIDER_ENDPOINTS);
  assert.doesNotMatch(
    JSON.stringify({
      label: state.label,
      assistantLabel: state.assistantLabel,
      profile: state.profile,
      actionPacks: state.actionPacks,
    }),
    /\bAYA\b|SENTINEL-CI|Abidjan|CEDEAO|Sahel|OCTAVE/,
  );
  assert.equal(
    missionRoomUsesImmersiveShell(workspace, '/hypervisor/mission-room/cockpit'),
    true,
  );

  const tampered = structuredClone(workspace);
  const endpoints = tampered.workspace_app_runtime.experience?.mission_room?.provider_endpoints;
  endpoints?.reverse();
  assert.equal(missionRoomExtensionState(tampered).enabled, false);
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
