import type { MandateEvent, SystemMandate } from '@app/features/mandate/mandate.models';

export const MANDATE_FACETS = ['inbound', 'outbound', 'capabilities', 'provenance', 'valves'] as const;
export type MandateFacet = typeof MANDATE_FACETS[number];
export type CoverageState = 'recorded' | 'breached' | 'not_recorded';
export type MandateCoverageRun = Omit<SystemMandate['recent_runs'][number], 'facets'> & {
  facets?: Partial<Record<MandateFacet, {event_count: number; breach_count: number; state: CoverageState}>>;
};

/** A configured facet or snapshot is not a recorded control event. */
export function mandateCoverageCell(run: MandateCoverageRun, facet: MandateFacet) {
  const evidence = run.facets?.[facet];
  const count = evidence && Number.isInteger(evidence.event_count) && evidence.event_count > 0
    ? evidence.event_count : 0;
  const state: CoverageState = count === 0 ? 'not_recorded'
    : (evidence!.breach_count > 0 ? 'breached' : 'recorded');
  return {state, count};
}

export function mandateCoverageCounts(runs: MandateCoverageRun[]) {
  const cells = runs.flatMap(run => MANDATE_FACETS.map(facet => mandateCoverageCell(run, facet)));
  return {
    total: cells.length,
    recorded: cells.filter(cell => cell.state !== 'not_recorded').length,
    missing: cells.filter(cell => cell.state === 'not_recorded').length,
  };
}

/** Human decisions remain separate; selecting output conditions never invents a gate event. */
export function mandateFacetEvents(events: MandateEvent[], facet: MandateFacet | null) {
  return facet ? events.filter(event => event.facet === facet
    || (facet === 'capabilities' && event.facet === 'delegation')) : events;
}
