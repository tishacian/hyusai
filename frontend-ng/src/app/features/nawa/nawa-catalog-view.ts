/**
 * NAWA WE — what the catalogue screen reads out of one extracted entry.
 *
 * Pure, framework-free logic so the wording rules below can be exercised
 * against the strings the extractor actually produces
 * (`nawa-catalog-view.spec.ts`). The asset is generated with a banned-brand
 * guard and is never edited by hand, so everything here is presentation: it
 * decides what a line means, never what it says.
 */
import type { NawaUseCase } from './nawa-itsd.model';

/**
 * How availability is worded. A service desk catalogue states what one can
 * request today; it does not stamp every other entry as missing, which is what
 * a "planned" chip on thirty-eight rows amounts to.
 */
export const NAWA_AVAILABILITY: Readonly<Record<NawaUseCase['status'], string>> = {
  live: 'Available',
  planned: 'In the rollout plan',
};

/**
 * A staffing tally as the workbook writes it: a short label, a count, nothing
 * else — "Main Flow: 9 Agents", "Total Agents: 5", "Completed: 1", and the two
 * rows the author left blank.
 *
 * The narrative branches of the same field open on the very same kind of label
 * ("Rejected: NAWA WE notifies the requester…"), so the rule can only key on
 * what follows the colon carrying no prose. Getting that backwards would drop a
 * branch of the described process from the screen.
 */
const STAFFING_LINE = /^[^:]{1,40}:[ \t]*(?:[—–-]|\d+(?:[.,]\d+)?)?[ \t]*(?:agents?)?[ \t]*$/i;

export function isStaffingLine(line: string): boolean {
  return STAFFING_LINE.test(line.trim());
}

function textLines(value: string | null | undefined): string[] {
  return (value ?? '')
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/** What the process does, with the agent counts held back. */
export function narrativeLines(value: string | null | undefined): string[] {
  return textLines(value).filter((line) => !isStaffingLine(line));
}

/** The agent counts alone — business case material, not catalogue material. */
export function staffingLines(value: string | null | undefined): string[] {
  return textLines(value).filter((line) => isStaffingLine(line));
}

/**
 * The one plain line a catalogue card shows under the service name.
 *
 * Two entries of the workbook carry no process text at all. The card then says
 * nothing, rather than turn a name into a promise nobody wrote.
 */
export function serviceSummary(item: NawaUseCase): string {
  return narrativeLines(item.automated_process)[0] ?? '';
}

/** Search runs over the same text in both views. */
export function matchesQuery(item: NawaUseCase, needle: string): boolean {
  if (!needle) return true;
  return `${item.sr} ${item.name} ${item.manual_process} ${item.automated_process}`
    .toLowerCase()
    .includes(needle);
}

export interface NawaBusinessTotals {
  services: number;
  agents: number;
  monthlyVolume: number;
  available: number;
}

/** Totals for the business case view, over whatever is currently listed. */
export function businessTotals(items: readonly NawaUseCase[]): NawaBusinessTotals {
  return {
    services: items.length,
    agents: items.reduce((sum, item) => sum + (item.agents ?? 0), 0),
    monthlyVolume: Math.round(items.reduce((sum, item) => sum + (item.monthly_volume ?? 0), 0)),
    available: items.filter((item) => item.status === 'live').length,
  };
}

function ratio(item: NawaUseCase): number | null {
  const legacy = item.legacy_minutes;
  const target = item.automated_minutes;
  if (typeof legacy !== 'number' || typeof target !== 'number') return null;
  if (legacy <= 0 || target <= 0) return null;
  return legacy / target;
}

/**
 * Acceleration targeted by the customer's own plan, derived from its two time
 * columns. No absolute duration is shown: the workbook annotates the target
 * column with "Time in hours" while the legacy column is declared in minutes,
 * so printing either unit would be a claim we cannot back.
 *
 * A ratio only survives that ambiguity if it refuses to speak when the two
 * numbers do not support a claim. Anything at or below parity renders as
 * parity or a dash instead of a multiplier, so if the columns turned out to
 * carry different units every row would degrade to that rather than show a
 * confident wrong figure.
 */
export function speedupLabel(item: NawaUseCase): string {
  const value = ratio(item);
  if (value === null || value < 0.95) return '—';
  if (value < 1.05) return 'at parity';
  // One outlier compares a multi-week calendar delay to a handling time.
  // Beyond two orders of magnitude the figure stops informing anyone.
  if (value >= 100) return '> 100× faster';
  const rounded = value < 10 ? value.toFixed(1).replace(/\.0$/, '') : String(Math.round(value));
  return `~${rounded}× faster`;
}

export function hasSpeedup(item: NawaUseCase): boolean {
  const value = ratio(item);
  return value !== null && value >= 1.05;
}
