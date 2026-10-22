import { RUNS_FR, RUNS_EN } from '@app/core/i18n/runs.dict';
/** Stable navigation: historical facets remain addressable within Result. */
export type RunSection = 'result' | 'execution' | 'quality' | 'usage';
export function runSection(view: string | null, facet: string | null): RunSection {
  if (view === 'flow' || facet === 'trace') return 'execution';
  return facet === 'quality' || facet === 'usage' ? facet : 'result';
}
export const RUN_SECTION_LABELS = {
  fr: { result: RUNS_FR['runs.sections.result'], execution: RUNS_FR['runs.sections.execution'], quality: RUNS_FR['runs.sections.quality'], usage: RUNS_FR['runs.sections.usage'], technical: RUNS_FR['runs.sections.technical'], mandate: RUNS_FR['runs.sections.mandate'], flow: RUNS_FR['runs.sections.flow'], timeline: RUNS_FR['runs.sections.timeline'], value: RUNS_FR['runs.sections.value'] },
  en: { result: RUNS_EN['runs.sections.result'], execution: RUNS_EN['runs.sections.execution'], quality: RUNS_EN['runs.sections.quality'], usage: RUNS_EN['runs.sections.usage'], technical: RUNS_EN['runs.sections.technical'], mandate: RUNS_EN['runs.sections.mandate'], flow: RUNS_EN['runs.sections.flow'], timeline: RUNS_EN['runs.sections.timeline'], value: RUNS_EN['runs.sections.value'] },
} as const;
export function runSectionLabels(locale: string) { return RUN_SECTION_LABELS[locale.startsWith('fr') ? 'fr' : 'en']; }
