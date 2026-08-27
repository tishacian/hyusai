/**
 * The shared tabular rendering contract.
 *
 * These bars are the whole reason a dataset reads as data rather than as rows,
 * so their normalization is pinned here: a demo where one tall bucket flattens
 * every other column to an invisible sliver would be worse than no sparkline.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { DATA_EN, DATA_FR } from '@app/core/i18n/data.dict';
import { FLOW_FR } from '@app/core/i18n/flow.dict';

import {
  COLUMN_KIND_GLYPH,
  NUMERIC_COLUMN_KINDS,
  formatBytes,
  isNumericKind,
  nullPercent,
  profileBars,
  profileFacts,
  toggleColumnSelection,
  topValueBars,
  type TabularColumnStats,
} from './data-table.vm';

test('numeric columns draw their histogram, normalized to the tallest bucket', () => {
  const stats: TabularColumnStats = {
    kind: 'float',
    histogram: [
      { upper: 10, count: 5 },
      { upper: 20, count: 10 },
      { upper: 30, count: 0 },
    ],
  };

  const bars = profileBars(stats, true);

  assert.equal(bars.length, 3);
  assert.equal(bars[1].height, 100, 'the tallest bucket fills the sparkline');
  assert.equal(bars[0].height, 50, 'heights are relative, not absolute');
  // An empty bucket keeps a visible floor: a gap would read as a missing column.
  assert.equal(bars[2].height, 6);
  assert.equal(bars[0].title, '≤ 10 · 5');
});

test('categorical columns draw their top values instead of a histogram', () => {
  const stats: TabularColumnStats = {
    kind: 'string',
    top_values: [
      { value: 'monthly', count: 8 },
      { value: 'yearly', count: 2 },
      { value: null, count: 1 },
    ],
  };

  const bars = profileBars(stats, false, 'null');

  assert.deepEqual(
    bars.map((bar) => bar.title),
    ['monthly · 8', 'yearly · 2', 'null · 1'],
  );
  assert.equal(bars[0].height, 100);
  assert.equal(bars[1].height, 25);
});

test('a column with no profile draws nothing rather than a fake baseline', () => {
  assert.deepEqual(profileBars(null, true), []);
  assert.deepEqual(profileBars({}, true), []);
  assert.deepEqual(profileBars({ histogram: [] }, true), []);
  // Numeric column, but only categorical stats available (and vice versa).
  assert.deepEqual(profileBars({ top_values: [{ value: 'a', count: 1 }] }, true), []);
});

test('a histogram bin with no upper edge still labels its bucket', () => {
  const bars = profileBars({ histogram: [{ upper: null, count: 3 }] }, true);

  assert.equal(bars[0].title, '— · 3');
});

test('null ratios become whole percentages, and a clean column reports zero', () => {
  assert.equal(nullPercent({ null_ratio: 0.2534 }), 25);
  assert.equal(nullPercent({ null_ratio: 0 }), 0);
  assert.equal(nullPercent({}), 0);
  assert.equal(nullPercent(null), 0);
});

test('only integer and float count as numeric for alignment and histograms', () => {
  assert.ok(isNumericKind('integer'));
  assert.ok(isNumericKind('float'));
  assert.ok(!isNumericKind('boolean'));
  assert.ok(!isNumericKind('datetime'));
  assert.ok(!isNumericKind('string'));
  assert.ok(!isNumericKind(undefined));
  assert.deepEqual([...NUMERIC_COLUMN_KINDS], ['integer', 'float']);
});

test('every column kind has a header glyph so no column renders unlabelled', () => {
  for (const kind of [
    'integer',
    'float',
    'boolean',
    'datetime',
    'string',
    'other',
  ] as const) {
    assert.ok(COLUMN_KIND_GLYPH[kind], `${kind} has a glyph`);
  }
});

test('a numeric profile states counts, then range, then central tendency', () => {
  const stats: TabularColumnStats = {
    kind: 'float',
    nulls: 12,
    null_ratio: 0.0015,
    distinct: 402,
    min: 0.5,
    max: 99.5,
    mean: 42.25,
    std: 11.5,
  };

  const facts = profileFacts(stats, true, 8000);

  assert.deepEqual(
    facts.map((fact) => fact.key),
    ['rows', 'nulls', 'distinct', 'min', 'max', 'mean', 'std'],
  );
  assert.equal(facts[0].value, 8000);
  assert.equal(facts[1].ratio, 0.0015, 'the null count carries its share of rows');
  assert.equal(facts[6].value, 11.5);
});

test('a categorical profile leaves out the statistics that would be meaningless', () => {
  const facts = profileFacts(
    { kind: 'string', nulls: 0, distinct: 4, mean: 3, std: 1 },
    false,
  );

  // `mean` and `std` of a string column are an artefact, never a finding.
  assert.deepEqual(
    facts.map((fact) => fact.key),
    ['nulls', 'distinct'],
  );
});

test('a clean column still says so, because "no missing values" is a finding', () => {
  const facts = profileFacts({ kind: 'integer', nulls: 0 }, true);

  assert.deepEqual(facts, [{ key: 'nulls', value: 0, ratio: 0 }]);
});

test('a datetime column keeps its range without inventing an average', () => {
  const facts = profileFacts(
    { kind: 'datetime', nulls: 0, min: '2026-01-01', max: '2026-08-25' },
    false,
  );

  assert.deepEqual(
    facts.map((fact) => [fact.key, fact.value]),
    [
      ['nulls', 0],
      ['min', '2026-01-01'],
      ['max', '2026-08-25'],
    ],
  );
});

test('a column with no profile at all offers no facts to open', () => {
  assert.deepEqual(profileFacts(null, true, 8000), []);
  assert.deepEqual(profileFacts(undefined, false), []);
});

test('a row count is only stated when it is one', () => {
  assert.ok(!profileFacts({ nulls: 0 }, true, 0).some((fact) => fact.key === 'rows'));
  assert.ok(!profileFacts({ nulls: 0 }, true, null).some((fact) => fact.key === 'rows'));
});

test('top values rank widest first, relative to the most frequent one', () => {
  const bars = topValueBars({
    top_values: [
      { value: 'fiber', count: 300 },
      { value: 'dsl', count: 150 },
      { value: null, count: 3 },
    ],
  });

  assert.deepEqual(
    bars.map((bar) => [bar.label, bar.count, bar.width]),
    [
      ['fiber', 300, 100],
      ['dsl', 150, 50],
      // Floored, so a rare value is still a visible bar rather than nothing.
      ['null', 3, 2],
    ],
  );
});

test('a high-cardinality column still shows shape, not seven empty slivers', () => {
  // Every value covers ~1% of an 8k-row dataset: normalizing against the row
  // count would render this as nothing at all.
  const bars = topValueBars({
    top_values: [
      { value: 'a', count: 90 },
      { value: 'b', count: 45 },
    ],
  });

  assert.equal(bars[0].width, 100);
  assert.equal(bars[1].width, 50);
});

test('a numeric column has no top values, so its popover shows only figures', () => {
  assert.deepEqual(topValueBars({ histogram: [{ upper: 1, count: 4 }] }), []);
  assert.deepEqual(topValueBars(null), []);
});

test('byte sizes read as volumes, keeping a decimal only where it informs', () => {
  assert.equal(formatBytes(512, 'en'), '512 B');
  assert.equal(formatBytes(1536, 'en'), '1.5 kB');
  assert.equal(formatBytes(5 * 1024 * 1024, 'en'), '5.0 MB');
  // Past 10 units the decimal is noise, so it goes away.
  assert.equal(formatBytes(42 * 1024 * 1024, 'en'), '42 MB');
  assert.equal(formatBytes(3 * 1024 ** 4, 'en'), '3.0 TB');
  assert.equal(formatBytes(null, 'en'), '—');
  assert.equal(formatBytes(undefined, 'en'), '—');
});

test('a column click replaces, toggles or leaves the selection alone', () => {
  assert.deepEqual(toggleColumnSelection('single', [], 'churn'), ['churn']);
  assert.deepEqual(toggleColumnSelection('single', ['churn'], 'churn'), []);
  assert.deepEqual(toggleColumnSelection('single', ['churn'], 'region'), ['region']);
  assert.deepEqual(toggleColumnSelection('multi', ['a'], 'b'), ['a', 'b']);
  assert.deepEqual(toggleColumnSelection('multi', ['a', 'b'], 'a'), ['b']);
  assert.deepEqual(toggleColumnSelection('none', ['a'], 'b'), ['a']);
  assert.deepEqual(toggleColumnSelection('multi', ['a'], 'a', ['a']), ['a']);
});

test('the table states its own shape, so no caller can forget to', () => {
  // The plan's first UI bet is one table, and part of what it carries is a
  // "n rows · k columns" badge. It belongs to the component because it is a
  // property of the data rather than of the surface: fifty rows of preview look
  // identical whether they came from eight thousand or from fifty-one, and a
  // caller that forgets to say which leaves the reader guessing at the scale.
  const source = readFileSync(
    join(process.cwd(), 'src/app/shared/ui/data-table.component.ts'),
    'utf8',
  );
  assert.match(source, /data-testid="table-shape"/);
  assert.match(source, /data-testid="column-select"/);
  assert.match(source, /'data\.table\.rows_columns'/);
  assert.match(source, /'data\.table\.duration_rows'/);
  assert.match(source, /readonly shape = computed/);
  // The whole dataset when the caller knows it, the rows on screen otherwise:
  // a preview of a preview has no other number to give.
  assert.match(source, /total !== null && total >= 0 \? total : this\.rows\(\)\.length/);
  assert.ok(DATA_FR['data.table.rows_columns'], 'the badge has FR copy');
  assert.ok(DATA_EN['data.table.rows_columns'], 'the badge has EN copy');
  assert.ok(DATA_FR['data.table.duration_rows'], 'a timed result unifies duration and rows');
  assert.ok(DATA_EN['data.table.duration_rows'], 'the timed badge has EN copy');

  // And no caller states it a second time: two row counts in one caption bar is
  // exactly the drift the shared component exists to prevent.
  for (const [name, key] of [
    ['data-view', 'data.detail.preview.caption'],
    ['transform workshop', 'flow.transform.result.caption'],
  ] as const) {
    const copy = (DATA_FR as Record<string, string>)[key] ?? FLOW_FR[key];
    assert.ok(copy, `${key} exists`);
    assert.doesNotMatch(copy, /\{rows\}|\{columns\}|\{total\}/, `${name} repeats the shape`);
  }
});
