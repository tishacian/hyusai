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
export type FactoryFactId =
  | 'pr'
  | 'inbox'
  | 'supplier'
  | 'format'
  | 'justification'
  | 'budget'
  | 'fund'
  | 'fundscenter';

export interface DeskCompileFacts {
  budget?: string;
  fund?: string;
  fundscenter?: string;
  budgetVia?: string;
  fundVia?: string;
}

export interface SelectedPr {
  id: string;
  item: string;
  label: string;
  materialGroup: string;
}

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
  selectedPrId: string;
  kpis: DeskKpi[];
  stations: FactoryStation[];
  facts: FactoryFact[];
}

export interface DeskKeyedRead {
  ok?: boolean;
  tool?: string;
  text?: string;
  result?: unknown;
  detail?: string;
  columns?: string[];
  rows?: string[][];
  row_count?: number;
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

export const JUSTIFICATION_SERVER_ID = 'sap';
export const LIVE_PR_ITEM = 'get_A_PurchaseRequisitionItem';
export const LIVE_PR_ITEM_BY_KEY = 'get_A_PurchaseRequisitionItem_by_key';
export const LIVE_BUDGET = 'fi_Validate';
export const LIVE_ACCT = 'get_A_PurReqnAcctAssgmt';
export const LIVE_PO_ITEM = 'get_A_PurchaseOrderItem';
export const LIVE_PO_HEADER = 'get_A_PurchaseOrder';
export const DEMO_JUSTIFICATION_PR = '2000276450';
export const DEMO_JUSTIFICATION_ITEM = '10';
export const ITEM_TEXT_EXPAND = 'to_PurchaseReqnItemText';
export const APPROVED_PR_TOP = '50';
export const PO_ITEM_TOP = '200';
export const PO_HEADER_CAP = 5;
export const APPROVED_PR_FILTER =
  "PurchaseRequisitionStatus eq 'X' and PurchasingDocument eq '' and IsDeleted eq '' and IsClosed eq false";
export const APPROVED_PR_SELECT =
  'PurchaseRequisition,PurchaseRequisitionItem,PurchaseRequisitionItemText,Material,MaterialGroup,RequestedQuantity,BaseUnit,PurchaseRequisitionPrice,PurReqnItemCurrency,Plant,CompanyCode,PurchasingGroup,DeliveryDate,PurchaseRequisitionType';
export const ACCT_SELECT =
  'PurchaseRequisitionItem,CostCenter,WBSElement,Fund,FundsCenter,CommitmentItem,GLAccount,PurReqnNetAmount';
export const PO_ITEM_SELECT =
  'PurchaseOrder,PurchaseOrderItem,Material,MaterialGroup,Plant,NetPriceAmount,DocumentCurrency,PurchaseRequisition';
export const PO_HEADER_SELECT =
  'PurchaseOrder,Supplier,PurchaseOrderType,PaymentTerms,DocumentCurrency,IncotermsClassification,PurchasingOrganization,PurchasingGroup,CompanyCode,NetPaymentDays';
export const FACTORY_WRITE_TOOLS: ReadonlySet<string> = new Set([
  'post_A_PurchaseOrder',
  'fi_DiscardFromPurchasing',
  'fi_EnableForPurchasing',
  'create_po',
  'reject_pr',
  'handle_rejection',
]);
const JUSTIFICATION_TEXT_KEYS = [
  'justification',
  'Note',
  'Text',
  'PlainLongText',
  'NoteDescription',
  'PurchaseRequisitionItemText',
] as const;

const PREFERRED_COLUMNS: Record<DeskLaneId, readonly string[]> = {
  pr: [
    'PurchaseRequisition',
    'PurchaseRequisitionItem',
    'PurchaseRequisitionItemText',
    'MaterialGroup',
    'RequestedQuantity',
    'PurchaseRequisitionType',
    'PurReqnDescription',
    'CreationDate',
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
  const fetched = (preview.rows || []).length;
  const rowCount = fetched || Number(preview.row_count || 0);
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

function cellAt(row: readonly string[], at: number | undefined): string {
  if (at == null) return '';
  return String(row[at] ?? '').trim();
}

export function selectedPrFromLane(lane: DeskLane | undefined): SelectedPr {
  const empty: SelectedPr = { id: '', item: '', label: '', materialGroup: '' };
  if (!lane?.columns.length || !lane.rows.length) return empty;
  const index = new Map(lane.columns.map((name, at) => [name.toLowerCase(), at]));
  const idAt = ['PurchaseRequisition', 'pr_id']
    .map((name) => index.get(name.toLowerCase()))
    .find((at) => at != null);
  const labelAt = ['PurchaseRequisitionItemText', 'PurReqnDescription', 'title']
    .map((name) => index.get(name.toLowerCase()))
    .find((at) => at != null);
  const itemAt = index.get('purchaserequisitionitem');
  const groupAt = index.get('materialgroup') ?? index.get('pr_type');
  let fallbackId = '';
  for (const row of lane.rows) {
    const id = cellAt(row, idAt);
    const label = cellAt(row, labelAt);
    if (!fallbackId && id) fallbackId = id;
    if (label) {
      return {
        id: id || fallbackId,
        item: cellAt(row, itemAt),
        label,
        materialGroup: cellAt(row, groupAt),
      };
    }
  }
  return {
    id: fallbackId,
    item: '',
    label: fallbackId,
    materialGroup: lane.rows[0] ? cellAt(lane.rows[0], groupAt) : '',
  };
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

  const focus = selectedPrFromLane(pr);
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
    selectedPrId: focusPr,
    kpis,
    stations,
    facts,
  };
}

export function approvedPrItemReadBody(): {
  tool: string;
  arguments: {
    filter: string;
    select: string;
    orderby: string;
    top: string;
    inlinecount: string;
  };
} {
  return {
    tool: LIVE_PR_ITEM,
    arguments: {
      filter: APPROVED_PR_FILTER,
      select: APPROVED_PR_SELECT,
      orderby: 'PurchaseRequisitionReleaseDate desc',
      top: APPROVED_PR_TOP,
      inlinecount: 'allpages',
    },
  };
}

export function budgetReadBody(prId: string): {
  tool: string;
  arguments: { PurchaseRequisition: string };
} {
  return {
    tool: LIVE_BUDGET,
    arguments: { PurchaseRequisition: String(prId || '') },
  };
}

export function acctAssgmtReadBody(prId: string): {
  tool: string;
  arguments: { filter: string; select: string };
} {
  return {
    tool: LIVE_ACCT,
    arguments: {
      filter: `PurchaseRequisition eq '${String(prId || '').replace(/'/g, '')}'`,
      select: ACCT_SELECT,
    },
  };
}

export function poItemReadBody(materialGroup: string): {
  tool: string;
  arguments: { filter: string; select: string; top: string };
} {
  const group = String(materialGroup || '').replace(/'/g, '');
  return {
    tool: LIVE_PO_ITEM,
    arguments: {
      filter: `MaterialGroup eq '${group}'`,
      select: PO_ITEM_SELECT,
      top: PO_ITEM_TOP,
    },
  };
}

export function poHeaderReadBody(poId: string): {
  tool: string;
  arguments: { filter: string; select: string };
} {
  const number = String(poId || '').replace(/'/g, '');
  return {
    tool: LIVE_PO_HEADER,
    arguments: {
      filter: `PurchaseOrder eq '${number}'`,
      select: PO_HEADER_SELECT,
    },
  };
}

export function factoryTerrainReadBodies(selected: {
  id?: string;
  materialGroup?: string;
  poIds?: readonly string[];
}): Array<{ tool: string }> {
  const bodies: Array<{ tool: string }> = [approvedPrItemReadBody()];
  const prId = String(selected.id || '').trim();
  if (prId) {
    bodies.push(budgetReadBody(prId), acctAssgmtReadBody(prId));
  }
  const group = String(selected.materialGroup || '').trim();
  if (group) bodies.push(poItemReadBody(group));
  for (const poId of (selected.poIds || []).slice(0, PO_HEADER_CAP)) {
    bodies.push(poHeaderReadBody(poId));
  }
  return bodies;
}

export function isFactoryWriteTool(name: string): boolean {
  return FACTORY_WRITE_TOOLS.has(String(name || '').trim());
}

export function uniquePurchaseOrders(preview: DeskPreview | null, cap = PO_HEADER_CAP): string[] {
  if (!preview?.columns?.length || !preview.rows?.length) return [];
  const at = preview.columns.findIndex((name) => name.toLowerCase() === 'purchaseorder');
  if (at < 0) return [];
  const ids: string[] = [];
  for (const row of preview.rows) {
    const id = String(row[at] ?? '').trim();
    if (id && !ids.includes(id)) ids.push(id);
    if (ids.length >= cap) break;
  }
  return ids;
}

export function mergeHeaderPreviews(previews: readonly DeskPreview[]): DeskPreview | null {
  const live = previews.filter((preview) => preview && preview.ok !== false && (preview.columns || []).length);
  if (!live.length) return null;
  const columns = live[0].columns || [];
  const rows: string[][] = [];
  for (const preview of live) {
    const cols = preview.columns || [];
    if (cols.join('\0') === columns.join('\0')) {
      rows.push(...(preview.rows || []));
      continue;
    }
    const index = columns.map((name) => cols.indexOf(name));
    for (const row of preview.rows || []) {
      rows.push(index.map((at) => (at >= 0 ? String(row[at] ?? '') : '')));
    }
  }
  return {
    ok: true,
    tool: live[0].tool || LIVE_PO_HEADER,
    columns,
    rows,
    row_count: rows.length,
  };
}

function readRecords(payload: unknown): Array<Record<string, unknown>> {
  if (payload == null) return [];
  if (Array.isArray(payload)) {
    return payload.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object');
  }
  if (typeof payload !== 'object') return [];
  const root = payload as Record<string, unknown>;
  for (const key of ['result', 'd', 'data'] as const) {
    if (key in root && root[key] !== payload) return readRecords(root[key]);
  }
  for (const key of ['results', 'value'] as const) {
    if (Array.isArray(root[key])) return readRecords(root[key]);
  }
  if ('Type' in root || 'type' in root || 'Fund' in root || 'FundsCenter' in root) return [root];
  return [];
}

export function budgetOkFromRead(payload: DeskKeyedRead | null): { ok: boolean; reason: string } {
  if (!payload) return { ok: true, reason: 'ok' };
  const raw = payload.result;
  if (raw && typeof raw === 'object' && !Array.isArray(raw) && 'budget_ok' in raw) {
    const ok = Boolean((raw as { budget_ok?: unknown }).budget_ok);
    const reason = String((raw as { reason?: unknown }).reason || (ok ? 'ok' : 'budget'));
    return { ok, reason };
  }
  if (payload.columns?.length && payload.rows?.length) {
    const typeAt = payload.columns.findIndex((name) => name.toLowerCase() === 'type');
    if (typeAt >= 0) {
      for (const row of payload.rows) {
        if (String(row[typeAt] || '').toUpperCase() !== 'E') continue;
        const msgAt = payload.columns.findIndex((name) => /^(message|text|note)$/i.test(name));
        return { ok: false, reason: (msgAt >= 0 ? String(row[msgAt] || '') : 'E').trim() || 'E' };
      }
      return { ok: true, reason: 'ok' };
    }
  }
  for (const row of readRecords(raw)) {
    const kind = String(row['Type'] ?? row['type'] ?? '')
      .trim()
      .toUpperCase();
    if (kind !== 'E') continue;
    const message = String(row['Message'] ?? row['message'] ?? row['Text'] ?? row['Note'] ?? '').trim();
    return { ok: false, reason: message || 'E' };
  }
  return { ok: true, reason: 'ok' };
}

export function fundFromRead(payload: DeskKeyedRead | null): { fund: string; fundscenter: string } {
  if (!payload) return { fund: '', fundscenter: '' };
  const records = readRecords(payload.result);
  if (records.length) {
    return {
      fund: String(records[0]['Fund'] ?? '').trim(),
      fundscenter: String(records[0]['FundsCenter'] ?? '').trim(),
    };
  }
  const columns = payload.columns || [];
  const rows = payload.rows || [];
  if (!columns.length || !rows.length) return { fund: '', fundscenter: '' };
  const fundAt = columns.findIndex((name) => name.toLowerCase() === 'fund');
  const centerAt = columns.findIndex((name) => name.toLowerCase() === 'fundscenter');
  return {
    fund: fundAt >= 0 ? String(rows[0][fundAt] ?? '').trim() : '',
    fundscenter: centerAt >= 0 ? String(rows[0][centerAt] ?? '').trim() : '',
  };
}

export function justificationReadBody(prId = ''): {
  tool: string;
  arguments: {
    PurchaseRequisition: string;
    PurchaseRequisitionItem: string;
    expand: string;
  };
} {
  return {
    tool: LIVE_PR_ITEM_BY_KEY,
    arguments: {
      PurchaseRequisition: prId.trim() || DEMO_JUSTIFICATION_PR,
      PurchaseRequisitionItem: DEMO_JUSTIFICATION_ITEM,
      expand: ITEM_TEXT_EXPAND,
    },
  };
}

export function offersSelectedJustification(selectedPrId: string): boolean {
  const id = selectedPrId.trim();
  return Boolean(id) && id !== DEMO_JUSTIFICATION_PR;
}

function justificationTextFromRow(row: Record<string, unknown>): string {
  for (const key of JUSTIFICATION_TEXT_KEYS) {
    if (!(key in row)) continue;
    const value = row[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const inner = (value as { value?: unknown }).value;
      if (typeof inner === 'string' && inner.trim()) return inner.trim();
    }
  }
  return '';
}

function justificationExpandRows(node: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(node)) {
    return node.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object');
  }
  if (!node || typeof node !== 'object') return [];
  const row = node as Record<string, unknown>;
  for (const key of ['results', 'value'] as const) {
    const found = row[key];
    if (Array.isArray(found)) {
      return found.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object');
    }
  }
  return [row];
}

export function extractJustificationText(payload: unknown): string {
  if (payload == null) return '';
  if (typeof payload === 'string') return payload.trim();
  if (typeof payload !== 'object') return '';
  const root = payload as Record<string, unknown>;
  const candidates: Array<Record<string, unknown>> = [root];
  for (const key of ['d', 'data', 'result'] as const) {
    const inner = root[key];
    if (inner && typeof inner === 'object' && !Array.isArray(inner)) {
      candidates.push(inner as Record<string, unknown>);
    }
  }
  for (const row of candidates) {
    const direct = row['justification'];
    if (typeof direct === 'string' && direct.trim()) return direct.trim();
    if (ITEM_TEXT_EXPAND in row) {
      const texts = justificationExpandRows(row[ITEM_TEXT_EXPAND])
        .map(justificationTextFromRow)
        .filter(Boolean);
      if (texts.length) return texts.join('\n\n');
    }
    const hit = justificationTextFromRow(row);
    if (hit) return hit;
  }
  return '';
}

export function withJustificationFact(
  briefing: DeskBriefing,
  text: string,
  via: string,
): DeskBriefing {
  const value = text.trim();
  const facts = briefing.facts.filter((fact) => fact.id !== 'justification');
  if (value) facts.push({ id: 'justification', value, via });
  return { ...briefing, facts };
}

export function withCompileFacts(briefing: DeskBriefing, extras: DeskCompileFacts): DeskBriefing {
  const facts = briefing.facts.filter(
    (fact) => fact.id !== 'budget' && fact.id !== 'fund' && fact.id !== 'fundscenter',
  );
  if (extras.budget?.trim()) {
    facts.push({ id: 'budget', value: extras.budget.trim(), via: extras.budgetVia || '' });
  }
  if (extras.fund?.trim()) {
    facts.push({ id: 'fund', value: extras.fund.trim(), via: extras.fundVia || '' });
  }
  if (extras.fundscenter?.trim()) {
    facts.push({ id: 'fundscenter', value: extras.fundscenter.trim(), via: extras.fundVia || '' });
  }
  return { ...briefing, facts };
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

export function shouldOpenFactoryPortal(query: string): boolean {
  const q = foldAsk(query);
  if (!q || ASK_INTENTS.has(q)) return false;
  const intent = interpretFactoryAsk(query);
  return intent === 'next' || intent === 'empty';
}

export function factoryBriefingParams(
  briefing: DeskBriefing,
  lanes: readonly DeskLane[] = [],
): Record<string, string | number> {
  const byId = new Map(lanes.map((lane) => [lane.id, lane]));
  const fact = (id: FactoryFactId) => briefing.facts.find((row) => row.id === id)?.value || '';
  return {
    ...briefing.voiceParams,
    pr: fact('pr') || String(briefing.voiceParams['pr'] || ''),
    supplier: fact('supplier') || String(briefing.voiceParams['supplier'] || ''),
    format: fact('format') || String(briefing.voiceParams['format'] || ''),
    prs: byId.get('pr')?.rowCount || briefing.voiceParams['prs'] || 0,
    tasks: byId.get('inbox')?.rowCount || briefing.voiceParams['tasks'] || 0,
    pos: byId.get('po')?.rowCount || briefing.voiceParams['pos'] || 0,
    receipts: byId.get('gr')?.rowCount || briefing.voiceParams['receipts'] || 0,
  };
}

export function askFactory(
  query: string,
  briefing: DeskBriefing,
  lanes: readonly DeskLane[] = [],
): FactoryAskReply {
  const intent = interpretFactoryAsk(query);
  const params = factoryBriefingParams(briefing, lanes);
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
