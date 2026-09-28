import {
  availableNumber,
  isoWeek,
  type HypervisorDayPoint,
  type HypervisorRegisterRow,
  type HypervisorSeriesView,
} from './hypervisor-v2-series';

/**
 * Synthèse W2-v5: the state every linked view of the Direction page reads —
 * the day the cadran, the activity strip, the rivers and the selection panel
 * all point at, and the system the panel and the "selected system" band name.
 *
 * Pure functions only, so the lock machine and the panel content are tested
 * without Angular.
 */

// --- Day lock ---------------------------------------------------------------

/**
 * `hover` is the transient preview (pointer or keyboard focus on a day),
 * `locked` the day a click, Enter or Space pinned. A preview never replaces
 * the lock: it shows while it lasts, then the page falls back to the lock.
 */
export interface DayLockState {
  readonly locked: number | null;
  readonly hover: number | null;
}

export type DayLockEvent =
  | { readonly type: 'hover'; readonly day: number | null }
  | { readonly type: 'toggle'; readonly day: number }
  | { readonly type: 'escape' }
  | { readonly type: 'reset' };

export const DAY_LOCK_IDLE: DayLockState = { locked: null, hover: null };

export function reduceDayLock(state: DayLockState, event: DayLockEvent): DayLockState {
  switch (event.type) {
    case 'hover':
      return state.hover === event.day ? state : { locked: state.locked, hover: event.day };
    case 'toggle':
      return { locked: state.locked === event.day ? null : event.day, hover: state.hover };
    case 'escape':
      return state.locked == null ? state : { locked: null, hover: state.hover };
    case 'reset':
      return state.locked == null && state.hover == null ? state : DAY_LOCK_IDLE;
  }
}

/** The day every linked view shows: the preview while there is one, else the lock. */
export function selectedDay(state: DayLockState): number | null {
  return state.hover ?? state.locked;
}

/** What a polite live region should say after a transition, if anything. */
export function lockTransition(prev: DayLockState, next: DayLockState): 'locked' | 'unlocked' | null {
  if (next.locked != null && next.locked !== prev.locked) return 'locked';
  if (next.locked == null && prev.locked != null) return 'unlocked';
  return null;
}

// --- Activity strip -----------------------------------------------------------

export interface ActivityMark {
  readonly index: number;
  readonly total: number;
  /** Height as a share of the busiest day, 0..1. */
  readonly share: number;
  readonly weekend: boolean;
  readonly selected: boolean;
  /** The day the reader locked (click, Enter or Space), whatever the preview shows. */
  readonly locked: boolean;
  readonly inSelectedWeek: boolean;
}

export interface ActivityWeek {
  /** First day index of the ISO week inside the window. */
  readonly start: number;
  /** One past the last day index of the week inside the window. */
  readonly end: number;
  readonly isoWeek: number;
  readonly selected: boolean;
}

export interface ActivityStrip {
  readonly marks: readonly ActivityMark[];
  readonly weeks: readonly ActivityWeek[];
  readonly selectedWeek: ActivityWeek | null;
  /** The week holding the locked day: the strip names it « Semaine verrouillée ». */
  readonly lockedWeek: ActivityWeek | null;
  readonly max: number;
}

type StripDay = Pick<HypervisorDayPoint, 'date' | 'measured' | 'declared' | 'weekend'>;

/**
 * One mark per day of the window, grouped in ISO weeks (Monday first). The
 * week holding the selected day is flagged so the strip can band it; the week
 * holding the locked day is returned apart, so a passing preview elsewhere
 * never renames it.
 */
export function activityStrip(
  days: readonly StripDay[],
  selected: number | null,
  locked: number | null = null,
): ActivityStrip {
  const totals = days.map((day) => Math.max(0, day.measured) + Math.max(0, day.declared));
  const max = totals.reduce((best, value) => Math.max(best, value), 0);
  const weeks: Array<{ start: number; end: number; isoWeek: number }> = [];
  days.forEach((day, index) => {
    const week = isoWeek(day.date);
    const last = weeks[weeks.length - 1];
    if (last && last.isoWeek === week && last.end === index) last.end = index + 1;
    else weeks.push({ start: index, end: index + 1, isoWeek: week });
  });
  const weekOf = (day: number | null) => day != null && day >= 0 && day < days.length
    ? weeks.find((week) => day >= week.start && day < week.end) ?? null
    : null;
  const hit = weekOf(selected);
  const lockHit = weekOf(locked);
  const shaped: ActivityWeek[] = weeks.map((week) => ({ ...week, selected: week === hit }));
  const selectedWeek = shaped.find((week) => week.selected) ?? null;
  const lockedWeek = lockHit ? shaped[weeks.indexOf(lockHit)] ?? null : null;
  return {
    max,
    weeks: shaped,
    selectedWeek,
    lockedWeek,
    marks: totals.map((total, index) => ({
      index,
      total,
      share: max > 0 ? total / max : 0,
      weekend: Boolean(days[index]!.weekend),
      selected: index === selected,
      locked: index === locked,
      inSelectedWeek: selectedWeek != null && index >= selectedWeek.start && index < selectedWeek.end,
    })),
  };
}

/**
 * Keyboard on the activity strip (a horizontal listbox, selection does not
 * follow focus): arrows walk one day, Page Up / Page Down a week, Home and
 * End jump to the ends. The strip reads left to right and does not wrap.
 */
export function stripKeyTarget(key: string, index: number, count: number): number | null {
  if (count <= 0) return null;
  const clamp = (value: number) => Math.min(count - 1, Math.max(0, value));
  switch (key) {
    case 'ArrowRight':
    case 'ArrowDown':
      return clamp(index + 1);
    case 'ArrowLeft':
    case 'ArrowUp':
      return clamp(index - 1);
    case 'PageDown':
      return clamp(index + 7);
    case 'PageUp':
      return clamp(index - 7);
    case 'Home':
      return 0;
    case 'End':
      return count - 1;
    default:
      return null;
  }
}

// --- Selection panel -----------------------------------------------------------

/** `locked`: pinned by the reader · `preview`: pointer or focus · `peak`: nothing selected, the busiest day. */
export type SelectionDayMode = 'locked' | 'preview' | 'peak';
/** `hover`/`pinned`: chosen by the reader · `day`: top system of the selected day · `period`: top of the window. */
export type SelectionSystemMode = 'hover' | 'pinned' | 'day' | 'period';

export interface SelectionDay {
  readonly mode: SelectionDayMode;
  readonly index: number;
  readonly point: HypervisorDayPoint;
  readonly total: number;
}

export interface SelectionRiverPart {
  readonly systemId: string;
  readonly label: string;
  readonly value: number;
  readonly declared: boolean;
}

export interface SelectionSystem {
  readonly mode: SelectionSystemMode;
  readonly row: HypervisorRegisterRow;
}

export interface SelectionModel {
  readonly day: SelectionDay | null;
  /** The same day in the rivers: one part per system with a non-zero value, largest first. */
  readonly rivers: readonly SelectionRiverPart[];
  readonly system: SelectionSystem | null;
}

export function selectionModel(
  view: Pick<HypervisorSeriesView, 'days' | 'peak' | 'streams' | 'register'> | null,
  lock: DayLockState,
  hoverSystem: string | null,
  pinnedSystem: string | null,
): SelectionModel {
  if (!view) return { day: null, rivers: [], system: null };
  const chosen = selectedDay(lock);
  let day: SelectionDay | null = null;
  const pick = (index: number, mode: SelectionDayMode): SelectionDay | null => {
    const point = view.days[index];
    return point ? { mode, index, point, total: point.measured + point.declared } : null;
  };
  if (chosen != null) day = pick(chosen, lock.hover != null && lock.hover !== lock.locked ? 'preview' : 'locked');
  if (!day && view.peak) day = pick(view.peak.index, 'peak');

  const rivers: SelectionRiverPart[] = day
    ? view.streams
      .map((row) => ({
        systemId: row.systemId,
        label: row.label,
        value: row.values[day!.index] ?? 0,
        declared: row.tone === 'declared' || row.tone === 'declared-soft',
      }))
      .filter((part) => part.value > 0)
      .sort((a, b) => b.value - a.value)
    : [];

  const byId = (id: string | null): HypervisorRegisterRow | null =>
    id ? view.register.find((row) => row.systemId === id) ?? null : null;
  let system: SelectionSystem | null = null;
  const hovered = byId(hoverSystem);
  const pinned = byId(pinnedSystem);
  if (hovered) system = { mode: 'hover', row: hovered };
  else if (pinned) system = { mode: 'pinned', row: pinned };
  else if (day && day.mode !== 'peak' && rivers.length) {
    const top = byId(rivers[0]!.systemId);
    if (top) system = { mode: 'day', row: top };
  }
  if (!system) {
    const top = [...view.register]
      .filter((row) => !row.outsideDenominator)
      .sort((a, b) => (availableNumber(b.hours) ?? 0) - (availableNumber(a.hours) ?? 0))[0];
    if (top) system = { mode: 'period', row: top };
  }
  return { day, rivers, system };
}
