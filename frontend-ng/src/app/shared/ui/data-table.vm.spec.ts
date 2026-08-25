/**
 * The shared tabular rendering contract.
 *
 * These bars are the whole reason a dataset reads as data rather than as rows,
 * so their normalization is pinned here: a demo where one tall bucket flattens
 * every other column to an invisible sliver would be worse than no sparkline.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  COLUMN_KIND_GLYPH,
  NUMERIC_COLUMN_KINDS,
  formatBytes,
  isNumericKind,
  nullPercent,
  profileBars,
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
