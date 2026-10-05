import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  arcTable,
  ATOM_RINGS,
  bridgePoints,
  bridgeStrength,
  electronSpeed,
  nearness,
  orbitBraid,
  pruneByLength,
  ringPoint,
} from './auth-atom';

test('an electron stays on its ring, drift included', () => {
  const ring = ATOM_RINGS[0];
  for (const extra of [0, 37]) {
    const theta = ((ring.rotation + extra) * Math.PI) / 180;
    for (const angle of [0, 0.7, 2, 4.1]) {
      const { x, y } = ringPoint(ring, angle, 200, 200, extra);
      const u = (x - 200) * Math.cos(theta) + (y - 200) * Math.sin(theta);
      const v = -(x - 200) * Math.sin(theta) + (y - 200) * Math.cos(theta);
      assert.ok(Math.abs((u / ring.rx) ** 2 + (v / ring.ry) ** 2 - 1) < 1e-9);
    }
  }
});

test('the arc table measures the perimeter of an ellipse', () => {
  const ring = ATOM_RINGS[0];
  const h = ((ring.rx - ring.ry) / (ring.rx + ring.ry)) ** 2;
  const ramanujan = Math.PI * (ring.rx + ring.ry) * (1 + (3 * h) / (10 + Math.sqrt(4 - 3 * h)));
  assert.ok(Math.abs(arcTable(ring).total - ramanujan) / ramanujan < 1e-4);
});

test('nearness eases from the edge of the radius to the atom', () => {
  assert.equal(nearness(500, 420), 0);
  assert.equal(nearness(0, 420), 1);
  const half = nearness(210, 420);
  assert.ok(half > 0.4 && half < 0.6);
});

test('electrons speed up when the pointer is near, and keep their direction', () => {
  const [first, second] = ATOM_RINGS;
  assert.ok(electronSpeed(first, 1) > electronSpeed(first, 0) * 3);
  assert.ok(electronSpeed(second, 0) < 0, 'the middle ring turns the other way');
  assert.equal(electronSpeed(first, 0), (Math.PI * 2) / first.periodS);
});

test('the bridge runs from the electron to the pointer and sags to one side', () => {
  const points = bridgePoints(0, 0, 100, 0, 5);
  assert.deepEqual([points[0].x, points[0].y], [0, 0]);
  const end = points[points.length - 1];
  assert.ok(Math.abs(end.x - 100) < 1e-9 && Math.abs(end.y) < 1e-9);
  const middle = points[Math.floor(points.length / 2)];
  assert.ok(middle.y > 5, 'the thread sags off the straight line');
  assert.ok(points.every((p, i) => i === 0 || p.d > points[i - 1].d), 'distance grows along it');
  assert.deepEqual(bridgePoints(3, 3, 3.2, 3, 0), []);
});

test('the bridge appears close to an electron and grows with the pull', () => {
  assert.equal(bridgeStrength(250, 1), 0);
  assert.equal(bridgeStrength(60, 1), 1);
  assert.ok(bridgeStrength(150, 1) > 0 && bridgeStrength(150, 1) < 1);
  assert.equal(bridgeStrength(60, 0.5), 0.5);
});

test('a trail keeps only its last stretch, measured from the head', () => {
  const points = [0, 10, 20, 30, 40, 50].map((d) => ({ d }));
  pruneByLength(points, 25);
  assert.deepEqual(points.map((p) => p.d), [30, 40, 50]);
  pruneByLength([], 10);
});

test('an orbit braid has two mirrored strands that fade and open toward the tail', () => {
  const trail = Array.from({ length: 41 }, (_, i) => ({ x: i * 5, y: 0, d: i * 5 }));
  const options = { amplitude: 3, wavelength: 1e9, width: 1.2, spread: 1.5 };
  const a = orbitBraid(trail, Math.PI / 2, 200, options);
  const b = orbitBraid(trail, -Math.PI / 2, 200, options);
  assert.ok(a.every((s, i) => Math.abs(s.y + b[i].y) < 1e-9), 'mirrored strands');
  assert.equal(a[a.length - 1].life, 1);
  assert.equal(a[0].life, 0);
  assert.ok(Math.abs(a[0].y) > Math.abs(a[a.length - 1].y) * 2, 'opens toward the tail');
  assert.ok(a[0].width < a[a.length - 1].width, 'thins toward the tail');
  assert.deepEqual(orbitBraid([], 0, 100, options), []);
});
