import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  AGENTIUM_SURFACE_ROUTES,
  BUSINESS_NAVIGATION_SURFACE_IDS,
  COCKPIT_VERBS,
  agentiumSurfaceById,
  matchCockpitVerb,
  navigationLensUrl,
  navigationObjectUrl,
  navigationPortfolioUrl,
  navigationRouteContext,
  navigationScopeUrl,
  pathAllowedBySurfaceIds,
} from './navigation.catalog';

test('Client360 stays classified under Operate in the standard admin cockpit', () => {
  const surface = AGENTIUM_SURFACE_ROUTES.find((item) => item.id === 'client360-pdr');

  assert.equal(surface?.lens, 'operate');
  assert.equal(matchCockpitVerb('/client360')?.key, 'operate');
  assert.equal(matchCockpitVerb('/client360/opportunities')?.key, 'operate');
});

test('surface registry owns unique ids and every rail section references it', () => {
  assert.equal(
    new Set(AGENTIUM_SURFACE_ROUTES.map((surface) => surface.id)).size,
    AGENTIUM_SURFACE_ROUTES.length,
  );
  for (const verb of COCKPIT_VERBS) {
    assert.ok(agentiumSurfaceById(verb.primarySurfaceId), verb.primarySurfaceId);
    for (const section of [...(verb.sections ?? []), ...(verb.legacySections ?? [])]) {
      assert.ok(agentiumSurfaceById(section.surfaceId), section.surfaceId);
    }
  }
});

test('lens changes preserve Capability, System and Run identity for every cockpit lens', () => {
  const objects = [
    { url: '/capabilities/cap-42?tab=overview', type: 'capability', ref: 'cap-42' },
    { url: '/systems/sys-42?tab=overview', type: 'system', ref: 'sys-42' },
    { url: '/runs/run-42?tab=outcome', type: 'run', ref: 'run-42' },
  ] as const;
  const lenses = ['hypervisor', 'build', 'operate', 'steer', 'govern'] as const;

  for (const object of objects) {
    for (const lens of lenses) {
      const target = navigationLensUrl(object.url, lens, '/should-not-be-used');
      const parsed = navigationRouteContext(target);
      assert.equal(parsed.path, object.url.split('?')[0]);
      assert.equal(parsed.selectedType, object.type);
      assert.equal(parsed.selectedRef, object.ref);
      assert.equal(parsed.lens, lens);
    }
  }

  const scopedList = navigationRouteContext(navigationLensUrl(
    '/skills?scope=skills&capabilityId=cap-42&systemId=sys-42&runId=run-42',
    'govern',
    '/governance',
  ));
  assert.equal(scopedList.capabilityId, 'cap-42');
  assert.equal(scopedList.systemId, 'sys-42');
  assert.equal(scopedList.runId, 'run-42');
  assert.equal(scopedList.scope, 'skills');
  assert.equal(scopedList.lens, 'govern');
});

test('scope routes retain the real current ancestry', () => {
  const build = COCKPIT_VERBS.find((verb) => verb.key === 'build')!;
  const operate = COCKPIT_VERBS.find((verb) => verb.key === 'operate')!;
  const systems = build.sections!.find((section) => section.key === 'systems')!;
  const runs = operate.sections!.find((section) => section.key === 'runs')!;
  const skills = build.sections!.find((section) => section.key === 'skills')!;
  const capabilityScope = navigationRouteContext(navigationScopeUrl(systems, {
    capabilityId: 'cap-1',
    systemId: null,
    runId: null,
    skillRef: null,
  }, 'build'));
  assert.equal(capabilityScope.path, '/systems');
  assert.equal(capabilityScope.capabilityId, 'cap-1');
  assert.equal(capabilityScope.scope, 'systems');

  const systemScope = navigationRouteContext(navigationScopeUrl(runs, {
    capabilityId: 'cap-1',
    systemId: 'sys-1',
    runId: null,
    skillRef: null,
  }, 'operate'));
  assert.equal(systemScope.path, '/runs');
  assert.equal(systemScope.capabilityId, 'cap-1');
  assert.equal(systemScope.systemId, 'sys-1');
  assert.equal(systemScope.scope, 'runs');

  const runScope = navigationRouteContext(navigationScopeUrl(skills, {
    capabilityId: 'cap-1',
    systemId: 'sys-1',
    runId: 'run-1',
    skillRef: null,
  }, 'operate'));
  assert.equal(runScope.path, '/skills');
  assert.equal(runScope.capabilityId, 'cap-1');
  assert.equal(runScope.systemId, 'sys-1');
  assert.equal(runScope.runId, 'run-1');
  assert.equal(runScope.scope, 'skills');
  assert.equal(runScope.lens, 'operate');
});

test('object builders use canonical locators and business guards match registered surfaces', () => {
  assert.equal(navigationPortfolioUrl('steer'), '/hypervisor?lens=steer');
  assert.equal(navigationPortfolioUrl('hypervisor'), '/hypervisor');
  assert.equal(navigationObjectUrl('capability', 'cap/42'), '/capabilities/cap%2F42');
  assert.equal(navigationObjectUrl('system', 'sys-42', { lens: 'operate' }), '/systems/sys-42?lens=operate');
  assert.equal(navigationObjectUrl('run', 'run-42', { lens: 'operate' }), '/runs/run-42');
  assert.equal(navigationObjectUrl('skill', 'invoice_extract_v1'), '/skills/invoice_extract_v1');
  assert.equal(
    navigationObjectUrl('system', 'system-b', {
      capabilityId: 'cap-b',
      runId: 'run-from-system-a',
      skillRef: 'stale-skill',
    }),
    '/systems/system-b?capabilityId=cap-b',
  );
  assert.equal(
    navigationLensUrl(
      '/systems/system-b?runId=run-from-system-a&capabilityId=spoof',
      'operate',
      '/runs',
      { capabilityId: 'cap-b', systemId: 'system-b', runId: null, skillRef: null },
    ),
    '/systems/system-b?lens=operate&capabilityId=cap-b',
  );

  assert.equal(pathAllowedBySurfaceIds('/chat', BUSINESS_NAVIGATION_SURFACE_IDS), true);
  assert.equal(pathAllowedBySurfaceIds('/client360/opportunities', BUSINESS_NAVIGATION_SURFACE_IDS), true);
  assert.equal(pathAllowedBySurfaceIds('/knowledge/capture?systemId=sys-1', BUSINESS_NAVIGATION_SURFACE_IDS), true);
  assert.equal(pathAllowedBySurfaceIds('/systems/sys-1', BUSINESS_NAVIGATION_SURFACE_IDS), false);
});

test('unknown navigation query values never influence the cockpit projection', () => {
  const parsed = navigationRouteContext('/systems/sys-1?lens=destroy&scope=unknown&parent=spoof');
  assert.equal(parsed.lens, 'build');
  assert.equal(parsed.scope, null);
  assert.deepEqual(parsed.query, { lens: 'destroy', scope: 'unknown' });
  assert.equal(parsed.capabilityId, null);
});
