import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  accumulateStackedSeries,
  cubicSmoothAreaPath,
  cubicSmoothPath,
  radialDayAngle,
  radialPoint,
  radialSpokeEndpoints,
  radialSpokeLength,
  sankeyRibbonPath,
} from './svg-path';

test('cubicSmoothPath uses horizontal midpoints between consecutive points', () => {
  assert.equal(cubicSmoothPath([]), '');
  assert.equal(cubicSmoothPath([{ x: 3, y: 4 }]), 'M3,4');
  assert.equal(
    cubicSmoothPath([
      { x: 0, y: 0 },
      { x: 10, y: 10 },
    ]),
    'M0,0C5,0 5,10 10,10',
  );
  assert.equal(
    cubicSmoothPath([
      { x: 0, y: 8 },
      { x: 10, y: 2 },
      { x: 20, y: 6 },
    ]),
    'M0,8C5,8 5,2 10,2C15,2 15,6 20,6',
  );
});

test('cubicSmoothAreaPath closes to a lower band or a baseline', () => {
  const upper = [
    { x: 0, y: 4 },
    { x: 10, y: 1 },
  ];
  const lower = [
    { x: 0, y: 8 },
    { x: 10, y: 8 },
  ];
  assert.equal(cubicSmoothAreaPath([{ x: 0, y: 1 }]), '');
  assert.equal(cubicSmoothAreaPath(upper, lower), 'M0,4C5,4 5,1 10,1L10,8C5,8 5,8 0,8Z');
  assert.equal(cubicSmoothAreaPath(upper, null, 12), 'M0,4C5,4 5,1 10,1L10,12L0,12Z');
});

test('sankeyRibbonPath is a cubic band between two node segments', () => {
  assert.equal(
    sankeyRibbonPath({ x: 0, y: 10, height: 20 }, { x: 100, y: 30, height: 20 }),
    'M0,10C50,10 50,30 100,30L100,50C50,50 50,30 0,30Z',
  );
});

test('radial spoke math matches the approved 30-day clock', () => {
  assert.equal(radialDayAngle(0), -Math.PI / 2);
  assert.equal(radialDayAngle(15, 30), Math.PI / 2);
  assert.equal(radialPoint(0, 0, 10, 0).x, 10);
  assert.ok(Math.abs(radialPoint(0, 0, 10, 0).y) < 1e-10);
  assert.ok(Math.abs(radialPoint(0, 0, 10, Math.PI / 2).x) < 1e-10);
  assert.equal(radialPoint(0, 0, 10, Math.PI / 2).y, 10);

  assert.equal(radialSpokeLength(71, 71, 62, 156), 94);
  assert.equal(radialSpokeLength(0, 71, 62, 156), 0);
  assert.equal(radialSpokeLength(-4, 0, 62, 156), 0);

  const ends = radialSpokeEndpoints({
    cx: 180,
    cy: 180,
    angle: radialDayAngle(0),
    innerRadius: 62,
    length: 94,
    measuredShare: 0.45,
  });
  assert.equal(ends.start.x, 180);
  assert.equal(ends.start.y, 115);
  assert.ok(Math.abs(ends.mid.y - (180 - (62 + 94 * 0.45))) < 1e-10);
  assert.equal(ends.end.y, 24);
});

test('accumulateStackedSeries builds lower and upper bands per series', () => {
  assert.deepEqual(accumulateStackedSeries([]), []);
  assert.deepEqual(accumulateStackedSeries([[1, 2], [3, 4]]), [
    { lower: [0, 0], upper: [1, 2] },
    { lower: [1, 2], upper: [4, 6] },
  ]);
  assert.deepEqual(accumulateStackedSeries([[1], [2, 3, 4]]), [
    { lower: [0, 0, 0], upper: [1, 0, 0] },
    { lower: [1, 0, 0], upper: [3, 3, 4] },
  ]);
  assert.deepEqual(accumulateStackedSeries([[Number.NaN, 2]]), [
    { lower: [0, 0], upper: [0, 2] },
  ]);
});
