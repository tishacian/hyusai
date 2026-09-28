import { of, type Observable } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import type { ApiService } from '@app/core/api.service';
import type {
  DecisionRow,
  HypervisorValueBasisItem,
  Recommendation,
} from '@app/core/canonical-api.service';
import type { HypervisorSeriesResponse } from './hypervisor-v2-series';

/**
 * The Impact data sources that each feed their own blocks.
 *
 * Each one loads and fails on its own: a failed source leaves its blocks in
 * an `unavailable` state and the other blocks keep rendering. A failure is
 * never shown as an empty list or a zero.
 */
export type ImpactSourceId = 'series' | 'bases' | 'decisions' | 'recos';
export type ImpactSourceState = 'loading' | 'ready' | 'unavailable';
export type ImpactSourceStates = Readonly<Record<ImpactSourceId, ImpactSourceState>>;

export const IMPACT_SOURCES: readonly ImpactSourceId[] = ['series', 'bases', 'decisions', 'recos'];

export const LOADING_SOURCES: ImpactSourceStates = Object.freeze({
  series: 'loading',
  bases: 'loading',
  decisions: 'loading',
  recos: 'loading',
});

export type SourceOutcome<T> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly status: number | null };

export interface ImpactSourceValues {
  series: HypervisorSeriesResponse | null;
  bases: HypervisorValueBasisItem[];
  decisions: DecisionRow[];
  recos: Recommendation[];
}

export type ImpactSourceRequests = { readonly [K in ImpactSourceId]: () => Observable<ImpactSourceValues[K]> };

/** Turns a request into an outcome that never errors, keeping the HTTP status. */
export function settleSource<T>(request: Observable<T>): Observable<SourceOutcome<T>> {
  return request.pipe(
    map((value): SourceOutcome<T> => ({ ok: true, value })),
    catchError((error: unknown) => of<SourceOutcome<T>>({ ok: false, status: httpStatus(error) })),
  );
}

/**
 * Raw requests for the Impact sources.
 *
 * `CanonicalApiService` turns a failure into `null` or `[]`, which Impact
 * would then render as "no decision" or "no series". These calls let the
 * error through so `settleSource` can tell a failure from an empty answer.
 */
export function impactSourceRequests(
  http: Pick<ApiService, 'get'>,
  window: '30d' | '90d',
): ImpactSourceRequests {
  return {
    series: () => http.get<HypervisorSeriesResponse | null>('/hypervisor/series', { window }),
    bases: () => http
      .get<{ items?: HypervisorValueBasisItem[] } | null>('/hypervisor/value-bases')
      .pipe(map((body) => body?.items ?? [])),
    decisions: () => http
      .get<{ items?: DecisionRow[] } | null>('/hypervisor/decisions', { limit: '20' })
      .pipe(map((body) => body?.items ?? [])),
    recos: () => http
      .get<{ items?: Recommendation[] } | null>('/hypervisor/recommendations')
      .pipe(map((body) => body?.items ?? [])),
  };
}

/**
 * The page-level problem, when there is one: access to the series is denied,
 * or every source failed. Any other failure stays inside its own block.
 */
export function impactPageProblem(
  outcomes: Readonly<Record<ImpactSourceId, SourceOutcome<unknown>>>,
): string | null {
  const series = outcomes.series;
  if (!series.ok && series.status === 403) return 'experience.adoption.access_denied';
  if (IMPACT_SOURCES.every((id) => !outcomes[id].ok)) return 'experience.adoption.load_failed';
  return null;
}

export function withSourceState(
  states: ImpactSourceStates,
  id: ImpactSourceId,
  state: ImpactSourceState,
): ImpactSourceStates {
  return states[id] === state ? states : Object.freeze({ ...states, [id]: state });
}

function httpStatus(error: unknown): number | null {
  if (typeof error !== 'object' || error === null) return null;
  const status = (error as { status?: unknown }).status;
  return typeof status === 'number' ? status : null;
}
