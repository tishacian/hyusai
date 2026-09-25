import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  DEFAULT_HYPERVISOR_VIEWS,
  moveStratumBlock,
  parseViewsPayload,
  replaceView,
  showsBlock,
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
  assert.deepEqual(parsed.views[1]?.strata.comprendre, ['monument', 'cadran', 'rivers', 'signal']);
  assert.deepEqual(parsed.views[1]?.strata.decider, []);
  assert.deepEqual(parsed.views[2]?.strata.comprendre, ['unites', 'couverture', 'decisions']);
  assert.equal(showsBlock(parsed.views[0]!, 'comprendre', 'unites'), false);
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

test('toggle and move keep the rest of the view intact', () => {
  const direction = DEFAULT_HYPERVISOR_VIEWS[0]!;
  const hidden = toggleStratumBlock(direction, 'comprendre', 'sankey');
  assert.equal(showsBlock(hidden, 'comprendre', 'sankey'), false);
  assert.equal(showsBlock(direction, 'comprendre', 'sankey'), true);
  const moved = moveStratumBlock(direction, 'comprendre', 'monument', 1);
  assert.equal(moved.strata.comprendre[1], 'monument');
  const cols = toggleRegisterColumn(direction, 'spark');
  assert.equal(cols.register_columns.includes('spark'), false);
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
