/**
 * Live PR → PO desk. Turns MCP / HANA previews into a factory briefing:
 * connect → sense → compile → decide → sealed write.
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

export type FactoryStationId = 'connect' | 'sense' | 'compile' | 'decide' | 'write';
export type FactoryStationStatus = 'done' | 'ready' | 'blocked' | 'sealed';
export type FactoryFactId = 'pr' | 'inbox' | 'supplier' | 'format';

export interface FactoryStation {
  id: FactoryStationId;
  status: FactoryStationStatus;
  via: string;
}

export interface FactoryFact {
  id: FactoryFactId;
  value: string;
  via: string;
}

export interface DeskBriefing {
  headlineKey: string;
  headlineParams: Record<string, string | number>;
  nextKey: string;
  voiceKey: string;
  voiceParams: Record<string, string | number>;
  liveLanes: number;
  kpis: DeskKpi[];
  stations: FactoryStation[];
  facts: FactoryFact[];
}

export interface DeskShare {
  id: string;
  value: number;
  pct: number;
}

export interface DeskCoverage {
  prs: number;
  pos: number;
  pct: number;
}

export type FactoryAskIntent =
  | 'supplier'
  | 'pr'
  | 'inbox'
  | 'po'
  | 'gr'
  | 'write'
  | 'next'
  | 'empty';

export interface FactoryAskReply {
  intent: FactoryAskIntent;
  key: string;
  params: Record<string, string | number>;
  focus: DeskLaneId | null;
}

const ASK_CHIPS: ReadonlyArray<FactoryAskIntent> = ['supplier', 'po', 'next', 'write'];

export const FACTORY_ASK_CHIPS = ASK_CHIPS;

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
  const gatewayRow =
    (preview?.columns || []).includes('status') && (preview?.rows?.[0]?.[0] === '403');
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

function firstCell(lane: DeskLane | undefined, wanted: readonly string[]): string {
  if (!lane?.columns.length || !lane.rows.length) return '';
  const index = new Map(lane.columns.map((name, at) => [name.toLowerCase(), at]));
  for (const name of wanted) {
    const at = index.get(name.toLowerCase());
    if (at == null) continue;
    for (const row of lane.rows) {
      const value = String(row[at] ?? '').trim();
      if (value) return value;
    }
  }
  return '';
}

function majorityCell(lane: DeskLane | undefined, wanted: readonly string[]): string {
  if (!lane?.columns.length || !lane.rows.length) return '';
  const index = new Map(lane.columns.map((name, at) => [name.toLowerCase(), at]));
  let at = -1;
  for (const name of wanted) {
    const found = index.get(name.toLowerCase());
    if (found != null) {
      at = found;
      break;
    }
  }
  if (at < 0) return '';
  const votes = new Map<string, number>();
  for (const row of lane.rows) {
    const value = String(row[at] ?? '').trim();
    if (!value) continue;
    votes.set(value, (votes.get(value) || 0) + 1);
  }
  let best = '';
  let count = 0;
  for (const [value, n] of votes) {
    if (n > count) {
      best = value;
      count = n;
    }
  }
  return best;
}

function firstLiveTool(...lanes: Array<DeskLane | undefined>): string {
  for (const lane of lanes) {
    if (lane?.status === 'live' && lane.tool) return lane.tool;
  }
  return '';
}

function focusFromLane(
  lane: DeskLane | undefined,
  idNames: readonly string[],
  labelNames: readonly string[],
): { id: string; label: string } {
  if (!lane?.columns.length || !lane.rows.length) return { id: '', label: '' };
  const index = new Map(lane.columns.map((name, at) => [name.toLowerCase(), at]));
  const idAt = idNames.map((name) => index.get(name.toLowerCase())).find((at) => at != null);
  const labelAt = labelNames.map((name) => index.get(name.toLowerCase())).find((at) => at != null);
  let fallbackId = '';
  for (const row of lane.rows) {
    const id = idAt != null ? String(row[idAt] ?? '').trim() : '';
    const label = labelAt != null ? String(row[labelAt] ?? '').trim() : '';
    if (!fallbackId && id) fallbackId = id;
    if (label) return { id: id || fallbackId, label };
  }
  return { id: fallbackId, label: fallbackId };
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

  const focus = focusFromLane(pr, ['PurchaseRequisition'], ['PurReqnDescription']);
  const focusPr = focus.id;
  const focusLabel = focus.label;
  const inboxTask = firstCell(inbox, ['TaskTitle']);
  const supplier = majorityCell(po, ['Supplier']);
  const poFormat = majorityCell(po, ['PurchaseOrderType']);
  const facts: FactoryFact[] = [];
  if (focusLabel) facts.push({ id: 'pr', value: focusLabel, via: pr?.tool || '' });
  if (inboxTask) facts.push({ id: 'inbox', value: inboxTask, via: inbox?.tool || '' });
  if (supplier) facts.push({ id: 'supplier', value: supplier, via: po?.tool || '' });
  if (poFormat) facts.push({ id: 'format', value: poFormat, via: po?.tool || '' });

  const reached = lanes.some((lane) => lane.status !== 'down');
  const sensed = [pr, inbox, po].some((lane) => lane?.status === 'live');
  const compiled = facts.length > 0;
  const stations: FactoryStation[] = [
    { id: 'connect', status: reached ? 'done' : 'blocked', via: '' },
    { id: 'sense', status: sensed ? 'done' : 'blocked', via: firstLiveTool(pr, inbox, po) },
    { id: 'compile', status: compiled ? 'done' : 'blocked', via: compiled ? 'python_recipe_v1' : '' },
    { id: 'decide', status: hitlCount > 0 || compiled ? 'ready' : 'blocked', via: '' },
    { id: 'write', status: 'sealed', via: '' },
  ];

  let nextKey = 'experience.pr_to_po.desk.next.review';
  if (hitlCount > 0) nextKey = 'experience.pr_to_po.desk.next.decide';
  else if (liveLanes === 0) nextKey = 'experience.pr_to_po.desk.next.retry';
  else if (gr?.status === 'caution' || gr?.status === 'down') nextKey = 'experience.pr_to_po.desk.next.receive';

  const compiledHeadline = Boolean(focusPr && supplier);
  const voiceParams = {
    prs: pr?.rowCount || 0,
    tasks: inbox?.rowCount || 0,
    pos: po?.rowCount || 0,
    receipts: gr?.rowCount || 0,
    pr: focusLabel,
    supplier,
    format: poFormat,
  };
  return {
    headlineKey: compiledHeadline
      ? 'experience.pr_to_po.desk.headline.compiled'
      : liveLanes > 0
        ? 'experience.pr_to_po.desk.headline.live'
        : 'experience.pr_to_po.desk.headline.none',
    headlineParams: {
      prs: pr?.rowCount || 0,
      tasks: inbox?.rowCount || 0,
      pos: po?.rowCount || 0,
      pr: focusLabel,
      supplier,
    },
    nextKey,
    voiceKey: compiledHeadline
      ? 'experience.pr_to_po.desk.voice.compiled'
      : liveLanes > 0
        ? 'experience.pr_to_po.desk.voice.live'
        : 'experience.pr_to_po.desk.voice.none',
    voiceParams,
    liveLanes,
    kpis,
    stations,
    facts,
  };
}

export function donutSlices(shares: readonly DeskShare[]): Array<DeskShare & { offset: number }> {
  let cursor = 0;
  return shares.map((share) => {
    const row = { ...share, offset: cursor ? -cursor : 0 };
    cursor += share.pct;
    return row;
  });
}

export function terrainShares(kpis: readonly DeskKpi[]): DeskShare[] {
  const rows = kpis.filter((kpi) => kpi.id !== 'hana' && kpi.value > 0);
  const total = rows.reduce((sum, kpi) => sum + kpi.value, 0);
  if (!total) return [];
  return rows.map((kpi) => ({
    id: kpi.id,
    value: kpi.value,
    pct: Math.round((kpi.value / total) * 100),
  }));
}

export function supplierShares(lanes: readonly DeskLane[]): DeskShare[] {
  const po = lanes.find((lane) => lane.id === 'po');
  if (!po?.columns.length || !po.rows.length) return [];
  const index = new Map(po.columns.map((name, at) => [name.toLowerCase(), at]));
  const at = index.get('supplier');
  if (at == null) return [];
  const votes = new Map<string, number>();
  for (const row of po.rows) {
    const value = String(row[at] ?? '').trim();
    if (!value) continue;
    votes.set(value, (votes.get(value) || 0) + 1);
  }
  const ranked = [...votes.entries()].sort((a, b) => b[1] - a[1]);
  const total = ranked.reduce((sum, [, n]) => sum + n, 0);
  if (!total) return [];
  const top = ranked.slice(0, 4);
  const rest = ranked.slice(4).reduce((sum, [, n]) => sum + n, 0);
  const shares = top.map(([label, value]) => ({
    id: label,
    value,
    pct: Math.round((value / total) * 100),
  }));
  if (rest) shares.push({ id: 'other', value: rest, pct: Math.round((rest / total) * 100) });
  return shares;
}

export function orderCoverage(lanes: readonly DeskLane[]): DeskCoverage {
  const prs = lanes.find((lane) => lane.id === 'pr')?.rowCount || 0;
  const pos = lanes.find((lane) => lane.id === 'po')?.rowCount || 0;
  const basis = Math.max(prs, pos, 1);
  return { prs, pos, pct: Math.round((pos / basis) * 100) };
}

function foldAsk(query: string): string {
  return query
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

const ASK_INTENTS: ReadonlySet<string> = new Set([
  'supplier',
  'pr',
  'inbox',
  'po',
  'gr',
  'write',
  'next',
  'empty',
]);

export function interpretFactoryAsk(query: string): FactoryAskIntent {
  const q = foldAsk(query);
  if (!q) return 'empty';
  if (ASK_INTENTS.has(q)) return q as FactoryAskIntent;
  if (/(write|ecrire|creer|create|poster|seal|scell)/.test(q)) return 'write';
  if (/\b(suppliers?|fournisseurs?|vendors?)\b/.test(q)) return 'supplier';
  if (/\b(receipts?|receptions?|goods|gr)\b/.test(q)) return 'gr';
  if (/\b(approvals?|approbations?|inbox|tasks?|taches?)\b/.test(q)) return 'inbox';
  if (/\b(orders?|commandes?|pos?)\b/.test(q) && !/\bprs?\b/.test(q)) return 'po';
  if (/\b(requisitions?|demandes?|prs?)\b/.test(q)) return 'pr';
  return 'next';
}

export function askFactory(
  query: string,
  briefing: DeskBriefing,
  lanes: readonly DeskLane[] = [],
): FactoryAskReply {
  const intent = interpretFactoryAsk(query);
  const byId = new Map(lanes.map((lane) => [lane.id, lane]));
  const fact = (id: FactoryFactId) => briefing.facts.find((row) => row.id === id)?.value || '';
  const params = {
    ...briefing.voiceParams,
    pr: fact('pr') || String(briefing.voiceParams['pr'] || ''),
    supplier: fact('supplier') || String(briefing.voiceParams['supplier'] || ''),
    format: fact('format') || String(briefing.voiceParams['format'] || ''),
    prs: byId.get('pr')?.rowCount || briefing.voiceParams['prs'] || 0,
    tasks: byId.get('inbox')?.rowCount || briefing.voiceParams['tasks'] || 0,
    pos: byId.get('po')?.rowCount || briefing.voiceParams['pos'] || 0,
    receipts: byId.get('gr')?.rowCount || briefing.voiceParams['receipts'] || 0,
  };
  const focus: Record<FactoryAskIntent, DeskLaneId | null> = {
    supplier: 'po',
    pr: 'pr',
    inbox: 'inbox',
    po: 'po',
    gr: 'gr',
    write: null,
    next: null,
    empty: null,
  };
  return {
    intent,
    key: `experience.pr_to_po.desk.ask.answer.${intent}`,
    params,
    focus: focus[intent],
  };
}
