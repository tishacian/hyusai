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
  isObjectLens,
} from './navigation.catalog';

test('Client360 stays classified under Operate in the standard admin cockpit', () => {
  const surface = AGENTIUM_SURFACE_ROUTES.find((item) => item.id === 'client360-pdr');

  assert.equal(surface?.lens, 'operate');
  assert.equal(matchCockpitVerb('/client360')?.key, 'operate');
  assert.equal(matchCockpitVerb('/client360/opportunities')?.key, 'operate');
});

test('Andritz business app catalog keeps its stable routes and API prefixes', () => {
  assert.deepEqual(
    BUSINESS_NAVIGATION_SURFACE_IDS.map((surfaceId) => {
      const surface = agentiumSurfaceById(surfaceId);
      return {
        id: surfaceId,
        route: surface?.route,
        apiPrefix: surface?.apiPrefix,
      };
    }),
    [
      { id: 'chat', route: '/chat', apiPrefix: '/api/v1/chat' },
      { id: 'client360-pdr', route: '/client360', apiPrefix: '/api/v1/client360' },
      {
        id: 'knowledge-capture',
        route: '/knowledge/capture',
        apiPrefix: '/api/v1/knowledge-capture',
      },
      {
        id: 'fse-reports',
        route: '/knowledge/interventions',
        apiPrefix: '/api/v1/knowledge-capture',
      },
    ],
  );
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

test('lens changes preserve Capability, System, Run and SkillInvocation identity', () => {
  const objects = [
    { url: '/capabilities/cap-42?tab=overview', type: 'capability', ref: 'cap-42' },
    { url: '/systems/sys-42?tab=overview', type: 'system', ref: 'sys-42' },
    { url: '/runs/run-42?tab=outcome', type: 'run', ref: 'run-42' },
    {
      url: '/runs/run-42/invocations/inv-7?tab=runtime',
      type: 'skill_invocation',
      ref: 'inv-7',
    },
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
    skillInvocationId: null,
    skillRef: null,
  }, 'build'));
  assert.equal(capabilityScope.path, '/systems');
  assert.equal(capabilityScope.capabilityId, 'cap-1');
  assert.equal(capabilityScope.scope, 'systems');

  const systemScope = navigationRouteContext(navigationScopeUrl(runs, {
    capabilityId: 'cap-1',
    systemId: 'sys-1',
    runId: null,
    skillInvocationId: null,
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
    skillInvocationId: null,
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
  assert.equal(navigationPortfolioUrl('steer', true), '/hypervisor');
  assert.equal(navigationObjectUrl('capability', 'cap/42'), '/capabilities/cap%2F42');
  assert.equal(navigationObjectUrl('system', 'sys-42', { lens: 'operate' }), '/systems/sys-42?lens=operate');
  assert.equal(navigationObjectUrl('run', 'run-42', { lens: 'operate' }), '/runs/run-42');
  assert.equal(
    navigationObjectUrl('skill_invocation', 'inv/42', {
      runId: 'run/42',
      systemId: 'sys-42',
      capabilityId: 'cap-42',
      lens: 'govern',
    }),
    '/runs/run%2F42/invocations/inv%2F42?lens=govern&capabilityId=cap-42&systemId=sys-42',
  );
  assert.throws(
    () => navigationObjectUrl('skill_invocation', 'inv-42'),
    /requires its canonical parent runId/,
  );
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
      { capabilityId: 'cap-b', systemId: 'system-b', runId: null, skillInvocationId: null, skillRef: null },
    ),
    '/systems/system-b?lens=operate&capabilityId=cap-b',
  );

  assert.equal(pathAllowedBySurfaceIds('/chat', BUSINESS_NAVIGATION_SURFACE_IDS), true);
  assert.equal(pathAllowedBySurfaceIds('/client360/opportunities', BUSINESS_NAVIGATION_SURFACE_IDS), true);
  assert.equal(pathAllowedBySurfaceIds('/knowledge/capture?systemId=sys-1', BUSINESS_NAVIGATION_SURFACE_IDS), true);
  assert.equal(pathAllowedBySurfaceIds('/knowledge/interventions', BUSINESS_NAVIGATION_SURFACE_IDS), true);
  assert.equal(pathAllowedBySurfaceIds('/systems/sys-1', BUSINESS_NAVIGATION_SURFACE_IDS), false);
});

test('axes v4 has four object lenses and a distinct Portfolio destination', () => {
  assert.deepEqual(
    COCKPIT_VERBS.filter((verb) => isObjectLens(verb.key)).map((verb) => verb.key),
    ['build', 'operate', 'steer', 'govern'],
  );
  assert.deepEqual(COCKPIT_VERBS.find((verb) => verb.key === 'hypervisor')?.v4Sections, []);
  assert.equal(isObjectLens('hypervisor'), false);
  assert.equal(
    navigationLensUrl(
      '/systems/sys-1?lens=govern&facet=design',
      'build',
      '/build',
      { capabilityId: 'cap-1', systemId: 'sys-1', runId: null, skillInvocationId: null, skillRef: null },
      true,
    ),
    '/systems/sys-1?facet=design&lens=build&capabilityId=cap-1',
  );
});

test('unknown navigation query values never influence the cockpit projection', () => {
  const parsed = navigationRouteContext('/systems/sys-1?lens=destroy&scope=unknown&parent=spoof');
  assert.equal(parsed.lens, 'build');
  assert.equal(parsed.scope, null);
  assert.deepEqual(parsed.query, { lens: 'destroy', scope: 'unknown' });
  assert.equal(parsed.capabilityId, null);
});
