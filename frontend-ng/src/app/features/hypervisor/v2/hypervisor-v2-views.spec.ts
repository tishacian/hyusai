import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  DEFAULT_HYPERVISOR_VIEWS,
  IMPACT_GENERIC_VIEWS,
  IMPACT_VIEW_IDS,
  moveStratumBlock,
  normalizeBlockRef,
  normalizeView,
  parseImpactViewQuery,
  parseViewsPayload,
  removeStratumBlock,
  replaceView,
  serializeViewsForWrite,
  showsBlock,
  stratumBlockTypes,
  toggleRegisterColumn,
  toggleStratumBlock,
  viewDenominator,
  viewPeriod,
} from './hypervisor-v2-views';
import {
  navigationZoneSurfaceUrl,
  resolveNavLink,
} from '@app/core/navigation.catalog';

test('parseViewsPayload falls back to Direction / Operations / Conformite defaults', () => {
  const parsed = parseViewsPayload(null);
  assert.equal(parsed.can_edit, false);
  assert.deepEqual(parsed.views.map((view) => view.id), ['direction', 'operations', 'conformite']);
  assert.equal(viewPeriod(parsed.views[0]), '90d');
  assert.equal(viewDenominator(parsed.views[1]), 'runs');
  assert.equal(viewDenominator(parsed.views[2]), 'runs');
  assert.deepEqual(stratumBlockTypes(parsed.views[1]!, 'comprendre'), ['monument', 'cadran', 'rivers', 'signal']);
  assert.deepEqual(stratumBlockTypes(parsed.views[1]!, 'decider'), []);
  assert.deepEqual(stratumBlockTypes(parsed.views[2]!, 'comprendre'), ['unites', 'couverture', 'decisions']);
  assert.equal(showsBlock(parsed.views[0]!, 'comprendre', 'unites'), false);
  assert.equal(parsed.views[0]!.schema_version, 2);
  assert.equal(parsed.views[0]!.strata.comprendre[0]?.type, 'monument');
});

test('legacy units denominator is an alias of runs', () => {
  const parsed = parseViewsPayload({
    can_edit: false,
    views: [{
      ...DEFAULT_HYPERVISOR_VIEWS[1]!,
      denominator: 'units' as unknown as 'runs',
    }],
  });
  assert.equal(viewDenominator(parsed.views[0]), 'runs');
});

test('form 1 string strata dual-read into typed block refs', () => {
  const parsed = parseViewsPayload({
    can_edit: true,
    views: [{
      id: 'legacy',
      label: 'Legacy',
      denominator: 'hours',
      period: '30d',
      strata: {
        comprendre: ['monument', 'sankey'],
        detailler: ['registre'],
        decider: ['decisions'],
      },
      register_columns: ['unit'],
      sort: 'name',
    }],
  });
  const view = parsed.views[0]!;
  assert.equal(view.schema_version, 2);
  assert.deepEqual(stratumBlockTypes(view, 'comprendre'), ['monument', 'sankey']);
  assert.equal(view.strata.comprendre[0]?.settings && Object.keys(view.strata.comprendre[0].settings).length, 0);
  assert.equal(showsBlock(view, 'comprendre', 'sankey'), true);
  assert.equal(showsBlock(view, 'detailler', 'registre'), true);
});

test('form 2 object strata dual-read preserves settings', () => {
  const parsed = parseViewsPayload({
    can_edit: false,
    views: [{
      id: 'agenda',
      label: 'Agenda',
      denominator: 'hours',
      period: '30d',
      schema_version: 2,
      strata: {
        comprendre: [
          { type: 'echeancier', settings: { mode: 'liste' }, width: 'full' },
          { type: 'ordre_du_jour', source: 'sys-1', title: 'Prep', settings: { mode: 'prep' } },
        ],
        detailler: [],
        decider: [{ type: 'decisions', settings: {} }],
      },
      register_columns: [],
      sort: 'name',
    }],
  });
  const view = parsed.views[0]!;
  assert.equal(view.strata.comprendre[0]?.type, 'echeancier');
  assert.equal(view.strata.comprendre[0]?.settings['mode'], 'liste');
  assert.equal(view.strata.comprendre[0]?.width, 'full');
  assert.equal(view.strata.comprendre[1]?.source, 'sys-1');
  assert.equal(view.strata.comprendre[1]?.title, 'Prep');
});

test('serializeViewsForWrite emits form 2 only', () => {
  const form1 = normalizeView({
    id: 'ops',
    label: 'Ops',
    strata: { comprendre: ['monument', 'signal'], detailler: [], decider: [] },
  });
  const written = serializeViewsForWrite([form1]);
  assert.equal(written[0]?.schema_version, 2);
  assert.equal(typeof written[0]?.strata.comprendre[0], 'object');
  assert.equal(written[0]?.strata.comprendre[0]?.type, 'monument');
  assert.ok(!Array.isArray(written[0]?.strata.comprendre) || typeof written[0]!.strata.comprendre[0] !== 'string');
});

test('toggle move and remove keep the rest of the view intact', () => {
  const direction = DEFAULT_HYPERVISOR_VIEWS[0]!;
  const hidden = toggleStratumBlock(direction, 'comprendre', 'sankey');
  assert.equal(showsBlock(hidden, 'comprendre', 'sankey'), false);
  assert.equal(showsBlock(direction, 'comprendre', 'sankey'), true);
  const moved = moveStratumBlock(direction, 'comprendre', 'monument', 1);
  assert.equal(moved.strata.comprendre[1]?.type, 'monument');
  const removed = removeStratumBlock(direction, 'comprendre', 'rivers');
  assert.equal(showsBlock(removed, 'comprendre', 'rivers'), false);
  assert.equal(showsBlock(direction, 'comprendre', 'rivers'), true);
  const cols = toggleRegisterColumn(direction, 'spark');
  assert.equal(cols.register_columns.includes('spark'), false);
});

test('normalizeBlockRef accepts string and object forms', () => {
  assert.deepEqual(normalizeBlockRef('carte'), { type: 'carte', settings: {} });
  assert.equal(normalizeBlockRef(''), null);
  assert.equal(normalizeBlockRef({ type: 'flux', settings: { window: '7d' } })?.settings['window'], '7d');
});

test('IMPACT_GENERIC_VIEWS cover the five named views from six block types', () => {
  assert.deepEqual(IMPACT_VIEW_IDS.slice(), ['agenda', 'veille', 'securite', 'reunion', 'carte']);
  assert.equal(IMPACT_GENERIC_VIEWS.length, 5);
  for (const view of IMPACT_GENERIC_VIEWS) {
    assert.equal(view.schema_version, 2);
    const types = [
      ...stratumBlockTypes(view, 'comprendre'),
      ...stratumBlockTypes(view, 'detailler'),
      ...stratumBlockTypes(view, 'decider'),
    ];
    for (const type of types) {
      assert.ok(
        ['echeancier', 'flux', 'carte', 'alertes', 'ordre_du_jour', 'indicateurs', 'decisions'].includes(type),
        `unexpected block ${type} in ${view.id}`,
      );
    }
  }
  assert.deepEqual(stratumBlockTypes(IMPACT_GENERIC_VIEWS[0]!, 'comprendre'), ['echeancier', 'ordre_du_jour']);
  assert.deepEqual(stratumBlockTypes(IMPACT_GENERIC_VIEWS[1]!, 'comprendre'), ['indicateurs', 'flux', 'alertes']);
  assert.deepEqual(stratumBlockTypes(IMPACT_GENERIC_VIEWS[2]!, 'comprendre'), ['carte', 'alertes', 'echeancier']);
  assert.deepEqual(stratumBlockTypes(IMPACT_GENERIC_VIEWS[3]!, 'comprendre'), ['echeancier', 'ordre_du_jour']);
  assert.deepEqual(stratumBlockTypes(IMPACT_GENERIC_VIEWS[4]!, 'comprendre'), ['indicateurs', 'carte', 'alertes']);
});

test('parseImpactViewQuery accepts the five Impact views', () => {
  assert.equal(parseImpactViewQuery('agenda'), 'agenda');
  assert.equal(parseImpactViewQuery('Veille'), 'veille');
  assert.equal(parseImpactViewQuery('securite'), 'securite');
  assert.equal(parseImpactViewQuery('reunion'), 'reunion');
  assert.equal(parseImpactViewQuery('carte'), 'carte');
  assert.equal(parseImpactViewQuery('direction'), null);
  assert.equal(parseImpactViewQuery(null), null);
});

test('replaceView is a full-list replace of one id', () => {
  const views = DEFAULT_HYPERVISOR_VIEWS.map((view) => ({ ...view }));
  const next = replaceView(views, {
    ...views[0]!,
    denominator: 'value',
    period: '30d',
  });
  assert.equal(next[0]?.denominator, 'value');
  assert.equal(next[0]?.period, '30d');
  assert.equal(next[1]?.id, 'operations');
});

test('?theme=presentation survives an Impact facet change (replaceUrl)', () => {
  const currentUrl = '/hypervisor?theme=presentation&facet=synthese';
  const resolved = resolveNavLink(
    { facet: 'decisions' },
    {
      lens: 'hypervisor',
      ancestry: {
        capabilityId: null,
        systemId: null,
        runId: null,
        skillInvocationId: null,
        skillRef: null,
      },
      currentUrl,
    },
  );
  assert.equal(resolved.replaceUrl, true);
  assert.match(resolved.url, /theme=presentation/);
  assert.match(resolved.url, /facet=decisions/);
});

test('Impact sommaire links keep theme within the zone and drop it on zone change', () => {
  const section = {
    key: 'decisions' as const,
    label: 'Décisions',
    glyph: 'focus' as const,
    surfaceId: 'hypervisor',
    route: '/hypervisor',
    scopeType: 'surface' as const,
    ancestryAware: false,
    facet: 'decisions',
  };
  assert.match(
    navigationZoneSurfaceUrl(section, 'hypervisor', '/hypervisor?theme=presentation'),
    /theme=presentation/,
  );
  const operate = {
    key: 'runs' as const,
    label: 'Runs',
    glyph: 'play' as const,
    surfaceId: 'runs',
    route: '/runs',
    scopeType: 'surface' as const,
    ancestryAware: false,
  };
  assert.equal(
    navigationZoneSurfaceUrl(operate, 'operate', '/hypervisor?theme=presentation'),
    '/runs',
  );
});
