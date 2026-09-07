import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  AGENTIUM_SURFACE_LEAVES,
  AGENTIUM_SURFACE_ROUTES,
  BUSINESS_NAVIGATION_SURFACE_IDS,
  COCKPIT_VERBS,
  agentiumSurfaceById,
  cockpitVerbSections,
  objectFacetsFor,
  systemFacetForChild,
  matchCockpitVerb,
  navigationLeafUrl,
  navigationLensUrl,
  navigationObjectUrl,
  navigationPortfolioUrl,
  navigationRouteContext,
  navigationScopeUrl,
  navigationSectionNaming,
  navigationSurfaceUrl,
  pathAllowedBySurfaceIds,
  resolveNavLink,
  isObjectLens,
} from './navigation.catalog';

const EMPTY_ANCESTRY = {
  capabilityId: null,
  systemId: null,
  runId: null,
  skillInvocationId: null,
  skillRef: null,
};

function flowSection() {
  const build = COCKPIT_VERBS.find((verb) => verb.key === 'build')!;
  return build.sections!.find((section) => section.key === 'flows')!;
}

test('the Flow entry is named after the destination it resolves to', () => {
  const section = flowSection();

  const scratchpad = navigationScopeUrl(section, EMPTY_ANCESTRY, 'build');
  assert.equal(navigationSectionNaming(section, scratchpad).label, 'Scratchpad');

  const systemFlow = navigationScopeUrl(
    section,
    { ...EMPTY_ANCESTRY, systemId: 'sys-42' },
    'build',
  );
  assert.equal(navigationSectionNaming(section, systemFlow).label, 'Flow builder');

  const remembered = navigationScopeUrl(section, EMPTY_ANCESTRY, 'build', 'sys-42');
  assert.equal(navigationSectionNaming(section, remembered).label, 'Flow builder');
});

test('destination naming exposes a dedicated key so a locale can override it', () => {
  const section = flowSection();

  assert.equal(
    navigationSectionNaming(section, navigationScopeUrl(section, EMPTY_ANCESTRY, 'build')).i18nKey,
    'nav.flows.scratchpad',
  );
  assert.equal(
    navigationSectionNaming(section, '/systems/sys-42/flow').i18nKey,
    'nav.flows',
  );
});

test('sections without a dynamic destination keep their catalog naming', () => {
  for (const verb of COCKPIT_VERBS) {
    for (const section of verb.sections ?? []) {
      if (section.key === 'flows') continue;
      const naming = navigationSectionNaming(section, section.route);
      assert.equal(naming.label, section.label, section.key);
      assert.equal(naming.i18nKey, `nav.${section.key}`, section.key);
    }
  }
});

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
    for (const section of cockpitVerbSections(verb, { experienceStudio: true })) {
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
  assert.deepEqual(COCKPIT_VERBS.find((verb) => verb.key === 'hypervisor')?.sections, []);
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

test('experience studio adds one Create entry and keeps the zone catalogues', () => {
  const build = COCKPIT_VERBS.find((verb) => verb.key === 'build')!;
  const off = cockpitVerbSections(build);
  assert.deepEqual(off.map((section) => section.key), [
    'systems',
    'capabilities',
    'skills',
    'knowledge',
    'data',
    'flows',
  ]);

  const on = cockpitVerbSections(build, { experienceStudio: true });
  assert.deepEqual(on.map((section) => section.key), [
    'business_apps',
    'systems',
    'capabilities',
    'skills',
    'knowledge',
    'data',
    'flows',
  ]);
  assert.equal(matchCockpitVerb('/create')?.key, 'build');
  assert.equal(matchCockpitVerb('/create/apps')?.key, 'build');
});

test('the data plane is one Build entry that owns both of its routes', () => {
  const build = COCKPIT_VERBS.find((verb) => verb.key === 'build')!;
  const keys = build.sections!.map((section) => section.key);
  assert.equal(keys.filter((key) => key === 'data').length, 1);
  assert.equal(keys.includes('models' as never), false);
  const entry = build.sections!.find((section) => section.key === 'data')!;
  assert.equal(entry.label, 'Data & Models');
  assert.equal(entry.route, '/data');
  assert.deepEqual(entry.matches, ['/data', '/models']);
  // Deep links to a model card still resolve to a catalogued surface.
  assert.equal(agentiumSurfaceById('models')?.route, '/models');
  assert.equal(navigationRouteContext('/models/m-1?scope=models').scope, null);
});

test('Lot 6 orphan leaves are catalogued', () => {
  const ids = AGENTIUM_SURFACE_LEAVES.map((leaf) => leaf.id);
  for (const id of [
    'system-new',
    'system-flow',
    'system-run',
    'capability-curation',
    'connector-rpa-bridge',
    'create-app-new',
    'create-preview',
    'workspace-app-unavailable',
    'workspace-app-repair',
  ]) {
    assert.ok(ids.includes(id), id);
  }
  assert.equal(
    navigationLeafUrl('system-flow', { systemId: 'sys-x' }, { lens: 'operate', capabilityId: 'cap-a' }),
    '/systems/sys-x/flow?lens=operate&capabilityId=cap-a',
  );
  assert.equal(
    navigationSurfaceUrl('model-portal'),
    '/resources?facet=providers',
  );
  assert.equal(navigationSurfaceUrl('work'), '/work');
});

test('legacy query aliases hydrate the canonical grammar', () => {
  const parsed = navigationRouteContext(
    '/runs?tab=timeline&capability_id=cap-a&system_id=sys-x',
  );
  assert.equal(parsed.query['facet'], 'timeline');
  assert.equal(parsed.capabilityId, 'cap-a');
  assert.equal(parsed.systemId, 'sys-x');
});

test('nav v5 sommaire has no object-type index outside Create (I1)', () => {
  const forbidden = new Set(['capability', 'system', 'run', 'skill']);
  for (const verb of COCKPIT_VERBS) {
    const sections = cockpitVerbSections(verb);
    if (verb.key === 'build') {
      assert.ok(sections.some((section) => section.key === 'systems'));
      continue;
    }
    for (const section of sections) {
      assert.equal(
        forbidden.has(section.scopeType),
        false,
        `${verb.key}.${section.key} scopeType=${section.scopeType}`,
      );
    }
  }
});

test('OBJECT_FACETS lists System descendants used by the sommaire branch', () => {
  const facets = objectFacetsFor('system', 'operate');
  assert.deepEqual(facets.map((facet) => facet.id), [
    'overview',
    'runs',
    'skills',
    'knowledge',
    'flow',
  ]);
  assert.equal(systemFacetForChild('run'), 'runs');
  assert.equal(systemFacetForChild('skill'), 'skills');
  assert.equal(systemFacetForChild('capability'), null);
});

test('a page link keeps lens and ancestry (I3)', () => {
  const context = {
    lens: 'operate' as const,
    ancestry: {
      capabilityId: 'cap-a',
      systemId: 'sys-x',
      runId: null,
      skillInvocationId: null,
      skillRef: null,
    },
    currentUrl: '/systems/sys-x?lens=operate&capabilityId=cap-a',
  };

  assert.equal(
    resolveNavLink({ leaf: 'system-flow', ref: 'sys-x' }, context).url,
    '/systems/sys-x/flow?lens=operate&capabilityId=cap-a',
  );
  assert.equal(
    resolveNavLink({ surface: 'knowledge' }, context).url,
    '/knowledge?lens=operate&capabilityId=cap-a&systemId=sys-x',
  );
  assert.equal(
    resolveNavLink({ type: 'run', ref: 'run-1' }, context).url,
    '/runs/run-1?capabilityId=cap-a&systemId=sys-x',
  );

  const facet = resolveNavLink({ facet: 'runs' }, context);
  assert.equal(facet.replaceUrl, true);
  assert.equal(facet.url, '/systems/sys-x?lens=operate&facet=runs&capabilityId=cap-a');
});
