import assert from 'node:assert/strict';
import { test } from 'node:test';
import { GRAVITY, Membrane, pull } from './gravity';

test('a point is pulled toward the well, never past half the distance', () => {
  const [dx, dy] = pull(100, 100, { x: 200, y: 100, mass: 1 });
  assert.ok(dx > 0 && Math.abs(dy) < 1e-9, 'pulled straight toward the well');
  assert.ok(dx <= GRAVITY.maxShift);
  const [close] = pull(100, 100, { x: 110, y: 100, mass: 1 });
  assert.ok(close <= 4.5 + 1e-9, 'gathers around the pointer instead of jumping over it');
});

test('the pull fades with distance and with the mass of the well', () => {
  // Far enough from the well that the half-distance cap does not apply.
  const near = Math.hypot(...pull(0, 0, { x: 200, y: 0, mass: 1 }));
  const far = Math.hypot(...pull(0, 0, { x: 900, y: 0, mass: 1 }));
  const light = Math.hypot(...pull(0, 0, { x: 200, y: 0, mass: 0.25 }));
  assert.ok(near > far * 10);
  assert.ok(Math.abs(light - near * 0.25) < 1e-9);
  assert.deepEqual(pull(0, 0, null), [0, 0]);
  assert.deepEqual(pull(0, 0, { x: 50, y: 0, mass: 0 }), [0, 0]);
});

test('the membrane bends toward the well, and the deformation is continuous', () => {
  const membrane = new Membrane(400, 400, 20);
  const well = { x: 200, y: 200, mass: 1 };
  for (let i = 0; i < 120; i++) membrane.step(well, 1000 / 60);
  const [left] = membrane.sample(150, 200);
  const [right] = membrane.sample(250, 200);
  assert.ok(left > 1, 'a point left of the well moves right');
  assert.ok(right < -1, 'a point right of the well moves left');
  // Two points a pixel apart move almost the same: no tearing between them.
  const a = membrane.sample(120.2, 230.4);
  const b = membrane.sample(121.2, 230.4);
  assert.ok(Math.hypot(a[0] - b[0], a[1] - b[1]) < 0.3);
});

test('the border stays pinned and the membrane springs back to rest', () => {
  const membrane = new Membrane(400, 400, 20);
  for (let i = 0; i < 60; i++) membrane.step({ x: 10, y: 10, mass: 1 }, 1000 / 60);
  assert.deepEqual(membrane.sample(0, 0), [0, 0]);
  assert.ok(membrane.activity() > 1);
  for (let i = 0; i < 600; i++) membrane.step(null, 1000 / 60);
  assert.ok(membrane.activity() < 0.05, 'at rest 10 s after the well leaves');
});

test('the membrane moves the same way whatever the frame rate', () => {
  const well = { x: 180, y: 220, mass: 1 };
  const fast = new Membrane(400, 400, 20);
  const slow = new Membrane(400, 400, 20);
  for (let i = 0; i < 60; i++) fast.step(well, 1000 / 60);
  for (let i = 0; i < 20; i++) slow.step(well, 50);
  const a = fast.sample(140, 220);
  const b = slow.sample(140, 220);
  assert.ok(Math.hypot(a[0] - b[0], a[1] - b[1]) < 0.05);
});
