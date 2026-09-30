export type HypervisorViewDenominator = 'hours' | 'runs' | 'value';
export type HypervisorViewPeriod = '30d' | '90d';
export type HypervisorStratumId = 'comprendre' | 'detailler' | 'decider';
export type HypervisorBlockWidth = '1/2' | '2/3' | 'full';

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

/** Six generic Impact blocks (L13b). */
export const IMPACT_GENERIC_BLOCKS = [
  'echeancier',
  'flux',
  'carte',
  'alertes',
  'ordre_du_jour',
  'indicateurs',
] as const;

export const IMPACT_VIEW_IDS = [
  'agenda',
  'veille',
  'securite',
  'reunion',
  'carte',
] as const;

export type ComprendreBlock = (typeof COMPRENDRE_BLOCKS)[number];
export type DetaillerBlock = (typeof DETAILLER_BLOCKS)[number];
export type DeciderBlock = (typeof DECIDER_BLOCKS)[number];
export type RegisterColumn = (typeof REGISTER_COLUMNS)[number];
export type ViewSort = (typeof VIEW_SORTS)[number];
export type ImpactGenericBlock = (typeof IMPACT_GENERIC_BLOCKS)[number];
export type ImpactViewId = (typeof IMPACT_VIEW_IDS)[number];

export interface HypervisorBlockRef {
  type: string;
  source?: string;
  title?: string;
  width?: HypervisorBlockWidth;
  settings: Record<string, unknown>;
  exit?: string;
}

export interface HypervisorViewStrata {
  comprendre: HypervisorBlockRef[];
  detailler: HypervisorBlockRef[];
  decider: HypervisorBlockRef[];
}

export interface HypervisorNamedView {
  id: string;
  label: string;
  denominator: HypervisorViewDenominator;
  period: string;
  strata: HypervisorViewStrata;
  register_columns: string[];
  sort: string;
  schema_version?: number;
}

export interface HypervisorViewsPayload {
  views: HypervisorNamedView[];
  can_edit: boolean;
}

function block(
  type: string,
  settings: Record<string, unknown> = {},
  extras: Partial<Omit<HypervisorBlockRef, 'type' | 'settings'>> = {},
): HypervisorBlockRef {
  return { type, settings, ...extras };
}

function blocks(...types: string[]): HypervisorBlockRef[] {
  return types.map((type) => block(type));
}

export const DEFAULT_HYPERVISOR_VIEWS: readonly HypervisorNamedView[] = [
  {
    id: 'direction',
    label: 'hypervisor.v2.view.direction',
    denominator: 'hours',
    period: '90d',
    schema_version: 2,
    strata: {
      comprendre: blocks('monument', 'provenance', 'cadran', 'sankey', 'rivers', 'hors_denominateur'),
      detailler: blocks(...DETAILLER_BLOCKS),
      decider: blocks(...DECIDER_BLOCKS),
    },
    register_columns: [...REGISTER_COLUMNS],
    sort: 'value',
  },
  {
    id: 'operations',
    label: 'hypervisor.v2.view.operations',
    denominator: 'runs',
    period: '30d',
    schema_version: 2,
    strata: {
      comprendre: blocks('monument', 'cadran', 'rivers', 'signal'),
      detailler: blocks('registre'),
      decider: [],
    },
    register_columns: ['unit', 'spark'],
    sort: 'days_since_last_run',
  },
  {
    id: 'conformite',
    label: 'hypervisor.v2.view.conformite',
    denominator: 'runs',
    period: '90d',
    schema_version: 2,
    strata: {
      comprendre: blocks('unites', 'couverture', 'decisions'),
      detailler: blocks('registre'),
      decider: [],
    },
    register_columns: ['unit', 'basis'],
    sort: 'name',
  },
];

/** Five named Impact views assembled from the six generic blocks. */
export const IMPACT_GENERIC_VIEWS: readonly HypervisorNamedView[] = [
  {
    id: 'agenda',
    label: 'hypervisor.v2.view.agenda',
    denominator: 'hours',
    period: '30d',
    schema_version: 2,
    strata: {
      comprendre: [
        block('echeancier', { window: '48h', mode: 'liste' }),
        block('ordre_du_jour', { mode: 'prep' }),
      ],
      detailler: [],
      decider: [block('decisions')],
    },
    register_columns: [],
    sort: 'name',
  },
  {
    id: 'veille',
    label: 'hypervisor.v2.view.veille',
    denominator: 'hours',
    period: '30d',
    schema_version: 2,
    strata: {
      comprendre: [
        block('indicateurs'),
        block('flux'),
        block('alertes'),
      ],
      detailler: [],
      decider: [],
    },
    register_columns: [],
    sort: 'name',
  },
  {
    id: 'securite',
    label: 'hypervisor.v2.view.securite',
    denominator: 'hours',
    period: '30d',
    schema_version: 2,
    strata: {
      comprendre: [
        block('carte', { layers: 'incidents' }),
        block('alertes'),
        block('echeancier', { mode: 'compact' }, { width: '1/2' }),
      ],
      detailler: [],
      decider: [],
    },
    register_columns: [],
    sort: 'name',
  },
  {
    id: 'reunion',
    label: 'hypervisor.v2.view.reunion',
    denominator: 'hours',
    period: '30d',
    schema_version: 2,
    strata: {
      comprendre: [
        block('echeancier', { mode: 'fiche' }),
        block('ordre_du_jour', { mode: 'seance' }),
      ],
      detailler: [],
      decider: [block('decisions')],
    },
    register_columns: [],
    sort: 'name',
  },
  {
    id: 'carte',
    label: 'hypervisor.v2.view.carte',
    denominator: 'hours',
    period: '30d',
    schema_version: 2,
    strata: {
      comprendre: [
        block('indicateurs'),
        block('carte', { layers: 'economie' }),
        block('alertes'),
      ],
      detailler: [],
      decider: [],
    },
    register_columns: [],
    sort: 'name',
  },
];

export function isImpactViewId(id: string | null | undefined): id is ImpactViewId {
  return Boolean(id && (IMPACT_VIEW_IDS as readonly string[]).includes(id));
}

/** Parse `?view=` for the five Impact variants; unknown values return null. */
export function parseImpactViewQuery(raw: string | null | undefined): ImpactViewId | null {
  const value = (raw || '').trim().toLowerCase();
  return isImpactViewId(value) ? value : null;
}

export function cloneBlock(ref: HypervisorBlockRef): HypervisorBlockRef {
  return {
    type: ref.type,
    ...(ref.source != null ? { source: ref.source } : {}),
    ...(ref.title != null ? { title: ref.title } : {}),
    ...(ref.width != null ? { width: ref.width } : {}),
    settings: { ...(ref.settings || {}) },
    ...(ref.exit != null ? { exit: ref.exit } : {}),
  };
}

export function cloneView(view: HypervisorNamedView): HypervisorNamedView {
  return {
    ...view,
    schema_version: view.schema_version ?? 2,
    strata: {
      comprendre: view.strata.comprendre.map(cloneBlock),
      detailler: view.strata.detailler.map(cloneBlock),
      decider: view.strata.decider.map(cloneBlock),
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

export function showsBlock(
  view: HypervisorNamedView | null | undefined,
  stratum: HypervisorStratumId,
  blockType: string,
): boolean {
  return Boolean(view?.strata[stratum]?.some((item) => item.type === blockType));
}

export function showsColumn(view: HypervisorNamedView | null | undefined, column: string): boolean {
  return Boolean(view?.register_columns.includes(column));
}

export function toggleStratumBlock(
  view: HypervisorNamedView,
  stratum: HypervisorStratumId,
  blockType: string,
): HypervisorNamedView {
  const next = cloneView(view);
  const list = next.strata[stratum];
  const index = list.findIndex((item) => item.type === blockType);
  if (index >= 0) list.splice(index, 1);
  else list.push(block(blockType));
  return next;
}

export function moveStratumBlock(
  view: HypervisorNamedView,
  stratum: HypervisorStratumId,
  blockType: string,
  direction: -1 | 1,
): HypervisorNamedView {
  const next = cloneView(view);
  const list = next.strata[stratum];
  const index = list.findIndex((item) => item.type === blockType);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= list.length) return next;
  const [item] = list.splice(index, 1);
  list.splice(target, 0, item!);
  return next;
}

export function removeStratumBlock(
  view: HypervisorNamedView,
  stratum: HypervisorStratumId,
  blockType: string,
): HypervisorNamedView {
  const next = cloneView(view);
  next.strata[stratum] = next.strata[stratum].filter((item) => item.type !== blockType);
  return next;
}

export function toggleRegisterColumn(view: HypervisorNamedView, column: string): HypervisorNamedView {
  const next = cloneView(view);
  const index = next.register_columns.indexOf(column);
  if (index >= 0) next.register_columns.splice(index, 1);
  else next.register_columns.push(column);
  return next;
}

export function stratumBlockTypes(view: HypervisorNamedView | null | undefined, stratum: HypervisorStratumId): string[] {
  return (view?.strata[stratum] ?? []).map((item) => item.type);
}

export function serializeViewsForWrite(views: readonly HypervisorNamedView[]): HypervisorNamedView[] {
  return views.map((view) => {
    const cloned = cloneView(view);
    cloned.schema_version = 2;
    return cloned;
  });
}

export function parseViewsPayload(
  raw: { views?: readonly RawNamedView[]; can_edit?: boolean } | null | undefined,
): HypervisorViewsPayload {
  const views = raw?.views?.length
    ? raw.views.map(normalizeView)
    : DEFAULT_HYPERVISOR_VIEWS.map(cloneView);
  return { views, can_edit: raw?.can_edit === true };
}

type RawBlock = string | Partial<HypervisorBlockRef> | null | undefined;

interface RawNamedView {
  id: string;
  label: string;
  denominator?: string;
  period?: string;
  schema_version?: number;
  strata?: Partial<Record<HypervisorStratumId, RawBlock[]>>;
  register_columns?: string[];
  sort?: string;
}

export function normalizeBlockRef(raw: RawBlock): HypervisorBlockRef | null {
  if (raw == null) return null;
  if (typeof raw === 'string') {
    const type = raw.trim();
    return type ? block(type) : null;
  }
  if (typeof raw !== 'object') return null;
  const type = typeof raw.type === 'string' ? raw.type.trim() : '';
  if (!type) return null;
  const settings =
    raw.settings && typeof raw.settings === 'object' && !Array.isArray(raw.settings)
      ? { ...(raw.settings as Record<string, unknown>) }
      : {};
  return {
    type,
    settings,
    ...(typeof raw.source === 'string' ? { source: raw.source } : {}),
    ...(typeof raw.title === 'string' ? { title: raw.title } : {}),
    ...(raw.width === '1/2' || raw.width === '2/3' || raw.width === 'full' ? { width: raw.width } : {}),
    ...(typeof raw.exit === 'string' ? { exit: raw.exit } : {}),
  };
}

function normalizeStratum(raw: RawBlock[] | undefined): HypervisorBlockRef[] {
  if (!raw?.length) return [];
  const out: HypervisorBlockRef[] = [];
  for (const item of raw) {
    const normalized = normalizeBlockRef(item);
    if (normalized) out.push(normalized);
  }
  return out;
}

export function normalizeView(view: RawNamedView): HypervisorNamedView {
  return {
    id: view.id,
    label: view.label,
    denominator: viewDenominator(view as HypervisorNamedView),
    period: viewPeriod(view as HypervisorNamedView),
    schema_version: 2,
    strata: {
      comprendre: normalizeStratum(view.strata?.comprendre),
      detailler: normalizeStratum(view.strata?.detailler),
      decider: normalizeStratum(view.strata?.decider),
    },
    register_columns: [...(view.register_columns ?? [])],
    sort: view.sort || 'name',
  };
}

/** Resolve the active Impact generic view definition (or null). */
export function impactGenericView(id: string | null | undefined): HypervisorNamedView | null {
  if (!isImpactViewId(id)) return null;
  const found = IMPACT_GENERIC_VIEWS.find((view) => view.id === id);
  return found ? cloneView(found) : null;
}

/** Mission Room views must never leak from a saved catalog into another workspace. */
export function availableHypervisorViews(
  views: readonly HypervisorNamedView[],
  missionRoomAvailable: boolean,
  synthese: boolean,
): HypervisorNamedView[] {
  const portfolio = views.filter(view => !isImpactViewId(view.id));
  return synthese && missionRoomAvailable
    ? [...portfolio, ...IMPACT_GENERIC_VIEWS.map(cloneView)]
    : portfolio;
}
