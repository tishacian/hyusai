import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import {
  AGENTIUM_SURFACE_LEAVES,
  AGENTIUM_SURFACE_ROUTES,
  BUSINESS_NAVIGATION_SURFACE_IDS,
  COCKPIT_VERBS,
  agentiumSurfaceById,
  cockpitVerbSections,
  navigationBreadcrumbRootUrl,
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
  type HierarchyObjectType,
  HYPERVISOR_FACETS,
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
  assert.equal(navigationSectionNaming(section, scratchpad).label, 'Nouveau flux');

  const systemFlow = navigationScopeUrl(
    section,
    { ...EMPTY_ANCESTRY, systemId: 'sys-42' },
    'build',
  );
  assert.equal(navigationSectionNaming(section, systemFlow).label, 'System flow');

  const remembered = navigationScopeUrl(section, EMPTY_ANCESTRY, 'build', 'sys-42');
  assert.equal(navigationSectionNaming(section, remembered).label, 'System flow');
});

test('destination naming exposes a dedicated key so a locale can override it', () => {
  const section = flowSection();

  assert.equal(
    navigationSectionNaming(section, navigationScopeUrl(section, EMPTY_ANCESTRY, 'build')).i18nKey,
    'nav.flows.scratchpad',
  );
  assert.equal(
    navigationSectionNaming(section, '/systems/sys-42/flow').i18nKey,
    'nav.flows.system',
  );
});

test('sections without a dynamic destination keep their catalog naming', () => {
  for (const verb of COCKPIT_VERBS) {
    for (const section of verb.sections ?? []) {
      if (section.key === 'flows' || section.facet) continue;
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

test('every breadcrumb root returns to the catalogue owning that object type', () => {
  const expected: Record<HierarchyObjectType, string> = {
    capability: '/capabilities',
    system: '/systems',
    run: '/runs',
    // An invocation is runtime evidence, not a standalone catalogue.
    skill_invocation: '/runs',
    skill: '/skills',
    collection: '/knowledge',
    dataset: '/data',
    model: '/models',
    context: '/steering/contexts',
    conversation: '/conversations',
    business_app: '/create/apps',
  };

  for (const [type, root] of Object.entries(expected)) {
    assert.equal(
      navigationBreadcrumbRootUrl(type as HierarchyObjectType, 'build').split('?')[0],
      root,
      `${type} breadcrumb root`,
    );
    const surfacePath = navigationRouteContext(root).path;
    assert.notEqual(
      surfacePath,
      navigationRouteContext(navigationObjectUrl(
        type as HierarchyObjectType,
        'ref-1',
        type === 'skill_invocation' ? { runId: 'run-1' } : {},
      )).path,
      `${type} breadcrumb root must not return to the current object`,
    );
    assert.match(surfacePath, /^\/[a-z/-]+$/);
    assert.equal(navigationRouteContext(navigationBreadcrumbRootUrl(type as HierarchyObjectType, 'build')).lens, 'build');
  }
});

test('axes v4 has four object lenses and a distinct Portfolio destination', () => {
  assert.deepEqual(
    COCKPIT_VERBS.filter((verb) => isObjectLens(verb.key)).map((verb) => verb.key),
    ['build', 'operate', 'steer', 'govern'],
  );
  assert.deepEqual(
    COCKPIT_VERBS.find((verb) => verb.key === 'hypervisor')?.sections?.map((section) => section.key),
    ['synthese', 'registre', 'couts', 'bases', 'decisions', 'journal'],
  );
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
    'models',
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
    'models',
    'flows',
  ]);
  assert.equal(on[0]?.label, 'Business applications');
  assert.equal(on.find((section) => section.key === 'flows')?.role, 'action');
  assert.equal(matchCockpitVerb('/create')?.key, 'build');
  assert.equal(matchCockpitVerb('/create/apps')?.key, 'build');
});

test('Data and Models are two Build entries, only one of them active', () => {
  const build = COCKPIT_VERBS.find((verb) => verb.key === 'build')!;
  const entries = build.sections!.filter((section) => ['data', 'models'].includes(section.key));
  assert.deepEqual(
    entries.map((section) => [section.key, section.label, section.route, section.scopeType]),
    [
      ['data', 'Data', '/data', 'dataset'],
      ['models', 'Models', '/models', 'model'],
    ],
  );
  const claims = (path: string) => build.sections!
    .filter((section) => (section.matches ?? [section.route])
      .some((match) => path === match || path.startsWith(match + '/')))
    .map((section) => section.key);
  assert.deepEqual(claims('/data'), ['data']);
  assert.deepEqual(claims('/data/ds-1'), ['data']);
  assert.deepEqual(claims('/models'), ['models']);
  assert.deepEqual(claims('/models/m-1'), ['models']);
  assert.equal(navigationRouteContext('/models/m-1?scope=models').scope, 'models');
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

test('OBJECT_FACETS lists System descendants used by object facets', () => {
  const facets = objectFacetsFor('system', 'operate');
  assert.deepEqual(facets.map((facet) => facet.id), [
    'overview',
    'runs',
    'design',
    'context',
    'capture',
  ]);
  assert.equal(systemFacetForChild('run'), 'runs');
  assert.equal(systemFacetForChild('skill'), 'design');
  assert.equal(systemFacetForChild('capability'), null);
});

test('Administrer sections carry Workspace, Integrations and Governance groups', () => {
  const govern = COCKPIT_VERBS.find((verb) => verb.key === 'govern')!;
  assert.deepEqual(
    govern.sections!.map((section) => [section.key, section.group]),
    [
      ['workspace', 'workspace'],
      ['access', 'workspace'],
      ['workspace_apps', 'workspace'],
      ['presets', 'workspace'],
      ['resources', 'integrations'],
      ['outils', 'integrations'],
      ['apps', 'integrations'],
      ['connectors', 'integrations'],
      ['language_models', 'integrations'],
      ['audit', 'governance'],
      ['experiences', 'governance'],
      ['canonical', 'governance'],
      ['blueprints', 'governance'],
      ['surface_map', 'governance'],
    ],
  );
});

test('Administrer lists destinations in three groups including Outils and Extensions', () => {
  const govern = COCKPIT_VERBS.find((verb) => verb.key === 'govern')!;
  const sections = cockpitVerbSections(govern);
  const groups = [...new Set(sections.map((section) => section.group))];
  assert.deepEqual(groups, ['workspace', 'integrations', 'governance']);
  assert.ok(sections.some((section) => section.key === 'outils' && section.route === '/skills'));
  assert.ok(sections.some((section) => section.key === 'apps' && section.route === '/apps'));
  assert.equal(
    sections.find((section) => section.key === 'resources')?.route,
    '/resources',
  );
});

test('a member cannot see Apps du workspace in Administrer', () => {
  const govern = COCKPIT_VERBS.find((verb) => verb.key === 'govern')!;
  const asMember = cockpitVerbSections(govern, { isAdmin: false });
  assert.equal(asMember.some((section) => section.key === 'workspace_apps'), false);
  const asAdmin = cockpitVerbSections(govern, { isAdmin: true });
  assert.ok(asAdmin.some((section) => section.key === 'workspace_apps' && section.adminOnly));
});

test('/settings routes to workspace settings (not presets)', () => {
  const source = readFileSync(join(process.cwd(), 'src/app/app.routes.ts'), 'utf8');
  assert.match(source, /function workspaceSettingsRedirect\(/);
  assert.match(source, /path:\s*'settings'[\s\S]*?redirectTo:\s*workspaceSettingsRedirect/);
  assert.match(source, /\/workspace\/\$\{encodeURIComponent\(slug\)\}\/settings/);
  assert.doesNotMatch(source, /path:\s*'settings'[\s\S]*?redirectTo:\s*'presets'/);
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

  assert.deepEqual(HYPERVISOR_FACETS.map((item) => item.id), [
    'synthese',
    'registre',
    'couts',
    'bases',
    'decisions',
    'journal',
  ]);
  assert.equal(
    resolveNavLink({ facet: 'bases', capabilityId: 'cap-basis' }, {
      lens: 'hypervisor',
      ancestry: EMPTY_ANCESTRY,
      currentUrl: '/hypervisor',
    }).url,
    '/hypervisor?facet=bases&capabilityId=cap-basis',
  );
});


test('comparison invocation links retain their explicit Run instead of inherited baseline ancestry', () => {
  const link = resolveNavLink({type: 'skill_invocation', runId: 'candidate/run', ref: 'proof/1'}, {lens: 'operate', ancestry: {...EMPTY_ANCESTRY, runId: 'baseline', systemId: 'sys-1'},
    currentUrl: '/runs/baseline?campaign=comparison-1'});
  assert.equal(link.url, '/runs/candidate%2Frun/invocations/proof%2F1?systemId=sys-1');
  const context = navigationRouteContext(link.url);
  assert.equal(context.runId, 'candidate/run');
});

test('every literal [navLink] names a catalogue leaf or surface (a throw froze Impact)', () => {
  const root = join(process.cwd(), 'src/app');
  const leaves = new Set(AGENTIUM_SURFACE_LEAVES.map((leaf) => leaf.id));
  const surfaces = new Set(AGENTIUM_SURFACE_ROUTES.map((surface) => surface.id));
  const unknown: string[] = [];
  const walk = (dir: string): void => {
    for (const name of readdirSync(dir)) {
      const full = join(dir, name);
      if (statSync(full).isDirectory()) { walk(full); continue; }
      if (!/\.(ts|html)$/.test(name) || name.endsWith('.spec.ts')) continue;
      const text = readFileSync(full, 'utf8');
      for (const match of text.matchAll(/\[navLink\]="\{\s*(leaf|surface):\s*'([^']+)'/g)) {
        const known = match[1] === 'leaf' ? leaves : surfaces;
        if (!known.has(match[2]!)) unknown.push(`${relative(root, full)}: ${match[1]} '${match[2]}'`);
      }
    }
  };
  walk(root);
  assert.deepEqual(unknown, []);
});
