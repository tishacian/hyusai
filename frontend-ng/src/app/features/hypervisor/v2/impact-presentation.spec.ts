import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { HypervisorDayPoint, HypervisorRegisterRow, HypervisorStreamRow, SeriesFact } from './hypervisor-v2-series';
import { DAY_LOCK_IDLE, reduceDayLock, selectionModel, type DayLockState } from './impact-synthese';
import { presentationEscape, proofChain, type ProofBasisAuthor } from './impact-presentation';

// --- Escape order ------------------------------------------------------------------

test('Escape in Présentation: a locked day is unlocked first, the next press leaves the theme', () => {
  let lock: DayLockState = reduceDayLock(DAY_LOCK_IDLE, { type: 'toggle', day: 4 });
  assert.equal(presentationEscape(lock), 'unlock', 'first press: the lock goes');
  lock = reduceDayLock(lock, { type: 'escape' });
  assert.equal(lock.locked, null);
  assert.equal(presentationEscape(lock), 'exit', 'second press: the theme goes');
});

test('Escape in Présentation: without a lock the first press leaves; a preview is not a lock', () => {
  assert.equal(presentationEscape(DAY_LOCK_IDLE), 'exit');
  assert.equal(presentationEscape({ locked: null, hover: 7 }), 'exit', 'a hovered day never holds the theme');
  assert.equal(presentationEscape({ locked: 0, hover: null }), 'unlock', 'day 0 is a real lock');
});

// --- Chaîne de preuve ----------------------------------------------------------------

function point(date: string, measured: number, declared: number, runs = 10, systems = 2): HypervisorDayPoint {
  const weekday = new Date(`${date}T12:00:00Z`).getUTCDay();
  return { date, weekday, weekend: weekday === 0 || weekday === 6, measured, declared, runs, systems };
}

function fact(value: number | null): SeriesFact {
  return value == null ? { state: 'not_configured', value: null } : { state: 'available', value };
}

function row(systemId: string, hours: number | null, basis: HypervisorRegisterRow['basisStatus']): HypervisorRegisterRow {
  return {
    systemId,
    capabilityId: `cap-${systemId}`,
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
    runs: fact(3),
    basisStatus: basis,
    currency: 'EUR',
    outsideDenominator: hours == null,
  };
}

function stream(systemId: string, values: number[], tone: HypervisorStreamRow['tone']): HypervisorStreamRow {
  return { systemId, label: systemId, values, total: values.reduce((a, b) => a + b, 0), tone, basisStatus: 'declared' };
}

const VIEW = {
  days: [point('2026-08-29', 0, 0), point('2026-08-30', 1, 1), point('2026-08-31', 40, 69, 73, 4), point('2026-09-01', 20, 20)],
  peak: { index: 2, date: '2026-08-31', total: 109, measured: 40, declared: 69, runs: 73, systems: 4 },
  streams: [
    stream('kc', [0, 1, 31, 20], 'declared'),
    stream('tr', [0, 1, 40, 20], 'ink'),
    stream('sap', [0, 0, 10, 0], 'declared-soft'),
    stream('hr', [0, 0, 28, 0], 'declared'),
  ],
  register: [row('kc', 1868, 'declared'), row('tr', 512, 'measured'), row('sap', 116, 'declared'), row('hr', 90, null)],
};

const AUTHORS: Record<string, ProofBasisAuthor> = {
  kc: { by: 'Claire Martin', at: '2026-08-12' },
  tr: { by: null, at: null },
};
const author = (r: HypervisorRegisterRow): ProofBasisAuthor | null => AUTHORS[r.systemId] ?? null;

test('chaîne de preuve: a locked day states the day, its rivers, its system and the basis author', () => {
  const lock = reduceDayLock(DAY_LOCK_IDLE, { type: 'toggle', day: 2 });
  const [day, rivers, register, basis] = proofChain(selectionModel(VIEW, lock, null, null), author);
  assert.deepEqual(
    [day.step, day.state, day.index, day.date, day.total, day.runs, day.systems],
    [1, 'locked', 2, '2026-08-31', 109, 73, 4],
  );
  assert.equal(rivers.state, 'parts');
  assert.deepEqual(rivers.parts.map((p) => [p.systemId, p.value]), [['tr', 40], ['kc', 31], ['hr', 28]], 'largest first');
  assert.equal(rivers.more, 1, 'the fourth part is counted, not dropped');
  assert.deepEqual([register.state, register.mode, register.row?.systemId], ['row', 'day', 'tr'], 'top system of the locked day');
  assert.deepEqual([basis.state, basis.by, basis.at], ['measured', null, null], 'unknown author stays unknown');
});

test('chaîne de preuve: follows the lock to another day, and names a declared basis with its author', () => {
  const lock = reduceDayLock(DAY_LOCK_IDLE, { type: 'toggle', day: 1 });
  const [day, rivers, register, basis] = proofChain(selectionModel(VIEW, lock, null, null), author);
  assert.deepEqual([day.state, day.date, day.total], ['locked', '2026-08-30', 2]);
  assert.deepEqual(rivers.parts.map((p) => p.systemId), ['kc', 'tr']);
  assert.equal(rivers.more, 0);
  assert.equal(register.row?.systemId, 'kc');
  assert.deepEqual([basis.state, basis.by, basis.at], ['declared', 'Claire Martin', '2026-08-12']);
});

test('chaîne de preuve: at rest it shows the busiest day, an empty locked day says so', () => {
  const [day, , register] = proofChain(selectionModel(VIEW, DAY_LOCK_IDLE, null, null), author);
  assert.deepEqual([day.state, day.index], ['peak', 2]);
  assert.equal(register.mode, 'period', 'no lock: the top system of the window');

  const empty = proofChain(selectionModel(VIEW, { locked: 0, hover: null }, null, null), author);
  assert.deepEqual([empty[0].state, empty[0].total], ['locked', 0]);
  assert.deepEqual([empty[1].state, empty[1].parts.length], ['empty', 0]);
});

test('chaîne de preuve: a system without a basis reads « missing »; no series reads « none » everywhere', () => {
  const chain = proofChain(selectionModel(VIEW, { locked: 2, hover: null }, 'hr', null), author);
  assert.deepEqual([chain[2].mode, chain[2].row?.systemId], ['hover', 'hr']);
  assert.equal(chain[3].state, 'missing');

  const none = proofChain(selectionModel(null, DAY_LOCK_IDLE, null, null), author);
  assert.deepEqual(none.map((step) => [step.step, step.state]), [[1, 'none'], [2, 'none'], [3, 'none'], [4, 'none']]);
});
