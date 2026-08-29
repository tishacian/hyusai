/**
 * Live PR → PO desk. Turns MCP / HANA previews into a briefing a
 * colleague can read without opening the connector page.
 * No invented PDF aliases — tool names stay as the servers advertised them.
 */

export type DeskLaneId = 'pr' | 'inbox' | 'po' | 'gr' | 'hana';
export type DeskLaneStatus = 'live' | 'empty' | 'caution' | 'down';
export type DeskTone = 'ok' | 'warn' | 'off';

export interface DeskPreview {
  ok?: boolean;
  server_id?: string;
  tool?: string;
  columns?: string[];
  rows?: string[][];
  row_count?: number;
  detail?: string;
  source?: string;
  tables?: Array<{ name?: string }>;
  sample_table?: string | null;
}

export interface DeskLane {
  id: DeskLaneId;
  serverId: string;
  status: DeskLaneStatus;
  tool: string;
  columns: string[];
  rows: string[][];
  rowCount: number;
  detail: string;
  source: string;
}

export interface DeskKpi {
  id: DeskLaneId;
  value: number;
  tone: DeskTone;
}

export interface DeskBriefing {
  headlineKey: string;
  headlineParams: Record<string, number>;
  nextKey: string;
  liveLanes: number;
  kpis: DeskKpi[];
}

export const DESK_MCP_LANES: ReadonlyArray<{ id: Exclude<DeskLaneId, 'hana'>; serverId: string }> = [
  { id: 'pr', serverId: 'sap' },
  { id: 'inbox', serverId: 'sap_inbox' },
  { id: 'po', serverId: 'hikma' },
  { id: 'gr', serverId: 'sap_gr' },
];

const PREFERRED_COLUMNS: Record<DeskLaneId, readonly string[]> = {
  pr: [
    'PurchaseRequisition',
    'PurchaseRequisitionType',
    'PurReqnDescription',
    'CreationDate',
    'SourceDetermination',
  ],
  inbox: ['TaskTitle', 'TaskDefinitionName', 'Status', 'Priority', 'InstanceID', 'CreatedOn'],
  po: [
    'PurchaseOrder',
    'PurchaseOrderType',
    'Supplier',
    'PurchaseOrderDate',
    'PurchasingOrganization',
  ],
  gr: ['MaterialDocument', 'MaterialDocumentYear', 'GoodsMovementCode', 'PostingDate'],
  hana: [],
};

const COLUMN_CAP = 5;
const ROW_CAP = 6;

export function pickDeskColumns(columns: readonly string[], lane: DeskLaneId): string[] {
  const available = columns
    .map((name) => String(name || ''))
    .filter(
      (name) =>
        name &&
        !name.startsWith('__') &&
        !name.startsWith('to_') &&
        !name.toLowerCase().endsWith('supports'),
    );
  if (!available.length) return [];
  const lower = new Map(available.map((name) => [name.toLowerCase(), name]));
  const picked: string[] = [];
  for (const wanted of PREFERRED_COLUMNS[lane]) {
    const hit = lower.get(wanted.toLowerCase());
    if (hit && !picked.includes(hit)) picked.push(hit);
    if (picked.length >= COLUMN_CAP) return picked;
  }
  for (const name of available) {
    if (!picked.includes(name)) picked.push(name);
    if (picked.length >= COLUMN_CAP) break;
  }
  return picked;
}

export function projectRows(
  columns: readonly string[],
  rows: readonly string[][],
  picked: readonly string[],
): string[][] {
  const index = picked.map((name) => columns.indexOf(name));
  return rows.slice(0, ROW_CAP).map((row) => index.map((at) => (at >= 0 ? String(row[at] ?? '') : '')));
}

export function laneFromPreview(
  id: Exclude<DeskLaneId, 'hana'>,
  serverId: string,
  preview: DeskPreview | null,
  detail = '',
): DeskLane {
  const message = (preview?.detail || detail || '').trim();
  const gatewayRow = (preview?.columns || []).includes('status') && (preview.rows?.[0]?.[0] === '403');
  if (!preview || preview.ok === false || gatewayRow) {
    return {
      id,
      serverId,
      status: id === 'gr' || gatewayRow || /403|limited|refused/i.test(message) ? 'caution' : 'down',
      tool: preview?.tool || '',
      columns: [],
      rows: [],
      rowCount: 0,
      detail: message,
      source: '',
    };
  }
  const rawColumns = preview.columns || [];
  const columns = pickDeskColumns(rawColumns, id);
  const rows = projectRows(rawColumns, preview.rows || [], columns);
  const rowCount = Number(preview.row_count || rows.length || 0);
  let status: DeskLaneStatus = rowCount > 0 ? 'live' : 'empty';
  if (id === 'gr' && /403|limited|refused/i.test(message)) status = 'caution';
  return {
    id,
    serverId,
    status,
    tool: preview.tool || '',
    columns,
    rows,
    rowCount,
    detail: message,
    source: '',
  };
}

export function hanaLaneFromPreview(preview: DeskPreview | null, detail = ''): DeskLane {
  const message = (preview?.detail || detail || '').trim();
  if (!preview || preview.ok === false) {
    return {
      id: 'hana',
      serverId: 'hana',
      status: 'down',
      tool: preview?.sample_table || '',
      columns: [],
      rows: [],
      rowCount: 0,
      detail: message,
      source: preview?.source || '',
    };
  }
  const rawColumns = (preview.columns || []).map(String);
  const columns = pickDeskColumns(rawColumns, 'hana');
  const rows = projectRows(rawColumns, preview.rows || [], columns);
  const tableCount = (preview.tables || []).length;
  return {
    id: 'hana',
    serverId: 'hana',
    status: rows.length || tableCount ? 'live' : 'empty',
    tool: preview.sample_table || '',
    columns,
    rows,
    rowCount: tableCount || Number(preview.row_count || rows.length || 0),
    detail: message,
    source: preview.source || '',
  };
}

function kpiTone(lane: DeskLane | undefined): DeskTone {
  if (!lane || lane.status === 'down') return 'off';
  if (lane.status === 'caution' || lane.status === 'empty') return 'warn';
  return 'ok';
}

export function composeDesk(
  lanes: readonly DeskLane[],
  hitlCount = 0,
): DeskBriefing {
  const byId = new Map(lanes.map((lane) => [lane.id, lane]));
  const pr = byId.get('pr');
  const inbox = byId.get('inbox');
  const po = byId.get('po');
  const gr = byId.get('gr');
  const hana = byId.get('hana');
  const liveLanes = lanes.filter((lane) => lane.status === 'live').length;
  const kpis: DeskKpi[] = [
    { id: 'pr', value: pr?.rowCount || 0, tone: kpiTone(pr) },
    { id: 'inbox', value: inbox?.rowCount || 0, tone: kpiTone(inbox) },
    { id: 'po', value: po?.rowCount || 0, tone: kpiTone(po) },
    { id: 'gr', value: gr?.rowCount || 0, tone: kpiTone(gr) },
  ];
  if (hana) kpis.push({ id: 'hana', value: hana.rowCount || 0, tone: kpiTone(hana) });

  let nextKey = 'experience.pr_to_po.desk.next.review';
  if (hitlCount > 0) nextKey = 'experience.pr_to_po.desk.next.decide';
  else if (liveLanes === 0) nextKey = 'experience.pr_to_po.desk.next.retry';
  else if (gr?.status === 'caution' || gr?.status === 'down') nextKey = 'experience.pr_to_po.desk.next.receive';

  return {
    headlineKey:
      liveLanes > 0 ? 'experience.pr_to_po.desk.headline.live' : 'experience.pr_to_po.desk.headline.none',
    headlineParams: {
      prs: pr?.rowCount || 0,
      tasks: inbox?.rowCount || 0,
      pos: po?.rowCount || 0,
    },
    nextKey,
    liveLanes,
    kpis,
  };
}
