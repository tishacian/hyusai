/**
 * The orb's drawing is vendored from an upstream React package (see
 * `vendor/README.md`), which means it is upgraded by re-copying files rather
 * than by patching them. These tests are the contract that a re-copy has to
 * keep: every state still resolves to a painter, and every painter still runs
 * headless against the five-member canvas surface the engine actually touches.
 * Without them, a version bump would only be caught by looking at the screen.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { MODE_DRAWS } from './vendor/engine/registry';
import { resolvePreset, STATE_TO_MODE } from './vendor/presets';
import type { OrbSize, OrbState } from './vendor/types';

const STATES: OrbState[] = ['working', 'searching', 'solving', 'listening', 'composing', 'shaping'];
const SIZES: OrbSize[] = [64, 20];

/** Records what a painter drew. The engine only ever fills arcs. */
function fakeContext() {
  const arcs: { x: number; y: number; r: number }[] = [];
  const inks: string[] = [];
  return {
    arcs,
    inks,
    ctx: {
      fillStyle: '',
      filter: '',
      beginPath: () => {},
      arc(x: number, y: number, r: number) {
        arcs.push({ x, y, r });
      },
      fill() {
        inks.push(String(this.fillStyle));
      },
    } as unknown as CanvasRenderingContext2D,
  };
}

test('every state maps to a painter at both tuned sizes', () => {
  for (const state of STATES) {
    for (const size of SIZES) {
      const resolved = resolvePreset(state, size);
      assert.equal(resolved.mode, STATE_TO_MODE[state], `${state} changed mode`);
      assert.equal(typeof MODE_DRAWS[resolved.mode], 'function', `${resolved.mode} has no painter`);
      assert.ok(resolved.speed > 0, `${state}/${size} would be frozen`);
    }
  }
});

test('each painter puts ink inside the canvas box', () => {
  for (const state of STATES) {
    for (const size of SIZES) {
      const { mode, opts } = resolvePreset(state, size);
      const { ctx, arcs, inks } = fakeContext();
      // Two instants: a state that only draws at t=0 would look dead on screen.
      MODE_DRAWS[mode](ctx, size, 0.6, true, opts);
      const atRest = arcs.length;
      MODE_DRAWS[mode](ctx, size, 1.7, true, opts);

      assert.ok(atRest > 0, `${state}/${size} drew nothing`);
      assert.ok(arcs.length > atRest, `${state}/${size} stopped drawing after the first frame`);
      assert.ok(inks.every((ink) => ink.startsWith('rgba(')), `${state}/${size} left ink unset`);
      // A dot outside the box is clipped away and the orb looks truncated.
      const stray = arcs.find((dot) => dot.x < -size || dot.x > 2 * size || dot.r > size);
      assert.equal(stray, undefined, `${state}/${size} drew outside the canvas: ${JSON.stringify(stray)}`);
    }
  }
});

test('dark and light are the same drawing in opposite ink', () => {
  // The canvas is transparent: dark surfaces need light dots and vice versa.
  const { mode, opts } = resolvePreset('working', 64);
  const dark = fakeContext();
  const light = fakeContext();
  MODE_DRAWS[mode](dark.ctx, 64, 0.6, true, opts);
  MODE_DRAWS[mode](light.ctx, 64, 0.6, false, opts);

  assert.equal(dark.arcs.length, light.arcs.length, 'the theme moved the dots');
  assert.notDeepEqual(dark.inks, light.inks, 'the theme left the ink unchanged');
});

test('resolving a preset twice hands back the cached tuning', () => {
  // The render loop resolves on every input change; recomputing the scaled
  // profiles each time would allocate inside an animation frame.
  assert.equal(resolvePreset('searching', 20), resolvePreset('searching', 20));
});

test('prefers-reduced-motion pins a single representative frame', () => {
  // thinking-orb.component.ts paints frame(0.6) once when reduced motion is
  // on — no requestAnimationFrame loop. The painter at that instant must be
  // deterministic so two captures 500 ms apart stay identical.
  const source = readFileSync(
    join(process.cwd(), 'src/app/shared/cockpit/thinking-orb/thinking-orb.component.ts'),
    'utf8',
  );
  assert.match(source, /prefers-reduced-motion:\s*reduce/);
  const reducedBlock = source.match(/if\s*\(\s*reduced\s*\)\s*\{([\s\S]*?)\n\s*\}/);
  assert.ok(reducedBlock, 'missing reduced-motion branch');
  assert.match(reducedBlock[1], /frame\(\s*0\.6\s*\)/);
  assert.doesNotMatch(reducedBlock[1], /requestAnimationFrame/);

  const { mode, opts } = resolvePreset('working', 64);
  const first = fakeContext();
  const second = fakeContext();
  MODE_DRAWS[mode](first.ctx, 64, 0.6, true, opts);
  MODE_DRAWS[mode](second.ctx, 64, 0.6, true, opts);
  assert.deepEqual(first.arcs, second.arcs, 'the reduced-motion frame drifted');
  assert.deepEqual(first.inks, second.inks, 'the reduced-motion ink drifted');
});
