export type HypervisorViewDenominator = 'hours' | 'runs' | 'value';
export type HypervisorViewPeriod = '30d' | '90d';
export type HypervisorStratumId = 'comprendre' | 'detailler' | 'decider';

export const COMPRENDRE_BLOCKS = [
  'monument',
  'provenance',
  'cadran',
  'sankey',
  'rivers',
  'hors_denominateur',
  'unites',
  'couverture',
  'signal',
  'decisions',
] as const;

export const DETAILLER_BLOCKS = ['registre'] as const;
export const DECIDER_BLOCKS = ['signal', 'decisions'] as const;
export const REGISTER_COLUMNS = ['unit', 'spark', 'cost', 'basis', 'value'] as const;
export const VIEW_SORTS = ['value', 'name', 'days_since_last_run', 'cost'] as const;

export type ComprendreBlock = (typeof COMPRENDRE_BLOCKS)[number];
export type DetaillerBlock = (typeof DETAILLER_BLOCKS)[number];
export type DeciderBlock = (typeof DECIDER_BLOCKS)[number];
export type RegisterColumn = (typeof REGISTER_COLUMNS)[number];
export type ViewSort = (typeof VIEW_SORTS)[number];

export interface HypervisorViewStrata {
  comprendre: string[];
  detailler: string[];
  decider: string[];
}

export interface HypervisorNamedView {
  id: string;
  label: string;
  denominator: HypervisorViewDenominator;
  period: string;
  strata: HypervisorViewStrata;
  register_columns: string[];
  sort: string;
}

export interface HypervisorViewsPayload {
  views: HypervisorNamedView[];
  can_edit: boolean;
}

export const DEFAULT_HYPERVISOR_VIEWS: readonly HypervisorNamedView[] = [
  {
    id: 'direction',
    label: 'Direction',
    denominator: 'hours',
    period: '90d',
    strata: {
      comprendre: ['monument', 'provenance', 'cadran', 'sankey', 'rivers', 'hors_denominateur'],
      detailler: [...DETAILLER_BLOCKS],
      decider: [...DECIDER_BLOCKS],
    },
    register_columns: [...REGISTER_COLUMNS],
    sort: 'value',
  },
  {
    id: 'operations',
    label: 'Operations',
    denominator: 'runs',
    period: '30d',
    strata: {
      comprendre: ['monument', 'cadran', 'rivers', 'signal'],
      detailler: ['registre'],
      decider: [],
    },
    register_columns: ['unit', 'spark'],
    sort: 'days_since_last_run',
  },
  {
    id: 'conformite',
    label: 'Conformite',
    denominator: 'runs',
    period: '90d',
    strata: {
      comprendre: ['unites', 'couverture', 'decisions'],
      detailler: ['registre'],
      decider: [],
    },
    register_columns: ['unit', 'basis'],
    sort: 'name',
  },
];

export function cloneView(view: HypervisorNamedView): HypervisorNamedView {
  return {
    ...view,
    strata: {
      comprendre: [...view.strata.comprendre],
      detailler: [...view.strata.detailler],
      decider: [...view.strata.decider],
    },
    register_columns: [...view.register_columns],
  };
}

export function replaceView(
  views: readonly HypervisorNamedView[],
  next: HypervisorNamedView,
): HypervisorNamedView[] {
  const found = views.some((view) => view.id === next.id);
  if (!found) return [...views, cloneView(next)];
  return views.map((view) => (view.id === next.id ? cloneView(next) : view));
}

export function viewPeriod(view: HypervisorNamedView | null | undefined): HypervisorViewPeriod {
  return view?.period === '90d' ? '90d' : '30d';
}

export function viewDenominator(view: HypervisorNamedView | null | undefined): HypervisorViewDenominator {
  const value = view?.denominator as string | undefined;
  if (value === 'value') return 'value';
  if (value === 'runs' || value === 'units') return 'runs';
  return 'hours';
}

export function showsBlock(view: HypervisorNamedView | null | undefined, stratum: HypervisorStratumId, block: string): boolean {
  return Boolean(view?.strata[stratum]?.includes(block));
}

export function showsColumn(view: HypervisorNamedView | null | undefined, column: string): boolean {
  return Boolean(view?.register_columns.includes(column));
}

export function toggleStratumBlock(
  view: HypervisorNamedView,
  stratum: HypervisorStratumId,
  block: string,
): HypervisorNamedView {
  const next = cloneView(view);
  const list = next.strata[stratum];
  const index = list.indexOf(block);
  if (index >= 0) list.splice(index, 1);
  else list.push(block);
  return next;
}

export function moveStratumBlock(
  view: HypervisorNamedView,
  stratum: HypervisorStratumId,
  block: string,
  direction: -1 | 1,
): HypervisorNamedView {
  const next = cloneView(view);
  const list = next.strata[stratum];
  const index = list.indexOf(block);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= list.length) return next;
  const [item] = list.splice(index, 1);
  list.splice(target, 0, item!);
  return next;
}

export function toggleRegisterColumn(view: HypervisorNamedView, column: string): HypervisorNamedView {
  const next = cloneView(view);
  const index = next.register_columns.indexOf(column);
  if (index >= 0) next.register_columns.splice(index, 1);
  else next.register_columns.push(column);
  return next;
}

export function parseViewsPayload(
  raw: { views?: readonly RawNamedView[]; can_edit?: boolean } | null | undefined,
): HypervisorViewsPayload {
  const views = raw?.views?.length ? raw.views.map(normalizeView) : DEFAULT_HYPERVISOR_VIEWS.map(cloneView);
  return { views, can_edit: raw?.can_edit === true };
}

interface RawNamedView {
  id: string;
  label: string;
  denominator?: string;
  period?: string;
  strata?: Partial<HypervisorViewStrata>;
  register_columns?: string[];
  sort?: string;
}

function normalizeView(view: RawNamedView): HypervisorNamedView {
  return {
    id: view.id,
    label: view.label,
    denominator: viewDenominator(view as HypervisorNamedView),
    period: viewPeriod(view as HypervisorNamedView),
    strata: {
      comprendre: [...(view.strata?.comprendre ?? [])],
      detailler: [...(view.strata?.detailler ?? [])],
      decider: [...(view.strata?.decider ?? [])],
    },
    register_columns: [...(view.register_columns ?? [])],
    sort: view.sort || 'name',
  };
}
