import assert from 'node:assert/strict';
import { test } from 'node:test';
import { swarmFrame, swarmLayout, SWARM_FULL_PX, SWARM_REST_PX } from './orb-swarm';

test('at rest the shell stays inside the gathered sphere', () => {
  const radii = swarmFrame(swarmLayout(24), 0, 1, 0, 0).map((dot) => Math.hypot(dot.x, dot.y));
  const widest = Math.max(...radii);
  assert.ok(widest <= SWARM_REST_PX + 0.6, `widest ${widest}`);
  assert.ok(widest > SWARM_REST_PX - 1);
});

test('points facing the pointer travel out, the far side stays closer', () => {
  const points = swarmLayout(48);
  const closed = swarmFrame(points, 0, 1, 0, 0);
  const open = swarmFrame(points, 1, 1, 0, 0);
  const facing = open.reduce((best, dot, i) => (dot.x > open[best].x ? i : best), 0);
  const far = open.reduce((best, dot, i) => (dot.x < open[best].x ? i : best), 0);
  assert.ok(Math.hypot(open[facing].x, open[facing].y) > Math.hypot(closed[facing].x, closed[facing].y));
  assert.ok(Math.hypot(open[facing].x, open[facing].y) > SWARM_REST_PX + 20);
  assert.ok(Math.hypot(open[facing].x, open[facing].y) <= SWARM_FULL_PX + 0.6);
  assert.ok(Math.hypot(open[far].x, open[far].y) < Math.hypot(open[facing].x, open[facing].y));
});
