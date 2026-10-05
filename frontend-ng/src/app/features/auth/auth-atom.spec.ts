import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  angleAtLength,
  arcTable,
  ATOM_RINGS,
  bridgePoints,
  bridgeStrength,
  electronSpeed,
  nearness,
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

test('dashes spaced by arc length sit evenly along a flat ellipse', () => {
  const ring = ATOM_RINGS[0];
  const table = arcTable(ring);
  const count = 40;
  const step = table.total / count;
  const gaps: number[] = [];
  let previous = ringPoint(ring, angleAtLength(table, 0));
  for (let k = 1; k <= count; k++) {
    const point = ringPoint(ring, angleAtLength(table, k * step));
    gaps.push(Math.hypot(point.x - previous.x, point.y - previous.y));
    previous = point;
  }
  const spread = Math.max(...gaps) / Math.min(...gaps);
  assert.ok(spread < 1.05, `chords within 5 % of each other (got ${spread.toFixed(3)})`);
});

test('arc length wraps around the ring both ways', () => {
  const table = arcTable(ATOM_RINGS[2]);
  const a = angleAtLength(table, 10);
  assert.ok(Math.abs(angleAtLength(table, 10 + table.total) - a) < 1e-9);
  assert.ok(Math.abs(angleAtLength(table, 10 - table.total) - a) < 1e-9);
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
