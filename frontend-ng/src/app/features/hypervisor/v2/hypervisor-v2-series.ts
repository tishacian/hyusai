export const STALE_AFTER_DAYS = 7;

export type SeriesFactState =
  | 'available'
  | 'not_measured'
  | 'not_configured'
  | 'restricted'
  | 'unavailable';

export type HypervisorDenominator = 'hours' | 'units' | 'value';
export type HypervisorSeriesWindow = '30d' | '90d';
export type ValueBasisStatus = 'declared' | 'measured' | 'none';
export type RegisterHealth = 'pos' | 'warn' | 'neg' | 'neutral';
export type StreamTone = 'ink' | 'declared' | 'declared-soft';

export interface SeriesFact {
  state: SeriesFactState;
  value: number | null;
  unit?: string;
}

export interface ValueBasis {
  unit: string | null;
  hours_per_unit: number | null;
  value_per_unit: number | null;
  currency: string | null;
  declared_by: string | null;
  declared_at: string | null;
  status: ValueBasisStatus;
  note: string | null;
}

export interface HypervisorSeriesBucket {
  date: string;
  runs: SeriesFact;
  outcomes: SeriesFact;
  cost: SeriesFact;
  hours: SeriesFact;
  value_declared: SeriesFact;
}

export interface HypervisorSeriesSystem {
  system_id: string;
  capability_id: string | null;
  name: string;
  output_unit: string | null;
  value_basis: ValueBasis | null;
  days_since_last_run: SeriesFact;
  buckets: HypervisorSeriesBucket[];
}

export interface HypervisorSeriesResponse {
  window: HypervisorSeriesWindow;
  from: string;
  to: string;
  authorization_scope?: Record<string, unknown>;
  systems: HypervisorSeriesSystem[];
}

export interface HypervisorDayPoint {
  date: string;
  weekday: number;
  weekend: boolean;
  measured: number;
  declared: number;
}

export interface HypervisorChartTick {
  index: number;
  label: string;
  anchor?: 'start' | 'middle' | 'end';
}

export interface HypervisorStreamRow {
  systemId: string;
  label: string;
  values: number[];
  tone: StreamTone;
}

export interface HypervisorSankeyRow {
  systemId: string;
  capabilityId: string | null;
  label: string;
  detail?: string;
  value: number;
  outsideDenominator: boolean;
}

export interface HypervisorRegisterRow {
  systemId: string;
  capabilityId: string | null;
  name: string;
  initials: string;
  health: RegisterHealth;
  daysSinceLastRun: SeriesFact;
  outputUnit: string | null;
  weekSpark: number[];
  cost: SeriesFact;
  hours: SeriesFact;
  valueDeclared: SeriesFact;
  outcomes: SeriesFact;
  runs: SeriesFact;
  basisStatus: ValueBasisStatus | null;
  currency: string | null;
  outsideDenominator: boolean;
}

export interface HypervisorSeriesView {
  window: HypervisorSeriesWindow;
  from: string;
  to: string;
  dates: string[];
  days: HypervisorDayPoint[];
  weekendStarts: number[];
  ticks: HypervisorChartTick[];
  peak: { index: number; date: string; total: number } | null;
  monument: SeriesFact;
  measuredTotal: number;
  declaredTotal: number;
  costTotal: SeriesFact;
  valueTotal: SeriesFact;
  hoursTotal: SeriesFact;
  unitsTotal: SeriesFact;
  ratio: SeriesFact;
  currency: string | null;
  streams: HypervisorStreamRow[];
  costStreams: HypervisorStreamRow[];
  sankey: HypervisorSankeyRow[];
  register: HypervisorRegisterRow[];
  outside: HypervisorRegisterRow[];
  staleSystemIds: string[];
  pulseValues: number[];
  staleFrom: number | null;
}

export function dateKey(iso: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso;
  const raw = iso.includes('T') && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? `${iso}Z` : iso;
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return iso.slice(0, 10);
  return parsed.toISOString().slice(0, 10);
}

export function buildCalendar(from: string, to: string): string[] {
  const start = dateKey(from);
  const end = dateKey(to);
  const days: string[] = [];
  const cursor = new Date(`${start}T00:00:00Z`);
  const last = new Date(`${end}T00:00:00Z`);
  while (cursor.getTime() <= last.getTime()) {
    days.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return days;
}

export function availableNumber(fact: SeriesFact | null | undefined): number | null {
  if (!fact || fact.state !== 'available' || fact.value == null || !Number.isFinite(fact.value)) {
    return null;
  }
  return fact.value;
}

export function hasHoursBasis(basis: ValueBasis | null | undefined): boolean {
  return Boolean(basis && basis.status !== 'none' && basis.hours_per_unit != null);
}

export function hasValueBasis(basis: ValueBasis | null | undefined): boolean {
  return Boolean(basis && basis.status !== 'none' && basis.value_per_unit != null);
}

export function isOutsideDenominator(
  system: Pick<HypervisorSeriesSystem, 'value_basis'>,
  denominator: HypervisorDenominator,
): boolean {
  if (denominator === 'hours') return !hasHoursBasis(system.value_basis);
  if (denominator === 'value') return !hasValueBasis(system.value_basis);
  return false;
}

export function foldFacts(facts: readonly SeriesFact[]): SeriesFact {
  const available: number[] = [];
  let sawNotConfigured = false;
  let sawRestricted = false;
  let sawUnavailable = false;
  for (const fact of facts) {
    const value = availableNumber(fact);
    if (value != null) available.push(value);
    else if (fact.state === 'not_configured') sawNotConfigured = true;
    else if (fact.state === 'restricted') sawRestricted = true;
    else if (fact.state === 'unavailable') sawUnavailable = true;
  }
  if (available.length > 0) {
    return { state: 'available', value: available.reduce((sum, item) => sum + item, 0) };
  }
  if (sawNotConfigured) return { state: 'not_configured', value: null };
  if (sawRestricted) return { state: 'restricted', value: null };
  if (sawUnavailable) return { state: 'unavailable', value: null };
  return { state: 'not_measured', value: null };
}

export function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0]![0] ?? ''}${parts[1]![0] ?? ''}`.toUpperCase();
  return name.trim().slice(0, 2).toUpperCase();
}

export function healthFor(daysSince: SeriesFact): RegisterHealth {
  const days = availableNumber(daysSince);
  if (days == null) return 'neutral';
  if (days <= 3) return 'pos';
  if (days < STALE_AFTER_DAYS) return 'warn';
  return 'neg';
}

export function weekSpark(daily: readonly number[]): number[] {
  const weeks: number[] = [];
  for (let end = daily.length; end > 0; ) {
    const start = Math.max(0, end - 7);
    let total = 0;
    for (let i = start; i < end; i += 1) total += daily[i] ?? 0;
    weeks.unshift(total);
    end = start;
  }
  return weeks.slice(-10);
}

export function sortRegisterRows(
  rows: readonly HypervisorRegisterRow[],
  sort: string,
): HypervisorRegisterRow[] {
  const copy = [...rows];
  copy.sort((left, right) => {
    switch (sort) {
      case 'value':
        return compareNullableDesc(
          availableNumber(left.valueDeclared),
          availableNumber(right.valueDeclared),
        ) || left.name.localeCompare(right.name);
      case 'cost':
        return compareNullableDesc(
          availableNumber(left.cost),
          availableNumber(right.cost),
        ) || left.name.localeCompare(right.name);
      case 'days_since_last_run':
        return compareNullableDesc(
          availableNumber(left.daysSinceLastRun),
          availableNumber(right.daysSinceLastRun),
        ) || left.name.localeCompare(right.name);
      default:
        return left.name.localeCompare(right.name);
    }
  });
  return copy;
}

export function projectSeries(
  payload: HypervisorSeriesResponse,
  denominator: HypervisorDenominator,
): HypervisorSeriesView {
  const dates = buildCalendar(payload.from, payload.to);
  const systems = payload.systems ?? [];
  const register = systems.map((system) => projectRegisterRow(system, dates, denominator));
  const days = dates.map((date, index) => projectDay(date, index, systems, denominator));
  const measuredTotal = days.reduce((sum, day) => sum + day.measured, 0);
  const declaredTotal = days.reduce((sum, day) => sum + day.declared, 0);
  const inDenominator = register.filter((row) => !row.outsideDenominator);
  const monument = inDenominator.length === 0 && (denominator === 'hours' || denominator === 'value')
    ? { state: 'not_configured' as const, value: null }
    : { state: 'available' as const, value: measuredTotal + declaredTotal };

  const costTotal = foldFacts(register.map((row) => row.cost));
  const valueTotal = foldFacts(register.map((row) => row.valueDeclared));
  const hoursTotal = foldFacts(register.map((row) => row.hours));
  const unitsTotal = foldFacts(register.map((row) => row.outcomes));
  const costValue = availableNumber(costTotal);
  const declaredValue = availableNumber(valueTotal);
  const ratio = costValue != null && costValue > 0 && declaredValue != null
    ? { state: 'available' as const, value: declaredValue / costValue }
    : costTotal.state === 'not_configured' || valueTotal.state === 'not_configured'
      ? { state: 'not_configured' as const, value: null }
      : { state: 'not_measured' as const, value: null };

  let peak: HypervisorSeriesView['peak'] = null;
  for (let i = 0; i < days.length; i += 1) {
    const total = days[i]!.measured + days[i]!.declared;
    if (total <= 0) continue;
    if (!peak || total > peak.total) peak = { index: i, date: days[i]!.date, total };
  }

  const pulseValues = dates.map((date) => {
    let runs = 0;
    for (const system of systems) {
      const value = availableNumber(bucketOn(system, date)?.runs);
      if (value != null) runs += value;
    }
    return runs;
  });

  return {
    window: payload.window,
    from: payload.from,
    to: payload.to,
    dates,
    days,
    weekendStarts: dates.flatMap((date, index) => (weekdayUtc(date) === 6 ? [index] : [])),
    ticks: weekTicks(dates),
    peak,
    monument,
    measuredTotal,
    declaredTotal,
    costTotal,
    valueTotal,
    hoursTotal,
    unitsTotal,
    ratio,
    currency: firstCurrency(systems),
    streams: inDenominator.map((row) => ({
      systemId: row.systemId,
      label: row.name,
      values: dailyMetric(systems.find((system) => system.system_id === row.systemId)!, dates, denominator),
      tone: row.basisStatus === 'measured' ? 'ink' : 'declared',
    })),
    costStreams: register
      .filter((row) => row.cost.state === 'available')
      .map((row) => ({
        systemId: row.systemId,
        label: row.name,
        values: dailyCost(systems.find((system) => system.system_id === row.systemId)!, dates),
        tone: 'ink' as const,
      })),
    sankey: register
      .map((row) => ({
        systemId: row.systemId,
        capabilityId: row.capabilityId,
        label: row.name,
        detail: row.outputUnit ?? undefined,
        value: sankeyValue(row, denominator),
        outsideDenominator: row.outsideDenominator,
      }))
      .filter((row) => row.outsideDenominator || row.value > 0),
    register,
    outside: register.filter((row) => row.outsideDenominator),
    staleSystemIds: register
      .filter((row) => {
        const daysSince = availableNumber(row.daysSinceLastRun);
        return daysSince != null && daysSince >= STALE_AFTER_DAYS;
      })
      .map((row) => row.systemId),
    pulseValues,
    staleFrom: trailingQuietFrom(pulseValues),
  };
}

function projectRegisterRow(
  system: HypervisorSeriesSystem,
  dates: readonly string[],
  denominator: HypervisorDenominator,
): HypervisorRegisterRow {
  const daily = dates.map((date) => dailySystemMetric(system, date, denominator));
  return {
    systemId: system.system_id,
    capabilityId: system.capability_id,
    name: system.name,
    initials: initialsFor(system.name),
    health: healthFor(system.days_since_last_run),
    daysSinceLastRun: system.days_since_last_run,
    outputUnit: system.output_unit,
    weekSpark: weekSpark(daily),
    cost: foldFacts(dates.map((date) => bucketOn(system, date)?.cost ?? emptyDayCost())),
    hours: foldConfigured(system, dates, 'hours', hasHoursBasis(system.value_basis)),
    valueDeclared: foldConfigured(system, dates, 'value_declared', hasValueBasis(system.value_basis)),
    outcomes: foldFacts(dates.map((date) => bucketOn(system, date)?.outcomes ?? zeroAvailable())),
    runs: foldFacts(dates.map((date) => bucketOn(system, date)?.runs ?? zeroAvailable())),
    basisStatus: system.value_basis?.status ?? null,
    currency: system.value_basis?.currency ?? null,
    outsideDenominator: isOutsideDenominator(system, denominator),
  };
}

function projectDay(
  date: string,
  _index: number,
  systems: readonly HypervisorSeriesSystem[],
  denominator: HypervisorDenominator,
): HypervisorDayPoint {
  const weekday = weekdayUtc(date);
  let measured = 0;
  let declared = 0;
  for (const system of systems) {
    if (isOutsideDenominator(system, denominator)) continue;
    const value = dailySystemMetric(system, date, denominator);
    if (system.value_basis?.status === 'measured') measured += value;
    else declared += value;
  }
  return { date, weekday, weekend: weekday === 0 || weekday === 6, measured, declared };
}

function dailyMetric(
  system: HypervisorSeriesSystem,
  dates: readonly string[],
  denominator: HypervisorDenominator,
): number[] {
  return dates.map((date) => dailySystemMetric(system, date, denominator));
}

function dailyCost(system: HypervisorSeriesSystem, dates: readonly string[]): number[] {
  return dates.map((date) => {
    const bucket = bucketOn(system, date);
    if (!bucket) return 0;
    return availableNumber(bucket.cost) ?? 0;
  });
}

function dailySystemMetric(
  system: HypervisorSeriesSystem,
  date: string,
  denominator: HypervisorDenominator,
): number {
  const bucket = bucketOn(system, date);
  if (!bucket) return 0;
  if (denominator === 'hours') return availableNumber(bucket.hours) ?? 0;
  if (denominator === 'value') return availableNumber(bucket.value_declared) ?? 0;
  return availableNumber(bucket.outcomes) ?? 0;
}

function sankeyValue(row: HypervisorRegisterRow, denominator: HypervisorDenominator): number {
  if (denominator === 'hours') return availableNumber(row.hours) ?? 0;
  if (denominator === 'value') return availableNumber(row.valueDeclared) ?? 0;
  return availableNumber(row.outcomes) ?? 0;
}

function foldConfigured(
  system: HypervisorSeriesSystem,
  dates: readonly string[],
  key: 'hours' | 'value_declared',
  configured: boolean,
): SeriesFact {
  if (!configured) return { state: 'not_configured', value: null };
  return foldFacts(dates.map((date) => bucketOn(system, date)?.[key] ?? zeroAvailable()));
}

function emptyDayCost(): SeriesFact {
  return { state: 'not_measured', value: null };
}

function zeroAvailable(): SeriesFact {
  return { state: 'available', value: 0 };
}

function bucketOn(system: HypervisorSeriesSystem, date: string): HypervisorSeriesBucket | undefined {
  return system.buckets.find((bucket) => bucket.date === date);
}

function weekdayUtc(date: string): number {
  return new Date(`${date}T00:00:00Z`).getUTCDay();
}

function weekTicks(dates: readonly string[]): HypervisorChartTick[] {
  const ticks: HypervisorChartTick[] = [];
  for (let i = 0; i < dates.length; i += 7) {
    ticks.push({
      index: i,
      label: dates[i]!.slice(5),
      anchor: i === 0 ? 'start' : 'middle',
    });
  }
  return ticks;
}

function firstCurrency(systems: readonly HypervisorSeriesSystem[]): string | null {
  for (const system of systems) {
    const currency = system.value_basis?.currency;
    if (currency) return currency;
  }
  return null;
}

function trailingQuietFrom(values: readonly number[]): number | null {
  let lastActive = -1;
  for (let i = 0; i < values.length; i += 1) {
    if ((values[i] ?? 0) > 0) lastActive = i;
  }
  if (lastActive < 0) return 0;
  const quiet = values.length - 1 - lastActive;
  return quiet >= STALE_AFTER_DAYS ? lastActive + 1 : null;
}

function compareNullableDesc(left: number | null, right: number | null): number {
  if (left == null && right == null) return 0;
  if (left == null) return 1;
  if (right == null) return -1;
  return right - left;
}
