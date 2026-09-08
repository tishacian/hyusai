import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  STALE_AFTER_DAYS,
  buildCalendar,
  calendarTicks,
  foldFacts,
  hasHoursBasis,
  initialsFor,
  isOutsideDenominator,
  isoWeek,
  orderStreams,
  projectSeries,
  sortRegisterRows,
  weekSpark,
  type HypervisorRegisterRow,
  type HypervisorSeriesResponse,
  type HypervisorSeriesSystem,
  type SeriesFact,
  type ValueBasis,
} from './hypervisor-v2-series';

const DECLARED: ValueBasis = {
  unit: 'brief',
  hours_per_unit: 1.25,
  value_per_unit: 40,
  currency: 'EUR',
  declared_by: 'ada@example.com',
  declared_at: '2026-09-01T00:00:00',
  status: 'declared',
  note: null,
};

const MEASURED: ValueBasis = {
  ...DECLARED,
  status: 'measured',
  hours_per_unit: 2,
  value_per_unit: 10,
};

function fact(state: SeriesFact['state'], value: number | null = null, unit?: string): SeriesFact {
  return unit ? { state, value, unit } : { state, value };
}

function system(partial: Partial<HypervisorSeriesSystem> & Pick<HypervisorSeriesSystem, 'system_id' | 'name'>): HypervisorSeriesSystem {
  return {
    capability_id: 'cap-1',
    output_unit: 'brief',
    value_basis: DECLARED,
    days_since_last_run: fact('available', 1),
    buckets: [],
    ...partial,
  };
}

function day(
  date: string,
  overrides: Partial<HypervisorSeriesSystem['buckets'][number]> = {},
): HypervisorSeriesSystem['buckets'][number] {
  return {
    date,
    runs: fact('available', 1),
    outcomes: fact('available', 1, 'brief'),
    cost: fact('available', 2.5),
    hours: fact('available', 1.25),
    value_declared: fact('available', 40),
    ...overrides,
  };
}

const WINDOW: HypervisorSeriesResponse = {
  window: '30d',
  from: '2026-09-01T00:00:00',
  to: '2026-09-08T12:00:00',
  systems: [
    system({
      system_id: 'sys-declared',
      name: 'Tender Response Analyst',
      buckets: [day('2026-09-02'), day('2026-09-05', { hours: fact('available', 2.5), value_declared: fact('available', 80) })],
    }),
    system({
      system_id: 'sys-bare',
      name: 'Contract Risk',
      value_basis: null,
      days_since_last_run: fact('available', 12),
      buckets: [
        day('2026-09-03', {
          hours: fact('not_configured', null),
          value_declared: fact('not_configured', null),
          cost: fact('not_measured', null),
        }),
      ],
    }),
    system({
      system_id: 'sys-measured',
      name: 'PR to PO',
      value_basis: MEASURED,
      days_since_last_run: fact('available', 0),
      buckets: [day('2026-09-02', { hours: fact('available', 2), value_declared: fact('available', 10), cost: fact('available', 1) })],
    }),
  ],
};

test('builds a UTC calendar from naive from/to and does not pad missing days', () => {
  assert.deepEqual(buildCalendar('2026-09-01T00:00:00', '2026-09-03T18:00:00'), [
    '2026-09-01',
    '2026-09-02',
    '2026-09-03',
  ]);
});

test('joins sparse buckets by date and never treats absence as not_configured zero', () => {
  const view = projectSeries(WINDOW, 'hours');
  assert.equal(view.dates.length, 8);
  assert.equal(view.dates[0], '2026-09-01');
  assert.equal(view.days[0]?.measured, 0);
  assert.equal(view.days[0]?.declared, 0);
  assert.equal(view.days[1]?.declared, 1.25);
  assert.equal(view.days[1]?.measured, 2);
  assert.equal(view.weekendStarts.includes(4), true, '2026-09-05 is Saturday');
  const bare = view.register.find((row) => row.systemId === 'sys-bare');
  assert.equal(bare?.hours.state, 'not_configured');
  assert.equal(bare?.hours.value, null);
  assert.equal(bare?.cost.state, 'not_measured');
  assert.equal(bare?.cost.value, null);
  assert.equal(bare?.outsideDenominator, true);
});

test('partitions hors-denominateur on hours and keeps native units in-denominator', () => {
  const hours = projectSeries(WINDOW, 'hours');
  assert.deepEqual(hours.outside.map((row) => row.systemId), ['sys-bare']);
  assert.equal(hours.sankey.some((row) => row.systemId === 'sys-bare' && row.outsideDenominator), true);
  const units = projectSeries(WINDOW, 'units');
  assert.equal(units.outside.length, 0);
  assert.equal(units.register.find((row) => row.systemId === 'sys-bare')?.outsideDenominator, false);
});

test('picks the peak day from measured+declared and marks stale systems', () => {
  const view = projectSeries(WINDOW, 'hours');
  assert.equal(view.peak?.date, '2026-09-02');
  assert.equal(view.peak?.total, 3.25);
  assert.equal(view.peak?.measured, 2);
  assert.equal(view.peak?.declared, 1.25);
  assert.equal(view.peak?.runs, 2, 'runs of in-denominator systems on the peak day');
  assert.equal(view.peak?.systems, 2);
  assert.equal(view.days[view.peak!.index]?.runs, view.peak?.runs);
  assert.equal(view.days[view.peak!.index]?.systems, view.peak?.systems);
  assert.deepEqual(view.staleSystemIds, ['sys-bare']);
  assert.equal(STALE_AFTER_DAYS, 7);
});

test('sankey widths are run counts and outside systems keep their native outcome', () => {
  const view = projectSeries(WINDOW, 'hours');
  const declared = view.sankey.find((row) => row.systemId === 'sys-declared');
  assert.equal(declared?.runs, 2);
  assert.equal(declared?.outsideDenominator, false);
  const bare = view.sankey.find((row) => row.systemId === 'sys-bare');
  assert.equal(bare?.outsideDenominator, true);
  assert.equal(bare?.outcomes.state, 'available');
  assert.equal(bare?.outcomes.value, 1);
  assert.equal(bare?.outputUnit, 'brief');
});

test('rivers stack measured first, then declared by weight with alternating teal tones', () => {
  const view = projectSeries(WINDOW, 'hours');
  assert.deepEqual(view.streams.map((row) => row.systemId), ['sys-measured', 'sys-declared']);
  assert.deepEqual(view.streams.map((row) => row.tone), ['ink', 'declared']);
  const ordered = orderStreams([
    { systemId: 'a', label: 'A', values: [1], total: 1, tone: 'ink', basisStatus: 'declared' },
    { systemId: 'b', label: 'B', values: [5], total: 5, tone: 'ink', basisStatus: 'declared' },
    { systemId: 'c', label: 'C', values: [2], total: 2, tone: 'ink', basisStatus: 'measured' },
  ]);
  assert.deepEqual(ordered.map((row) => `${row.systemId}:${row.tone}`), ['c:ink', 'b:declared', 'a:declared-soft']);
});

test('calendar ticks carry range bounds and ISO weeks without crowding the end', () => {
  const dates = buildCalendar('2026-08-09', '2026-09-07');
  const ticks = calendarTicks(dates);
  assert.deepEqual(ticks.map((tick) => [tick.index, tick.kind]), [
    [0, 'start'],
    [7, 'week'],
    [14, 'week'],
    [21, 'week'],
    [29, 'end'],
  ]);
  assert.equal(ticks[1]?.date, '2026-08-16');
  assert.equal(ticks[1]?.isoWeek, 33);
  assert.equal(isoWeek('2026-01-01'), 1);
  assert.equal(isoWeek('2026-12-31'), 53);
  assert.equal(calendarTicks(['2026-09-01']).length, 1);
});

test('week spark collapses the calendar from the end without fabricating cost', () => {
  assert.deepEqual(weekSpark([1, 1, 1, 1, 1, 1, 1, 2]), [1, 8]);
  const view = projectSeries(WINDOW, 'hours');
  const declared = view.register.find((row) => row.systemId === 'sys-declared');
  assert.ok((declared?.weekSpark.length ?? 0) >= 2);
  assert.equal(declared?.cost.state, 'available');
  assert.equal(declared?.cost.value, 5);
});

test('foldFacts never returns a fabricated zero for a non-available fact', () => {
  assert.deepEqual(foldFacts([fact('not_configured', null), fact('not_measured', null)]), {
    state: 'not_configured',
    value: null,
  });
  assert.deepEqual(foldFacts([fact('available', 0), fact('not_measured', null)]), {
    state: 'available',
    value: 0,
  });
});

test('sorts register rows with null facts last', () => {
  const rows = [
    { name: 'B', valueDeclared: fact('not_configured', null), cost: fact('available', 1), daysSinceLastRun: fact('available', 2) },
    { name: 'A', valueDeclared: fact('available', 3), cost: fact('available', 1), daysSinceLastRun: fact('available', 9) },
  ] as HypervisorRegisterRow[];
  assert.deepEqual(sortRegisterRows(rows, 'value').map((row) => row.name), ['A', 'B']);
  assert.deepEqual(sortRegisterRows(rows, 'name').map((row) => row.name), ['A', 'B']);
  assert.deepEqual(sortRegisterRows(rows, 'days_since_last_run').map((row) => row.name), ['A', 'B']);
});

test('basis helpers treat status none as unusable', () => {
  assert.equal(hasHoursBasis({ ...DECLARED, status: 'none' }), false);
  assert.equal(isOutsideDenominator({ value_basis: null }, 'hours'), true);
  assert.equal(isOutsideDenominator({ value_basis: DECLARED }, 'units'), false);
  assert.equal(initialsFor('Tender Response Analyst'), 'TR');
});

test('ratio stays unset when cost is not measured', () => {
  const view = projectSeries({
    ...WINDOW,
    systems: [system({
      system_id: 'sys-nocost',
      name: 'No Cost',
      buckets: [day('2026-09-02', { cost: fact('not_measured', null) })],
    })],
  }, 'hours');
  assert.equal(view.costTotal.state, 'not_measured');
  assert.equal(view.costTotal.value, null);
  assert.equal(view.ratio.state, 'not_measured');
  assert.equal(view.ratio.value, null);
});
