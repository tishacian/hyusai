import type { HypervisorRegisterRow } from './hypervisor-v2-series';
import type {
  DayLockState,
  SelectionDayMode,
  SelectionModel,
  SelectionRiverPart,
  SelectionSystemMode,
} from './impact-synthese';

/**
 * Présentation theme W2-v6: the same linked state as the Synthèse (day lock,
 * selection model), told for a room. Pure functions only, so the Escape order
 * and the chaîne de preuve are tested without Angular.
 */

// --- Pending decisions fact ------------------------------------------------------------

/**
 * The command band's « Décisions en attente » fact. A link only when there is
 * something to open: a known zero reads « aucune », not « 0 → »; a source
 * that has not answered keeps its own state label (caller's job).
 */
export type PendingDecisionsFact =
  | { readonly kind: 'state' }
  | { readonly kind: 'none' }
  | { readonly kind: 'open'; readonly count: number };

export function pendingDecisionsFact(sourceReady: boolean, count: number): PendingDecisionsFact {
  if (!sourceReady) return { kind: 'state' };
  return count > 0 ? { kind: 'open', count } : { kind: 'none' };
}

// --- Escape ---------------------------------------------------------------------

/**
 * Escape in the Présentation theme peels one layer at a time: a locked day
 * first (the room is still looking at it, and the unlock is announced), then
 * the theme itself on the next press. Without a lock, the first Escape leaves.
 */
export type PresentationEscape = 'unlock' | 'exit';

export function presentationEscape(lock: Pick<DayLockState, 'locked'>): PresentationEscape {
  return lock.locked != null ? 'unlock' : 'exit';
}

// --- Chaîne de preuve ------------------------------------------------------------

/** Who declared a system's value basis, and when, if the bases source says so. */
export interface ProofBasisAuthor {
  readonly by: string | null;
  readonly at: string | null;
}

/** 01 · the day: locked, previewed, or (nothing chosen) the busiest day. */
export interface ProofDay {
  readonly step: 1;
  readonly state: SelectionDayMode | 'none';
  readonly index: number | null;
  readonly date: string | null;
  readonly total: number;
  readonly runs: number;
  readonly systems: number;
}

/** 02 · the same day in the rivers: the largest parts first, the rest counted. */
export interface ProofRivers {
  readonly step: 2;
  readonly state: 'parts' | 'empty' | 'none';
  readonly parts: readonly SelectionRiverPart[];
  readonly more: number;
}

/** 03 · the system in the register, and why it is the one named. */
export interface ProofRegister {
  readonly step: 3;
  readonly state: 'row' | 'none';
  readonly mode: SelectionSystemMode | null;
  readonly row: HypervisorRegisterRow | null;
}

/** 04 · its value basis, with its author and date when known. */
export interface ProofBasis {
  readonly step: 4;
  readonly state: 'measured' | 'declared' | 'missing' | 'none';
  readonly by: string | null;
  readonly at: string | null;
}

export type ProofChain = readonly [ProofDay, ProofRivers, ProofRegister, ProofBasis];

/** Parts listed under 02 before the rest collapses into « et N autres ». */
export const PROOF_RIVER_PARTS = 3;

export function proofChain(
  selection: SelectionModel,
  basisAuthor: (row: HypervisorRegisterRow) => ProofBasisAuthor | null,
  maxParts = PROOF_RIVER_PARTS,
): ProofChain {
  const day = selection.day;
  const proofDay: ProofDay = day
    ? {
      step: 1,
      state: day.mode,
      index: day.index,
      date: day.point.date,
      total: day.total,
      runs: day.point.runs,
      systems: day.point.systems,
    }
    : { step: 1, state: 'none', index: null, date: null, total: 0, runs: 0, systems: 0 };

  const parts = selection.rivers.slice(0, Math.max(0, maxParts));
  const rivers: ProofRivers = !day
    ? { step: 2, state: 'none', parts: [], more: 0 }
    : parts.length
      ? { step: 2, state: 'parts', parts, more: selection.rivers.length - parts.length }
      : { step: 2, state: 'empty', parts: [], more: 0 };

  const sys = selection.system;
  const register: ProofRegister = sys
    ? { step: 3, state: 'row', mode: sys.mode, row: sys.row }
    : { step: 3, state: 'none', mode: null, row: null };

  let basis: ProofBasis = { step: 4, state: 'none', by: null, at: null };
  if (sys) {
    const status = sys.row.basisStatus;
    const author = basisAuthor(sys.row);
    basis = {
      step: 4,
      state: status === 'measured' || status === 'declared' ? status : 'missing',
      by: author?.by || null,
      at: author?.at || null,
    };
  }
  return [proofDay, rivers, register, basis];
}
