import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { HypervisorDayPoint, HypervisorRegisterRow, HypervisorStreamRow, SeriesFact } from './hypervisor-v2-series';
import {
  DAY_LOCK_IDLE,
  activityStrip,
  lockTransition,
  reduceDayLock,
  selectedDay,
  selectionModel,
  stripKeyTarget,
  type DayLockEvent,
  type DayLockState,
} from './impact-synthese';

function run(events: readonly DayLockEvent[], from: DayLockState = DAY_LOCK_IDLE): DayLockState {
  return events.reduce(reduceDayLock, from);
}

test('day lock: a click locks, the lock survives the pointer leaving', () => {
  const state = run([{ type: 'hover', day: 4 }, { type: 'toggle', day: 4 }, { type: 'hover', day: null }]);
  assert.deepEqual(state, { locked: 4, hover: null });
  assert.equal(selectedDay(state), 4);
});

test('day lock: hovering another day previews it without replacing the lock', () => {
  const locked = run([{ type: 'toggle', day: 4 }]);
  const preview = reduceDayLock(locked, { type: 'hover', day: 9 });
  assert.equal(preview.locked, 4, 'the lock stays');
  assert.equal(selectedDay(preview), 9, 'linked views follow the preview while it lasts');
  assert.equal(selectedDay(reduceDayLock(preview, { type: 'hover', day: null })), 4, 'then fall back to the lock');
});

test('day lock: the same day or Escape unlocks; locking another day moves the lock', () => {
  assert.equal(run([{ type: 'toggle', day: 4 }, { type: 'toggle', day: 4 }]).locked, null);
  assert.equal(run([{ type: 'toggle', day: 4 }, { type: 'escape' }]).locked, null);
  assert.equal(run([{ type: 'toggle', day: 4 }, { type: 'toggle', day: 7 }]).locked, 7);
  const idle = DAY_LOCK_IDLE;
  assert.equal(reduceDayLock(idle, { type: 'escape' }), idle, 'Escape without a lock is a no-op');
  assert.equal(reduceDayLock(idle, { type: 'hover', day: null }), idle, 'same hover keeps identity');
  assert.deepEqual(run([{ type: 'toggle', day: 2 }, { type: 'hover', day: 5 }, { type: 'reset' }]), DAY_LOCK_IDLE);
});

test('day lock: transitions name what the live region announces', () => {
  const locked = { locked: 4, hover: 4 };
  assert.equal(lockTransition(DAY_LOCK_IDLE, locked), 'locked');
  assert.equal(lockTransition(locked, { locked: 7, hover: 7 }), 'locked', 'a moved lock is announced on its new day');
  assert.equal(lockTransition(locked, { locked: null, hover: 4 }), 'unlocked');
  assert.equal(lockTransition(locked, { locked: 4, hover: 9 }), null, 'a preview is not announced');
  assert.equal(lockTransition(DAY_LOCK_IDLE, { locked: null, hover: 3 }), null);
});

function day(date: string, measured: number, declared: number, extra: Partial<HypervisorDayPoint> = {}): HypervisorDayPoint {
  const weekday = new Date(`${date}T12:00:00Z`).getUTCDay();
  return { date, weekday, weekend: weekday === 0 || weekday === 6, measured, declared, runs: 10, systems: 2, ...extra };
}

// 2026-08-27 is a Thursday: Thu–Sun close ISO week 35, Mon 31 opens week 36.
const DAYS = [
  day('2026-08-27', 10, 30),
  day('2026-08-28', 5, 15),
  day('2026-08-29', 0, 0),
  day('2026-08-30', 1, 1),
  day('2026-08-31', 40, 69, { runs: 73, systems: 2 }),
  day('2026-09-01', 20, 20),
];

test('activity strip: one mark per day, shares of the busiest day, ISO weeks from Monday', () => {
  const strip = activityStrip(DAYS, null);
  assert.equal(strip.marks.length, DAYS.length);
  assert.equal(strip.max, 109);
  assert.equal(strip.marks[4]!.share, 1);
  assert.equal(strip.marks[2]!.share, 0, 'an empty day stays an empty mark, not a fake minimum');
  assert.equal(strip.marks[2]!.weekend, true);
  assert.deepEqual(strip.weeks.map((w) => [w.start, w.end, w.isoWeek]), [[0, 4, 35], [4, 6, 36]]);
  assert.equal(strip.selectedWeek, null);
  assert.ok(strip.marks.every((mark) => !mark.selected && !mark.inSelectedWeek));
});

test('activity strip: the selected day lights its mark and bands its week', () => {
  const strip = activityStrip(DAYS, 5);
  assert.deepEqual([strip.selectedWeek?.start, strip.selectedWeek?.end], [4, 6]);
  assert.deepEqual(strip.marks.map((m) => m.inSelectedWeek), [false, false, false, false, true, true]);
  assert.deepEqual(strip.marks.map((m) => m.selected), [false, false, false, false, false, true]);
  assert.equal(activityStrip(DAYS, 99).selectedWeek, null, 'an out-of-range day selects nothing');
  assert.equal(activityStrip([], null).max, 0);
});

test('activity strip: the locked week is named apart from a passing preview', () => {
  const locked = activityStrip(DAYS, 1, 5);
  assert.deepEqual([locked.lockedWeek?.start, locked.lockedWeek?.end, locked.lockedWeek?.isoWeek], [4, 6, 36]);
  assert.deepEqual([locked.selectedWeek?.start, locked.selectedWeek?.isoWeek], [0, 35], 'the band follows the preview');
  assert.deepEqual(locked.marks.map((m) => m.locked), [false, false, false, false, false, true]);
  assert.equal(activityStrip(DAYS, 3).lockedWeek, null, 'no lock, no locked week');
  assert.equal(activityStrip(DAYS, null, 42).lockedWeek, null, 'an out-of-range lock names nothing');
});

test('activity strip: a lock from the strip is the same toggle as a spoke or a river day', () => {
  // Enter or a click on day 4 of the strip, then the same day again.
  const locked = run([{ type: 'hover', day: 4 }, { type: 'toggle', day: 4 }]);
  assert.equal(activityStrip(DAYS, selectedDay(locked), locked.locked).lockedWeek?.isoWeek, 36);
  assert.equal(lockTransition(DAY_LOCK_IDLE, locked), 'locked');
  const unlocked = reduceDayLock(locked, { type: 'toggle', day: 4 });
  assert.equal(unlocked.locked, null);
  assert.equal(activityStrip(DAYS, selectedDay(unlocked), unlocked.locked).lockedWeek, null);
});

test('activity strip keys: arrows walk a day, Page keys a week, Home/End the ends, no wrap', () => {
  assert.equal(stripKeyTarget('ArrowRight', 3, 30), 4);
  assert.equal(stripKeyTarget('ArrowLeft', 3, 30), 2);
  assert.equal(stripKeyTarget('ArrowRight', 29, 30), 29, 'the strip stops at the last day');
  assert.equal(stripKeyTarget('ArrowLeft', 0, 30), 0);
  assert.equal(stripKeyTarget('PageDown', 3, 30), 10);
  assert.equal(stripKeyTarget('PageUp', 3, 30), 0);
  assert.equal(stripKeyTarget('Home', 12, 30), 0);
  assert.equal(stripKeyTarget('End', 12, 30), 29);
  assert.equal(stripKeyTarget('Enter', 12, 30), null, 'Enter locks, it does not move');
  assert.equal(stripKeyTarget('ArrowRight', 0, 0), null);
});

function fact(value: number | null): SeriesFact {
  return value == null ? { state: 'not_configured', value: null } : { state: 'available', value };
}

function row(systemId: string, hours: number | null, outside = false): HypervisorRegisterRow {
  return {
    systemId,
    capabilityId: null,
    name: systemId.toUpperCase(),
    initials: systemId.slice(0, 2).toUpperCase(),
    health: 'pos',
    daysSinceLastRun: fact(0),
    outputUnit: null,
    weekSpark: [],
    cost: fact(10),
    hours: fact(hours),
    valueDeclared: fact(hours == null ? null : hours * 40),
    outcomes: fact(1),
    runs: fact(1),
    basisStatus: hours == null ? null : 'declared',
    currency: 'EUR',
    outsideDenominator: outside,
  };
}

function stream(systemId: string, values: number[], tone: HypervisorStreamRow['tone']): HypervisorStreamRow {
  return { systemId, label: systemId, values, total: values.reduce((a, b) => a + b, 0), tone, basisStatus: 'declared' };
}

const VIEW = {
  days: DAYS,
  peak: { index: 4, date: '2026-08-31', total: 109, measured: 40, declared: 69, runs: 73, systems: 2 },
  streams: [
    stream('kc', [30, 15, 0, 1, 31, 20], 'declared'),
    stream('tr', [10, 5, 0, 1, 68, 20], 'ink'),
    stream('sap', [0, 0, 0, 0, 10, 0], 'declared-soft'),
  ],
  register: [row('kc', 1868), row('tr', 512), row('sap', 116), row('risk', null, true)],
};

test('selection panel: at rest it names the busiest day and the top system of the window', () => {
  const model = selectionModel(VIEW, DAY_LOCK_IDLE, null, null);
  assert.equal(model.day?.mode, 'peak');
  assert.equal(model.day?.index, 4);
  assert.equal(model.day?.total, 109);
  assert.deepEqual(model.rivers.map((p) => [p.systemId, p.value, p.declared]), [
    ['tr', 68, false],
    ['kc', 31, true],
    ['sap', 10, true],
  ]);
  assert.equal(model.system?.mode, 'period');
  assert.equal(model.system?.row.systemId, 'kc', 'largest hours, never a system outside the total');
});

test('selection panel: a locked day drives the rivers breakdown and the system of the day', () => {
  const model = selectionModel(VIEW, { locked: 0, hover: null }, null, null);
  assert.equal(model.day?.mode, 'locked');
  assert.deepEqual(model.rivers.map((p) => p.systemId), ['kc', 'tr'], 'zero parts are left out');
  assert.equal(model.system?.mode, 'day');
  assert.equal(model.system?.row.systemId, 'kc');
  assert.deepEqual(selectionModel(VIEW, { locked: 2, hover: null }, null, null).rivers, [], 'an empty day has no parts');
});

test('selection panel: a preview over a lock is a preview; hover and pin override the system', () => {
  assert.equal(selectionModel(VIEW, { locked: 0, hover: 5 }, null, null).day?.mode, 'preview');
  assert.equal(selectionModel(VIEW, { locked: 5, hover: 5 }, null, null).day?.mode, 'locked');
  assert.equal(selectionModel(VIEW, { locked: null, hover: 1 }, null, null).day?.mode, 'preview');
  const pinned = selectionModel(VIEW, { locked: 4, hover: null }, null, 'sap');
  assert.deepEqual([pinned.system?.mode, pinned.system?.row.systemId], ['pinned', 'sap']);
  const hovered = selectionModel(VIEW, { locked: 4, hover: null }, 'risk', 'sap');
  assert.deepEqual([hovered.system?.mode, hovered.system?.row.systemId], ['hover', 'risk']);
  assert.equal(selectionModel(VIEW, DAY_LOCK_IDLE, 'unknown', null).system?.mode, 'period');
  assert.deepEqual(selectionModel(null, DAY_LOCK_IDLE, null, null), { day: null, rivers: [], system: null });
});
