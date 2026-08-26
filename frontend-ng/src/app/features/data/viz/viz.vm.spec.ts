/**
 * The viz kit's numbers.
 *
 * These are what every chart on the data and model surfaces is drawn from, which
 * is why they are tested as arithmetic: a wrong domain or a wrong baseline is a
 * chart that lies rather than a chart that crashes.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  STAGGER_BUDGET_MS,
  STAGGER_STEP_MS,
  UNIT_DOMAIN,
  confusionShade,
  confusionView,
  curveDomain,
  curveFill,
  curveSeries,
  referenceSeries,
  revealFraction,
  staggerDelay,
  tokenAlpha,
} from './viz.vm';

// ---------------------------------------------------------------------------
// Curves
// ---------------------------------------------------------------------------

test('a curve with nothing to draw yields nothing rather than a stray dot', () => {
  assert.deepEqual(curveSeries([]), []);
  assert.deepEqual(curveSeries(undefined), []);
  assert.deepEqual(curveSeries([{ x: 0.5, y: 0.5 }]), []);
  // Non-finite samples are dropped before the count is judged, so a two-point
  // series with one bad sample is still nothing.
  assert.deepEqual(curveSeries([{ x: 0, y: 0 }, { x: Number.NaN, y: 1 }]), []);
  assert.deepEqual(
    curveSeries([
      { x: 0, y: 0 },
      { x: 1, y: 1 },
    ]),
    [
      { x: 0, y: 0 },
      { x: 1, y: 1 },
    ],
  );
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
});

test('a degenerate domain is padded instead of dividing by zero', () => {
  const domain = curveDomain([[{ x: 5, y: 5 }]]);
  assert.deepEqual(domain, { minX: 5, maxX: 6, minY: 5, maxY: 6 });
  assert.deepEqual(curveDomain([]), UNIT_DOMAIN);
  assert.deepEqual(curveDomain([[]]), UNIT_DOMAIN);
});

test('a ROC’s reference is the diagonal of the box it is drawn in', () => {
  assert.deepEqual(referenceSeries({ kind: 'diagonal' }), [
    { x: 0, y: 0 },
    { x: 1, y: 1 },
  ]);
  // In the target's own units the corners move with the domain, or the
  // "diagonal" would be a line through nowhere.
  assert.deepEqual(
    referenceSeries({ kind: 'diagonal' }, { minX: 10, maxX: 30, minY: 10, maxY: 30 }),
    [
      { x: 10, y: 10 },
      { x: 30, y: 30 },
    ],
  );
});

test('a prevalence level spans the plot, or is refused rather than clamped', () => {
  assert.deepEqual(referenceSeries({ kind: 'level', value: 0.04 }), [
    { x: 0, y: 0.04 },
    { x: 1, y: 0.04 },
  ]);
  // Outside the domain there is nowhere honest to draw it: a prevalence line
  // pinned to the floor would read as a real baseline of zero.
  for (const value of [1.5, -0.2, null, undefined, Number.NaN]) {
    assert.deepEqual(referenceSeries({ kind: 'level', value: value as number }), []);
  }
});

test('an identity reference is a series like any other, and is filtered like one', () => {
  assert.deepEqual(
    referenceSeries({
      kind: 'series',
      points: [
        { x: 10, y: 10 },
        { x: 30, y: 30 },
      ],
    }),
    [
      { x: 10, y: 10 },
      { x: 30, y: 30 },
    ],
  );
  assert.deepEqual(referenceSeries({ kind: 'series', points: [{ x: 1, y: 1 }] }), []);
  assert.deepEqual(referenceSeries({ kind: 'none' }), []);
});

test('a token becomes a colour a canvas can fill with', () => {
  // Hex, long and short, with and without an alpha digit pair.
  assert.equal(tokenAlpha('#7dd3fc', 0.18), 'rgba(125, 211, 252, 0.18)');
  assert.equal(tokenAlpha('#FFF', 0.5), 'rgba(255, 255, 255, 0.5)');
  assert.equal(tokenAlpha('#7dd3fc80', 1), 'rgba(125, 211, 252, 0.502)');
  // The token's own alpha multiplies rather than being replaced: a stroke that
  // is already 8% white must not come back opaque.
  assert.equal(tokenAlpha('rgba(255, 255, 255, 0.08)', 1), 'rgba(255, 255, 255, 0.08)');
  assert.equal(tokenAlpha('rgba(255, 255, 255, 0.5)', 0.5), 'rgba(255, 255, 255, 0.25)');
  assert.equal(tokenAlpha('rgb(0 0 0 / 50%)', 1), 'rgba(0, 0, 0, 0.5)');
});

test('a colour nothing can parse fills with nothing, not with everything', () => {
  // An area fill that silently went opaque would hide the curve above it, which
  // is a worse failure than an area fill that is missing.
  for (const unparseable of ['', 'oklch(70% 0.1 220)', 'var(--ck-accent)', '#12345']) {
    assert.equal(tokenAlpha(unparseable, 0.2), 'transparent');
  }
});

// ---------------------------------------------------------------------------
// Depth
// ---------------------------------------------------------------------------

test('the wash under a curve is spent against the line and none of it on the floor', () => {
  const stops = curveFill('#7dd3fc', 0.34);
  assert.deepEqual(
    stops.map((stop) => stop.offset),
    [0, 0.45, 1],
  );
  // The top of the plot carries the whole peak and the bottom carries nothing,
  // which is what makes the area read as light off the curve rather than as a
  // filled polygon with a soft edge.
  assert.equal(stops[0].color, 'rgba(125, 211, 252, 0.34)');
  assert.equal(stops[2].color, 'rgba(125, 211, 252, 0)');

  const alphas = stops.map((stop) => Number(/([\d.]+)\)$/.exec(stop.color)![1]));
  assert.deepEqual(alphas, [...alphas].sort((a, b) => b - a));
  // And the middle is well under half, or the falloff is a straight ramp and
  // the eye reads the midpoint as the fill.
  assert.ok(alphas[1] < alphas[0] / 2, `${alphas[1]} is not under half of ${alphas[0]}`);
});

test('a wash nothing can parse is no wash, not an opaque one', () => {
  // Same failure mode `tokenAlpha` guards: a fill that silently went solid
  // would hide the curve it sits under.
  for (const stop of curveFill('var(--ck-accent)')) {
    assert.equal(stop.color, 'transparent');
  }
  // A peak of zero is a legible request — draw no wash — and not an error.
  for (const stop of curveFill('#7dd3fc', 0)) {
    assert.match(stop.color, /, 0\)$/);
  }
});

test('a reveal starts closed, ends open, and never reverses', () => {
  assert.equal(revealFraction(0, 800), 0);
  assert.equal(revealFraction(800, 800), 1);
  // Past the end and before the start are both the nearest end of the wipe,
  // because a frame can arrive at either.
  assert.equal(revealFraction(4000, 800), 1);
  assert.equal(revealFraction(-50, 800), 0);

  const steps = [0, 100, 200, 400, 600, 800].map((at) => revealFraction(at, 800));
  assert.deepEqual(steps, [...steps].sort((a, b) => a - b));
  // Eased out: half the time has uncovered well over half the plot, so the
  // wipe hurries past the origin and settles where the curve flattens.
  assert.ok(revealFraction(400, 800) > 0.8, `${revealFraction(400, 800)} is not eased`);
});

test('a reveal with no time to run is already over', () => {
  // Which is how reduced motion is expressed: the caller passes zero rather
  // than the component keeping a second code path for it.
  for (const duration of [0, -1, Number.NaN]) {
    assert.equal(revealFraction(0, duration), 1);
  }
  // A frame whose clock produced nothing usable is the start of the wipe, not
  // a jump to the end: NaN would otherwise clip the plot to nothing at all.
  assert.equal(revealFraction(Number.NaN, 800), 0);
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

// ---------------------------------------------------------------------------
// Staggered entrances
// ---------------------------------------------------------------------------

test('a stagger a reader can follow, on a set of any size', () => {
  // The first item never waits: an entrance that begins with a pause reads as
  // a slow page rather than as an animation.
  assert.equal(staggerDelay(0, 4), 0);
  // A small set gets the full step, which is what makes the order visible.
  assert.equal(staggerDelay(1, 4), STAGGER_STEP_MS);
  assert.equal(staggerDelay(3, 4), 3 * STAGGER_STEP_MS);
});

test('a long list compresses its step instead of outstaying its welcome', () => {
  // 24 permutation importances at the full step would be 1.2s of waiting. The
  // whole set has one budget, however many rows the model reported.
  const last = staggerDelay(23, 24);
  assert.ok(last <= STAGGER_BUDGET_MS, `${last} is inside the budget`);
  assert.equal(last, STAGGER_BUDGET_MS);
  assert.ok(staggerDelay(1, 24) < STAGGER_STEP_MS);
});

test('a stagger only ever runs forwards', () => {
  for (const count of [1, 2, 5, 24, 200]) {
    const delays = Array.from({ length: count }, (_, index) => staggerDelay(index, count));
    assert.deepEqual(delays, [...delays].sort((a, b) => a - b));
    assert.ok(delays[delays.length - 1]! <= STAGGER_BUDGET_MS);
  }
});

test('an index past the end of its set waits no longer than the end does', () => {
  // The matrix asks for `row + column` against the number of diagonals, and a
  // caller that miscounts should get a late cell, never an unreachable one.
  assert.equal(staggerDelay(9, 3), staggerDelay(2, 3));
  assert.equal(staggerDelay(-4, 3), 0);
  assert.equal(staggerDelay(Number.NaN, 3), 0);
  assert.equal(staggerDelay(1, 0), 0);
});
