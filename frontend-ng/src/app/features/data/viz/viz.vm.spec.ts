/**
 * The viz kit's geometry.
 *
 * These are the arithmetic every chart on the data and model surfaces is drawn
 * from, which is why they are tested as arithmetic: an SVG path is a string, and
 * a wrong one is a chart that lies rather than a chart that crashes.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  UNIT_DOMAIN,
  confusionShade,
  confusionView,
  curveArea,
  curveDomain,
  curvePath,
  referenceY,
} from './viz.vm';

// ---------------------------------------------------------------------------
// Curves
// ---------------------------------------------------------------------------

const BOX = { width: 100, height: 50 };

test('a curve is drawn with y flipped, so a better model climbs', () => {
  const path = curvePath(
    [
      { x: 0, y: 0 },
      { x: 0.5, y: 1 },
      { x: 1, y: 1 },
    ],
    BOX,
    UNIT_DOMAIN,
  );
  assert.equal(path, 'M0,50 L50,0 L100,0');
});

test('a curve with nothing to draw yields no path rather than a stray dot', () => {
  assert.equal(curvePath([], BOX), '');
  assert.equal(curvePath(undefined, BOX), '');
  assert.equal(curvePath([{ x: 0.5, y: 0.5 }], BOX), '');
  // Non-finite samples are dropped before the count is judged.
  assert.equal(curvePath([{ x: 0, y: 0 }, { x: Number.NaN, y: 1 }], BOX), '');
});

test('a regression fit is scaled to the target’s own units, not the unit square', () => {
  const fit = [
    { x: 10, y: 12 },
    { x: 30, y: 28 },
  ];
  const ideal = [
    { x: 10, y: 10 },
    { x: 30, y: 30 },
  ];
  const domain = curveDomain([fit, ideal]);
  assert.deepEqual(domain, { minX: 10, maxX: 30, minY: 10, maxY: 30 });
  // Both series share the domain, so the diagonal really is the diagonal.
  assert.equal(curvePath(ideal, BOX, domain), 'M0,50 L100,0');
});

test('a degenerate domain is padded instead of dividing by zero', () => {
  const domain = curveDomain([[{ x: 5, y: 5 }]]);
  assert.deepEqual(domain, { minX: 5, maxX: 6, minY: 5, maxY: 6 });
  assert.deepEqual(curveDomain([]), UNIT_DOMAIN);
  assert.deepEqual(curveDomain([[]]), UNIT_DOMAIN);
});

test('the filled area closes on the baseline, under the curve and nowhere else', () => {
  // The fill is what makes two ROCs comparable at a glance, so the closing
  // segments have to follow the curve's own x range: closing at 0 and at the
  // box width would fill under a curve that starts halfway across.
  const area = curveArea(
    [
      { x: 0.2, y: 0 },
      { x: 0.6, y: 1 },
    ],
    BOX,
  );
  assert.equal(area, 'M20,50 L60,0 L60,50 L20,50 Z');
  // No line, no area — not an area over an empty path.
  assert.equal(curveArea([{ x: 0, y: 0 }], BOX), '');
  assert.equal(curveArea(undefined, BOX), '');
});

test('a reference level lands in the box, or is refused', () => {
  assert.equal(referenceY(0, BOX), 50);
  assert.equal(referenceY(1, BOX), 0);
  assert.equal(referenceY(0.04, BOX), 48);
  // Outside the domain there is nowhere honest to draw it: a prevalence line
  // pinned to the floor would read as a real baseline of zero.
  assert.equal(referenceY(1.5, BOX), null);
  assert.equal(referenceY(-0.2, BOX), null);
  assert.equal(referenceY(null, BOX), null);
  assert.equal(referenceY(undefined, BOX), null);
  assert.equal(referenceY(Number.NaN, BOX), null);
  // In the target's own units, for the regression fit.
  assert.equal(referenceY(20, BOX, { minX: 0, maxX: 1, minY: 10, maxY: 30 }), 25);
});

// ---------------------------------------------------------------------------
// Confusion matrix
// ---------------------------------------------------------------------------

test('the confusion matrix is shaded per actual row, not per grand total', () => {
  // 96 loyal / 4 churners: the interesting cell is the one that is 50% of a
  // tiny row and 1% of the table. Row-normalizing is what keeps it visible.
  const view = confusionView({
    labels: ['loyal', 'churn'],
    matrix: [
      [94, 2],
      [2, 2],
    ],
  });
  assert.ok(view);
  assert.equal(view!.total, 100);
  assert.equal(view!.rows[1].total, 4);
  const missed = view!.rows[1].cells[0];
  assert.equal(missed.count, 2);
  assert.equal(missed.share, 0.5);
  assert.equal(missed.correct, false);
  assert.equal(view!.rows[1].cells[1].correct, true);
});

test('a malformed or absent matrix renders nothing at all', () => {
  assert.equal(confusionView(null), null);
  assert.equal(confusionView(undefined), null);
  assert.equal(confusionView({ labels: [], matrix: [] }), null);
  assert.equal(confusionView({ labels: ['a', 'b'], matrix: [[1, 2]] }), null);
});

test('an empty row divides by nothing and stays at zero', () => {
  const view = confusionView({ labels: ['a', 'b'], matrix: [[0, 0], [1, 1]] });
  assert.equal(view!.rows[0].cells[0].share, 0);
});

test('a cell that holds anything is tinted, and the diagonal is the green one', () => {
  // A rare confusion is still a confusion. Without the floor, a cell reading
  // "3" out of 4000 gets an alpha near zero and looks like an empty cell —
  // which is the one reading mistake this grid must not invite.
  const rare = confusionShade(0.001, false);
  assert.match(rare, /--ck-signal-neg/);
  assert.match(rare, /8%/);

  assert.match(confusionShade(1, true), /--ck-signal-pos/);
  // Truly empty stays truly empty.
  assert.match(confusionShade(0, false), /0%/);
  // And the scale is monotone between the two, or the grid would not read as
  // one quantity at different strengths.
  const shares = [0.1, 0.3, 0.6, 1];
  const alphas = shares.map((share) => Number(/ (\d+)%/.exec(confusionShade(share, true))![1]));
  assert.deepEqual(alphas, [...alphas].sort((a, b) => a - b));
});
