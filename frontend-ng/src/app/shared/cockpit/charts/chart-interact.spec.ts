import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  easeOutProgress,
  memoizeLayout,
  nearestDayIndex,
  placeTooltip,
  shouldRebuildLayout,
  wrapLabelLines,
} from './chart-interact';

test('memoizeLayout rebuilds only when the key changes', () => {
  let builds = 0;
  const slot = { key: '', value: null as { n: number } | null };
  const first = memoizeLayout(slot, 'days:30', () => {
    builds += 1;
    return { n: builds };
  });
  const again = memoizeLayout(slot, 'days:30', () => {
    builds += 1;
    return { n: builds };
  });
  assert.equal(first, again);
  assert.equal(builds, 1);
  const next = memoizeLayout(slot, 'days:31', () => {
    builds += 1;
    return { n: builds };
  });
  assert.notEqual(first, next);
  assert.equal(builds, 2);
});

test('shouldRebuildLayout ignores hover-only input names', () => {
  assert.equal(shouldRebuildLayout(['hoverDay']), false);
  assert.equal(shouldRebuildLayout(['hoverSystem']), false);
  assert.equal(shouldRebuildLayout(['hoverWeek']), false);
  assert.equal(shouldRebuildLayout(['days']), true);
  assert.equal(shouldRebuildLayout(['days', 'hoverDay']), true);
  assert.equal(shouldRebuildLayout([]), false);
});

test('nearestDayIndex snaps a pointer x onto the closest day', () => {
  assert.equal(nearestDayIndex(6, 6, 100, 11), 0);
  assert.equal(nearestDayIndex(56, 6, 100, 11), 5);
  assert.equal(nearestDayIndex(106, 6, 100, 11), 10);
  assert.equal(nearestDayIndex(-40, 6, 100, 11), 0);
  assert.equal(nearestDayIndex(400, 6, 100, 11), 10);
  assert.equal(nearestDayIndex(50, 0, 100, 1), 0);
});

test('placeTooltip flips at the viewport edges and stays inside', () => {
  assert.deepEqual(
    placeTooltip({ x: 10, y: 80 }, { w: 120, h: 40 }, { w: 200, h: 120 }),
    { x: 18, y: 32 },
  );
  assert.deepEqual(
    placeTooltip({ x: 180, y: 20 }, { w: 120, h: 40 }, { w: 200, h: 120 }),
    { x: 52, y: 28 },
  );
  const tight = placeTooltip({ x: 10, y: 10 }, { w: 180, h: 50 }, { w: 200, h: 80 });
  assert.ok(tight.x >= 0 && tight.x + 180 <= 200);
  assert.ok(tight.y >= 0 && tight.y + 50 <= 80);
});

test('wrapLabelLines keeps short names and wraps long System names to two lines', () => {
  assert.deepEqual(wrapLabelLines('Knowledge Capture', 20), ['Knowledge Capture']);
  assert.deepEqual(wrapLabelLines('SAP HANA Maintenance Copilot', 18), [
    'SAP HANA',
    'Maintenance Copilot',
  ]);
  assert.deepEqual(wrapLabelLines('TenderResponseAnalystWithoutSpaces', 16), [
    'TenderResponseA…',
  ]);
});

test('easeOutProgress lands on 0 and 1', () => {
  assert.equal(easeOutProgress(0), 0);
  assert.equal(easeOutProgress(1), 1);
  assert.ok(easeOutProgress(0.5) > 0.5);
});
