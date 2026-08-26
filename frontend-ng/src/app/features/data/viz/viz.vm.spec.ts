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
  UNIT_DOMAIN,
  confusionShade,
  confusionView,
  curveDomain,
  curveSeries,
  referenceSeries,
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
