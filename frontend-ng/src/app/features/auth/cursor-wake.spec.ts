import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  magneticInfluence,
  magneticTransform,
  prune,
  pushPoint,
  strand,
  wakeField,
  WAKE_STRAND,
  type WakePoint,
} from './cursor-wake';

function line(count: number, step = 10, t0 = 0, dt = 10): WakePoint[] {
  const points: WakePoint[] = [];
  for (let i = 0; i < count; i++) pushPoint(points, i * step, 0, t0 + i * dt, 3, 100, Infinity);
  return points;
}

test('pushPoint skips hand jitter and keeps the distance travelled', () => {
  const points: WakePoint[] = [];
  assert.equal(pushPoint(points, 0, 0, 0), true);
  assert.equal(pushPoint(points, 1, 1, 5), false);
  assert.equal(pushPoint(points, 3, 4, 10), true);
  assert.deepEqual(points.map((p) => p.d), [0, 5]);
});

test('pushPoint drops the oldest points past the cap', () => {
  const points: WakePoint[] = [];
  for (let i = 0; i < 10; i++) pushPoint(points, i * 10, 0, i, 3, 4, Infinity);
  assert.equal(points.length, 4);
  assert.equal(points[0].x, 60);
});

test('pushPoint fills a fast stroke with evenly spaced points', () => {
  const points: WakePoint[] = [];
  pushPoint(points, 0, 0, 0);
  pushPoint(points, 30, 0, 30, 3, 100, 6);
  assert.deepEqual(points.map((p) => p.x), [0, 6, 12, 18, 24, 30]);
  assert.deepEqual(points.map((p) => p.d), [0, 6, 12, 18, 24, 30]);
  assert.equal(points[3].t, 18);
});

test('prune removes the points older than the lifetime, from the tail only', () => {
  const points = line(5, 10, 0, 100);
  prune(points, 650, 400);
  assert.deepEqual(points.map((p) => p.t), [300, 400]);
  prune(points, 2000, 400);
  assert.equal(points.length, 0);
});

test('two strands half a turn apart sit on opposite sides of the path', () => {
  const points = line(12);
  const a = strand(points, 120, 0);
  const b = strand(points, 120, Math.PI);
  for (let i = 0; i < points.length; i++) {
    assert.ok(Math.abs(a[i].y + b[i].y) < 1e-9, `point ${i} is mirrored`);
  }
  assert.ok(a.some((s) => s.y > 0.5) && a.some((s) => s.y < -0.5), 'the strand crosses the path');
});

test('the wake widens toward its oldest end and fades with age', () => {
  const points = line(20);
  const samples = strand(points, 200, Math.PI / 2, { ...WAKE_STRAND, wavelength: 1e9 });
  const offsets = samples.map((s) => Math.abs(s.y));
  assert.ok(offsets[0] > offsets[offsets.length - 1], 'oldest offset is the widest');
  assert.ok(samples[0].alpha < samples[samples.length - 1].alpha, 'oldest point is the faintest');
  assert.ok(samples[0].width < samples[samples.length - 1].width, 'oldest point is the thinnest');
});

test('an expired point is fully transparent, and an empty wake draws nothing', () => {
  const points = line(3, 10, 0, 10);
  const samples = strand(points, 10_000, 0);
  assert.ok(samples.every((s) => s.alpha === 0));
  assert.deepEqual(strand([], 0, 0), []);
});

test('the magnetic field follows the freshest pointer sample and decays with it', () => {
  const points = line(12, 20, 0, 10);
  const fresh = wakeField(points, 110);
  const aged = wakeField(points, 500);
  const gone = wakeField(points, 1200);

  assert.ok(fresh && fresh.energy > 0.8);
  assert.ok(Math.abs((fresh?.vx ?? 0) - 1) < 1e-9);
  assert.ok(Math.abs(fresh?.vy ?? 1) < 1e-9);
  assert.ok(aged && aged.energy < fresh!.energy);
  assert.equal(gone, null);
});

test('magnetic influence is local, directional and bounded', () => {
  const field = { x: 0, y: 0, vx: 1, vy: 0, energy: 1 };
  const near = magneticInfluence(field, { x: 120, y: 0 }, 360);
  const far = magneticInfluence(field, { x: 400, y: 0 }, 360);

  assert.equal(near.x, 1);
  assert.equal(near.y, 0);
  assert.ok(near.strength > 0.3 && near.strength < 1);
  assert.equal(far.strength, 0);
  assert.equal(magneticInfluence(null, { x: 0, y: 0 }).strength, 0);
});

test('magnetic transforms stay small and scale with orbital depth', () => {
  const field = { x: 0, y: 0, vx: 1, vy: 0, energy: 1 };
  const influence = magneticInfluence(field, { x: 100, y: 0 }, 360);
  const shallow = magneticTransform(influence, field, 0.45);
  const deep = magneticTransform(influence, field, 1.1);
  const translation = (value: string) => value
    .slice(value.indexOf('translate(') + 'translate('.length, value.indexOf(') rotate'))
    .match(/-?\d+(?:\.\d+)?/g)!
    .map(Number);

  assert.ok(Math.abs(translation(deep)[0]) > Math.abs(translation(shallow)[0]));
  assert.ok(translation(deep).every(value => Math.abs(value) <= 34));
  assert.equal(magneticTransform({ ...influence, strength: 0 }, field, 1), '');
});
