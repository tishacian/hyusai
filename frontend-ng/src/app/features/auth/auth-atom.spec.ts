import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  ATOM_MAX_TILT_X_DEG,
  ATOM_MAX_TILT_Y_DEG,
  ATOM_RINGS,
  atomTransform,
  electronSpeed,
  REST_POSE,
  ringPoint,
  settle,
  targetPose,
} from './auth-atom';

test('the atom turns toward the pointer, within a few degrees', () => {
  const right = targetPose(900, 0, 600, 400);
  assert.equal(right.ry, ATOM_MAX_TILT_Y_DEG, 'full tilt beyond the reach');
  assert.equal(right.rx, 0);
  const above = targetPose(0, -200, 600, 400);
  assert.equal(above.rx, ATOM_MAX_TILT_X_DEG / 2, 'the top comes toward a pointer above');
  assert.deepEqual(targetPose(0, 0, 600, 400), { rx: 0, ry: 0, near: 1 });
});

test('near only rises close to the atom, smoothly', () => {
  assert.equal(targetPose(500, 0, 600, 400, 420).near, 0);
  const half = targetPose(210, 0, 600, 400, 420).near;
  assert.ok(half > 0.4 && half < 0.6);
  assert.ok(targetPose(50, 0, 600, 400, 420).near > half);
});

test('settle eases toward the target the same way at any frame rate', () => {
  const target = { rx: 6, ry: -8, near: 1 };
  let fast = REST_POSE;
  for (let i = 0; i < 6; i++) fast = settle(fast, target, 1000 / 60);
  const slow = settle(settle(REST_POSE, target, 50), target, 50);
  assert.ok(Math.abs(fast.ry - slow.ry) < 1e-9, '6 frames at 60 Hz = 2 frames at 20 Hz');
  assert.ok(Math.abs(fast.ry) < Math.abs(target.ry), 'not there yet after 0.1 s');
  const settled = settle(REST_POSE, target, 3000);
  assert.ok(Math.abs(settled.rx - target.rx) < 0.01, 'settled after 3 s');
});

test('an electron stays on its ring', () => {
  const ring = ATOM_RINGS[0];
  const theta = (ring.rotation * Math.PI) / 180;
  for (const angle of [0, 0.7, 2, 4.1]) {
    const { x, y } = ringPoint(ring, angle);
    // Back to the ellipse frame: (u/rx)² + (v/ry)² = 1.
    const u = (x - 200) * Math.cos(theta) + (y - 200) * Math.sin(theta);
    const v = -(x - 200) * Math.sin(theta) + (y - 200) * Math.cos(theta);
    assert.ok(Math.abs((u / ring.rx) ** 2 + (v / ring.ry) ** 2 - 1) < 1e-9);
  }
});

test('electrons speed up when the pointer is near, and keep their direction', () => {
  const [first, second] = ATOM_RINGS;
  assert.ok(electronSpeed(first, 1) > electronSpeed(first, 0) * 3);
  assert.ok(electronSpeed(second, 0) < 0, 'the middle ring turns the other way');
  assert.equal(electronSpeed(first, 0), (Math.PI * 2) / first.periodS);
});

test('the atom transform is a tilt, never a deformation', () => {
  const css = atomTransform({ rx: 3.456, ry: -2, near: 0.5 });
  assert.equal(css, 'perspective(1100px) rotateX(3.46deg) rotateY(-2.00deg)');
  assert.ok(!/scale|skew|translate/.test(css));
});
