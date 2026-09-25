/**
 * Arrival provenance via `history.state` (L10 contract). Not in the URL.
 * Used for traces (L21a), Impact ↔ System (UX-006), and stripped `?lens=hypervisor` (UX-010).
 */
export const ARRIVAL_PROVENANCE_KEY = 'ckArrivalProvenance';

export type ArrivalProvenanceKind =
  | 'observability_traces'
  | 'trace'
  | 'system'
  | 'object'
  | 'impact_registre'
  | 'see_in_impact';

export interface ArrivalProvenance {
  kind: ArrivalProvenanceKind;
  /** Short id shown in « Depuis la trace {id} ». */
  traceId?: string;
  /** Display name for « Depuis {name} » (system / object). */
  label?: string;
  /** System id for register highlight when arriving on Impact. */
  systemId?: string;
  /** Absolute path (+ query) for « Revenir ». */
  backUrl?: string;
}

const KNOWN_KINDS = new Set<ArrivalProvenanceKind>([
  'observability_traces',
  'trace',
  'system',
  'object',
  'impact_registre',
  'see_in_impact',
]);

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
  if (!KNOWN_KINDS.has(kind)) return null;
  const traceId = (raw as ArrivalProvenance).traceId;
  const label = (raw as ArrivalProvenance).label;
  const systemId = (raw as ArrivalProvenance).systemId;
  const backUrl = (raw as ArrivalProvenance).backUrl;
  return {
    kind,
    ...(typeof traceId === 'string' && traceId ? { traceId } : {}),
    ...(typeof label === 'string' && label ? { label } : {}),
    ...(typeof systemId === 'string' && systemId ? { systemId } : {}),
    ...(typeof backUrl === 'string' && backUrl ? { backUrl } : {}),
  };
}

/** « Depuis … » fragment (without ↰ / Revenir). */
export function arrivalProvenanceFromLabel(
  provenance: ArrivalProvenance,
  t: (key: string, params?: Record<string, string | number>) => string,
): string {
  switch (provenance.kind) {
    case 'trace': {
      const id = (provenance.traceId || '').slice(0, 12);
      return t('runs.provenance.from_trace', { id: id || '—' });
    }
    case 'observability_traces':
      return t('runs.provenance.from_observability_traces');
    case 'system':
    case 'object':
      return t('nav.provenance.from_system', {
        name: provenance.label || provenance.systemId || '—',
      });
    case 'impact_registre':
      return t('nav.provenance.from_impact_registre');
    case 'see_in_impact':
      return t('nav.provenance.see_in_impact');
    default:
      return '';
  }
}

/**
 * Full chip label. Back kinds: « ↰ Depuis … · Revenir ».
 * Forward (`see_in_impact`): « Voir dans Impact ».
 */
export function arrivalProvenanceLabel(
  provenance: ArrivalProvenance,
  t: (key: string, params?: Record<string, string | number>) => string,
): string {
  if (provenance.kind === 'see_in_impact') {
    return t('nav.provenance.see_in_impact');
  }
  return t('nav.provenance.chip', { from: arrivalProvenanceFromLabel(provenance, t) });
}

export function arrivalProvenanceIsForward(provenance: ArrivalProvenance): boolean {
  return provenance.kind === 'see_in_impact';
}
