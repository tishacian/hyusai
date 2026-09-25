/**
 * Arrival provenance via `history.state` (L10 contract). Not in the URL.
 * L21a uses it for « Depuis Observabilité › Traces » and « Depuis la trace {id} ».
 */
export const ARRIVAL_PROVENANCE_KEY = 'ckArrivalProvenance';

export type ArrivalProvenanceKind = 'observability_traces' | 'trace';

export interface ArrivalProvenance {
  kind: ArrivalProvenanceKind;
  /** Short id shown in « Depuis la trace {id} ». */
  traceId?: string;
  /** Absolute path (+ query) for « Revenir ». */
  backUrl?: string;
}

export function arrivalProvenanceState(
  provenance: ArrivalProvenance,
): Record<string, ArrivalProvenance> {
  return { [ARRIVAL_PROVENANCE_KEY]: provenance };
}

export function readArrivalProvenance(
  state: unknown = typeof history !== 'undefined' ? history.state : null,
): ArrivalProvenance | null {
  if (!state || typeof state !== 'object') return null;
  const raw = (state as Record<string, unknown>)[ARRIVAL_PROVENANCE_KEY];
  if (!raw || typeof raw !== 'object') return null;
  const kind = (raw as ArrivalProvenance).kind;
  if (kind !== 'observability_traces' && kind !== 'trace') return null;
  const traceId = (raw as ArrivalProvenance).traceId;
  const backUrl = (raw as ArrivalProvenance).backUrl;
  return {
    kind,
    ...(typeof traceId === 'string' && traceId ? { traceId } : {}),
    ...(typeof backUrl === 'string' && backUrl ? { backUrl } : {}),
  };
}

export function arrivalProvenanceLabel(
  provenance: ArrivalProvenance,
  t: (key: string, params?: Record<string, string | number>) => string,
): string {
  if (provenance.kind === 'trace') {
    const id = (provenance.traceId || '').slice(0, 12);
    return t('runs.provenance.from_trace', { id: id || '—' });
  }
  return t('runs.provenance.from_observability_traces');
}
