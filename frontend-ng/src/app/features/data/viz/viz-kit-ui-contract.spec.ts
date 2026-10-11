/**
 * UI contract of the viz kit's DOM charts — the bar list and the confusion
 * matrix — asserted against the component sources (same technique as
 * `flow-transform-ui-contract.spec.ts`).
 *
 * The arithmetic these two draw from is tested in `viz.vm.spec.ts`. What is
 * pinned here is the drawing, because that is what the evidence panel is judged
 * on and it lives in a template and a stylesheet where a type checker has no
 * opinion: a fill that lost its gradient, a stagger that lost its delay, or an
 * animation that ignores a reader who asked for less motion are all silent
 * regressions.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

function source(name: string): string {
  return readFileSync(join(process.cwd(), 'src/app/features/data/viz', name), 'utf8');
}

function modelCard(): string {
  return readFileSync(
    join(process.cwd(), 'src/app/features/models/model-view.component.ts'),
    'utf8',
  );
}

const BARS = source('bar-list.component.ts');
const MATRIX = source('confusion-matrix.component.ts');
const CURVE = source('curve-chart.component.ts');
const CARD = modelCard();

test('a bar is a direction, not a rectangle', () => {
  // Two stops of one colour, so the eye is carried along the bar to its tip,
  // plus the ring and the glow that put it on the track instead of in it.
  assert.match(BARS, /linear-gradient\(\s*90deg/);
  assert.match(BARS, /--viz-bar, var\(--ck-accent/);
  assert.match(BARS, /box-shadow:/);
  // The sheen is a pseudo-element: decoration must never become content.
  assert.match(BARS, /\.ck-viz-bars__fill::after/);
  // A bar for a near-zero value still has to be visible as a small bar rather
  // than read as a missing row.
  assert.match(BARS, /min-width: 4px/);
});

test('the bars keep the two colours that mean something', () => {
  // A negative permutation score and an emphasised majority class are facts,
  // not styling. No amount of gloss may collapse them into the accent.
  assert.match(BARS, /data-negative='true'\]\s*\{\s*--viz-bar: var\(--ck-signal-neg/);
  assert.match(BARS, /data-emphasis='true'\]\s*\{\s*--viz-bar: var\(--ck-signal-warn/);
});

test('a bar arrives in rank order, on a delay the arithmetic decides', () => {
  assert.match(BARS, /staggerDelay\(index, this\.bars\(\)\.length\)/);
  assert.match(BARS, /\[style\.--viz-bar-delay\]="delay\(index\) \+ 'ms'"/);
  assert.match(BARS, /animation-delay: var\(--viz-bar-delay/);
  assert.match(BARS, /@keyframes ck-viz-bar-sweep/);
  assert.match(BARS, /transform: scaleX\(0\)/);
});

test('a count and its share are typeset as two different things', () => {
  // The card used to concatenate them into one mono string, which asked the
  // reader to separate the figure from the gloss on it.
  assert.match(BARS, /class="ck-viz-bars__value"/);
  assert.match(BARS, /class="ck-viz-bars__share"/);
  assert.match(BARS, /@if \(bar\.share\)/);
  assert.match(CARD, /share: this\.percent\(bar\.share\)/);
  assert.ok(
    !/display: `\$\{bar\.count[^`]*percent/.test(CARD),
    'the balance bars no longer glue the percentage onto the count',
  );
});

test('the matrix says the share its shading encodes', () => {
  assert.match(MATRIX, /class="ck-viz-matrix__share"/);
  assert.match(MATRIX, /shareFormat = input<\(\(share: number\) => string\) \| null>\(null\)/);
  // Opt-in, because a percentage needs a locale to be written in: absent a
  // formatter the cell is a count and nothing is invented.
  assert.match(MATRIX, /@if \(shareOf\(cell\); as text\)/);
  assert.match(CARD, /\[shareFormat\]="cellShare"/);
  assert.match(CARD, /cellShare = \(share: number\): string => this\.percent\(share\)/);
});

test('the matrix uncovers itself across the diagonal', () => {
  // `row + column` is a wavefront index, and `2n - 1` is the number of
  // wavefronts — so the first cells to land are the ones on the diagonal.
  assert.match(MATRIX, /staggerDelay\(row \+ column, 2 \* this\.columns\(\) - 1\)/);
  assert.match(MATRIX, /@keyframes ck-viz-cell-in/);
  assert.match(MATRIX, /animation-delay: var\(--viz-cell-delay/);
});

test('a hovered cell is raised, never recoloured', () => {
  // The tint carries the row share. A hover that changed the background would
  // be a hover that changed the reading.
  const hover = /\.ck-viz-matrix__cell:hover\s*\{([^}]*)\}/.exec(MATRIX);
  assert.ok(hover, 'the matrix has a hover rule');
  assert.match(hover![1], /transform: translateY/);
  assert.ok(
    !/background/.test(hover![1]),
    'the hover rule leaves the shading alone',
  );
});

test('every entrance in the kit yields to a reader who asked for less motion', () => {
  // A global reduce-motion rule can collapse a duration but not a delay, which
  // on a stagger leaves the tail of the set blank. Both of these drop the
  // animation outright so the first frame is the final one.
  for (const [name, text] of [
    ['bar list', BARS],
    ['confusion matrix', MATRIX],
  ] as const) {
    const rule = /@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*?)\n\s{6}\}/.exec(text);
    assert.ok(rule, `${name} has a reduced-motion rule`);
    assert.match(rule![1], /animation: none/);
  }
});

test('a tooltip does not stand on the curve it is quoting', () => {
  // chart.js defaults to 2px, which puts the card on the line whose value it
  // is reporting.
  assert.match(CURVE, /caretPadding: 8/);
});
