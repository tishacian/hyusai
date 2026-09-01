/**
 * NAWA Agent Studio — run-flow and chat contract for the PR → PO agent.
 *
 * Angular-free so the unit spec pins the sequencing, the proposals and the
 * write envelopes without a TestBed. Every SAP body reuses the desk contract
 * (`pr-to-po-desk.ts`); nothing here invents a tool name or a payload shape.
 *
 * Writes go through `POST /mcp/servers/{id}/invoke`, which the backend keeps
 * sealed unless the workspace carries `sap_write_unsealed`. The studio's own
 * guardrail toggles sit in front of that: a disabled tool never leaves the
 * browser, and the blocked call stays visible in the transcript.
 */

import {
  BAPI_SERVER_ID,
  LIVE_BAPI_COMMIT,
  LIVE_BAPI_CREATE,
  hasRemainingQuantity,
  composeSealedPoPost,
  type DeskPreview,
  type DeskPrItemFields,
  type RecentPoTerms,
  type SealedPoPost,
} from './pr-to-po-desk';

export type StudioMode = 'run' | 'chat';

export type StudioNodeId =
  | 'requisitions'
  | 'budget'
  | 'discard'
  | 'summarise'
  | 'history'
  | 'derive'
  | 'proposal'
  | 'gate'
  | 'post'
  | 'reject';

export const STUDIO_NODE_ORDER: readonly StudioNodeId[] = [
  'requisitions',
  'budget',
  'discard',
  'summarise',
  'history',
  'derive',
  'proposal',
  'gate',
  'post',
  'reject',
];

export type StudioNodeStatus =
  | 'idle'
  | 'running'
  | 'done'
  | 'warn'
  | 'error'
  | 'skipped'
  | 'waiting';

export type StudioNodeKind = 'read' | 'derive' | 'gate' | 'write';

export const STUDIO_NODE_KIND: Record<StudioNodeId, StudioNodeKind> = {
  requisitions: 'read',
  budget: 'read',
  discard: 'write',
  summarise: 'derive',
  history: 'read',
  derive: 'derive',
  proposal: 'derive',
  gate: 'gate',
  post: 'write',
  reject: 'write',
};

export interface StudioCall {
  server: string;
  tool: string;
  request: unknown;
  response: unknown;
  ok: boolean;
  write: boolean;
  blocked: boolean;
  sealed: boolean;
  durationMs: number;
}

export interface StudioNodeState {
  id: StudioNodeId;
  status: StudioNodeStatus;
  noteKey: string;
  noteParams: Record<string, string | number>;
  calls: StudioCall[];
}

export type StudioDecision = 'pending' | 'approved' | 'rejected';

export interface StudioProvenance {
  field: string;
  value: string;
  sourceKey: string;
  sourceParams: Record<string, string | number>;
}

export interface StudioWriteOutcome {
  sealed: boolean;
  called: boolean;
  sapOk: boolean;
  poNumber: string;
  rolledBack: boolean;
  blocked: boolean;
  messages: string[];
}

export interface StudioProposal {
  prId: string;
  item: string;
  label: string;
  plant: string;
  currency: string;
  quantity: string;
  netPrice: string;
  amount: number;
  supplier: string;
  purchGroup: string;
  paymentTerms: string;
  incoterms: string;
  post: SealedPoPost | null;
  provenance: StudioProvenance[];
  decision: StudioDecision;
  outcome: StudioWriteOutcome | null;
  budgetWarning: string;
}

/** Local guardrails the presenter can flip; the write-set itself is backend code. */
export const STUDIO_GUARDRAIL_TOOLS: readonly string[] = [
  LIVE_BAPI_CREATE,
  LIVE_BAPI_COMMIT,
  'fi_DiscardFromPurchasing',
];

export const STUDIO_PROPOSAL_CAP = 3;

export const STUDIO_CHAT_CHIPS: readonly string[] = [
  'open_prs',
  'suppliers',
  'why_rejected',
  'would_post',
  'sealed',
];

export function initialStudioNodes(): StudioNodeState[] {
  return STUDIO_NODE_ORDER.map((id) => ({
    id,
    status: 'idle',
    noteKey: '',
    noteParams: {},
    calls: [],
  }));
}

function cell(columns: readonly string[], row: readonly string[], wanted: readonly string[]): string {
  const index = new Map(columns.map((name, at) => [name.toLowerCase(), at]));
  for (const name of wanted) {
    const at = index.get(name.toLowerCase());
    if (at == null) continue;
    const value = String(row[at] ?? '').trim();
    if (value) return value;
  }
  return '';
}

/**
 * Up to `cap` distinct open requisitions from the approved-PR read. One
 * proposal per PR id — the first open item row wins, like the desk.
 */
export function openPrRowsFromPreview(
  preview: DeskPreview | null,
  cap = STUDIO_PROPOSAL_CAP,
): DeskPrItemFields[] {
  const columns = preview?.columns || [];
  const rows = preview?.rows || [];
  if (!columns.length || !rows.length) return [];
  const seen = new Set<string>();
  const out: DeskPrItemFields[] = [];
  for (const row of rows) {
    if (!hasRemainingQuantity(columns, row)) continue;
    const prId = cell(columns, row, ['PurchaseRequisition', 'pr_id']);
    if (!prId || seen.has(prId)) continue;
    seen.add(prId);
    out.push({
      pr_id: prId,
      item: cell(columns, row, ['PurchaseRequisitionItem']) || '10',
      material: cell(columns, row, ['Material']),
      materialGroup: cell(columns, row, ['MaterialGroup', 'pr_type']),
      plant: cell(columns, row, ['Plant']) || '1000',
      quantity: cell(columns, row, ['RequestedQuantity']) || '1',
      unit: cell(columns, row, ['BaseUnit']) || 'EA',
      net_price: cell(columns, row, ['PurchaseRequisitionPrice']) || '0.00',
      currency: cell(columns, row, ['PurReqnItemCurrency', 'DocumentCurrency']) || 'QAR',
      deliveryDate: cell(columns, row, ['DeliveryDate']),
      prType: cell(columns, row, ['PurchaseRequisitionType']),
      label: cell(columns, row, ['PurchaseRequisitionItemText', 'PurReqnDescription', 'title']),
    });
    if (out.length >= cap) break;
  }
  return out;
}

export function proposalAmount(fields: DeskPrItemFields): number {
  const qty = Number(fields.quantity);
  const price = Number(fields.net_price);
  if (!Number.isFinite(qty) || !Number.isFinite(price)) return 0;
  return Math.round(qty * price * 100) / 100;
}

/** Provenance the reviewer reads on the card — each field names its source. */
export function proposalProvenance(
  fields: DeskPrItemFields,
  terms: RecentPoTerms,
  recentPoId: string,
): StudioProvenance[] {
  const rows: StudioProvenance[] = [];
  if (terms.supplier) {
    rows.push({
      field: 'supplier',
      value: terms.supplier,
      sourceKey: 'experience.pr_to_po.studio.provenance.supplier',
      sourceParams: { po: recentPoId || '—', plant: fields.plant },
    });
  }
  rows.push({
    field: 'purch_org',
    value: fields.plant,
    sourceKey: 'experience.pr_to_po.studio.provenance.purch_org',
    sourceParams: { plant: fields.plant },
  });
  rows.push({
    field: 'currency',
    value: fields.currency,
    sourceKey: 'experience.pr_to_po.studio.provenance.currency',
    sourceParams: { pr: fields.pr_id },
  });
  if (terms.paymentTerms) {
    rows.push({
      field: 'payment_terms',
      value: terms.paymentTerms,
      sourceKey: 'experience.pr_to_po.studio.provenance.payment_terms',
      sourceParams: { po: recentPoId || '—' },
    });
  }
  rows.push({
    field: 'delivery_date',
    value: fields.deliveryDate ? 'override' : 'floor',
    sourceKey: 'experience.pr_to_po.studio.provenance.delivery',
    sourceParams: {},
  });
  return rows;
}

export function buildStudioProposal(
  fields: DeskPrItemFields,
  terms: RecentPoTerms,
  recentPoId = '',
  budgetWarning = '',
): StudioProposal {
  return {
    prId: fields.pr_id,
    item: fields.item,
    label: fields.label || fields.pr_id,
    plant: fields.plant,
    currency: fields.currency,
    quantity: fields.quantity,
    netPrice: fields.net_price,
    amount: proposalAmount(fields),
    supplier: terms.supplier,
    purchGroup: terms.purchGroup,
    paymentTerms: terms.paymentTerms,
    incoterms: terms.incoterms,
    post: composeSealedPoPost(fields, terms.supplier, terms),
    provenance: proposalProvenance(fields, terms, recentPoId),
    decision: 'pending',
    outcome: null,
    budgetWarning,
  };
}

export function proposalsTotal(proposals: readonly StudioProposal[]): number {
  return Math.round(proposals.reduce((sum, row) => sum + row.amount, 0) * 100) / 100;
}

/** Body for `POST /mcp/servers/bapi_po/invoke` — the create, no TESTRUN ever. */
export function bapiCreateInvokeBody(post: SealedPoPost): {
  tool: string;
  arguments: Record<string, unknown>;
} {
  return { tool: LIVE_BAPI_CREATE, arguments: post.requestBody };
}

/** The commit is not optional: without it the PO number never existed. */
export function bapiCommitInvokeBody(): { tool: string; arguments: Record<string, unknown> } {
  return { tool: LIVE_BAPI_COMMIT, arguments: { import: { WAIT: 'X' } } };
}

/** Reversible discard (`fi_EnableForPurchasing` takes the same two keys). */
export function discardInvokeBody(prId: string, item: string): {
  tool: string;
  arguments: { PurchaseRequisition: string; PurchaseRequisitionItem: string };
} {
  const line = String(item || '').trim().replace(/^0+(?=\d)/, '') || '10';
  return {
    tool: 'fi_DiscardFromPurchasing',
    arguments: { PurchaseRequisition: String(prId || '').trim(), PurchaseRequisitionItem: line },
  };
}

export const STUDIO_WRITE_SERVERS: Record<string, string> = {
  [LIVE_BAPI_CREATE]: BAPI_SERVER_ID,
  [LIVE_BAPI_COMMIT]: BAPI_SERVER_ID,
  fi_DiscardFromPurchasing: 'sap',
  fi_EnableForPurchasing: 'sap',
};

export function guardrailBlocked(tool: string, disabled: ReadonlySet<string>): boolean {
  return disabled.has(String(tool || '').trim());
}

interface InvokeResponse {
  sealed?: boolean;
  called?: boolean;
  sap_ok?: boolean;
  po_number?: string;
  rolled_back?: boolean;
  messages?: Array<{ type?: string; message?: string }>;
}

export function outcomeFromInvoke(response: unknown): StudioWriteOutcome {
  const body = (response || {}) as InvokeResponse & { detail?: unknown };
  const messages = Array.isArray(body.messages)
    ? body.messages
        .map((row) => `${String(row?.type || '')}: ${String(row?.message || '')}`.trim())
        .filter((text) => text !== ':')
    : [];
  if (!messages.length && typeof body.detail === 'string' && body.detail.trim()) {
    messages.push(body.detail.trim());
  }
  return {
    // Only the backend's explicit envelope is sealed. An HTTP error body
    // (no `sealed` key) is a failed write, never a sealed success.
    sealed: body.sealed === true,
    called: body.called === true,
    sapOk: body.sap_ok === true,
    poNumber: String(body.po_number || '').trim(),
    rolledBack: body.rolled_back === true,
    blocked: false,
    messages,
  };
}

/** Outcome shown on the card when the local guardrail refused the write. */
export function blockedOutcome(): StudioWriteOutcome {
  return {
    sealed: false,
    called: false,
    sapOk: false,
    poNumber: '',
    rolledBack: false,
    blocked: true,
    messages: [],
  };
}

/** A blocked call never left the browser — the transcript must say so. */
export function blockedCall(server: string, tool: string, request: unknown): StudioCall {
  return {
    server,
    tool,
    request,
    response: { blocked: true, called: false, reason: 'guardrail_disabled' },
    ok: false,
    write: true,
    blocked: true,
    sealed: false,
    durationMs: 0,
  };
}

export function studioCallFromInvoke(
  server: string,
  tool: string,
  request: unknown,
  response: unknown,
): StudioCall {
  const outcome = outcomeFromInvoke(response);
  return {
    server,
    tool,
    request,
    response,
    ok: outcome.sealed ? true : outcome.sapOk,
    write: true,
    blocked: false,
    sealed: outcome.sealed,
    durationMs: 0,
  };
}

export function readCall(server: string, tool: string, request: unknown, response: unknown, ok = true): StudioCall {
  return {
    server,
    tool,
    request,
    response,
    ok,
    write: false,
    blocked: false,
    sealed: false,
    durationMs: 0,
  };
}

const JSON_PREVIEW_CAP = 4000;

/** Verbatim JSON for the expandable call cards, capped for the DOM. */
export function studioJson(value: unknown): string {
  let text: string;
  try {
    text = JSON.stringify(value, null, 2) ?? '';
  } catch {
    text = String(value);
  }
  if (text.length <= JSON_PREVIEW_CAP) return text;
  return `${text.slice(0, JSON_PREVIEW_CAP)}\n… (${text.length - JSON_PREVIEW_CAP} chars truncated)`;
}

export function formatStudioAmount(amount: number, currency: string): string {
  return `${amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency || 'QAR'}`;
}

/** Distinct plants across the picked requisitions (history is read per plant). */
export function studioPlants(rows: readonly DeskPrItemFields[]): string[] {
  const plants: string[] = [];
  for (const row of rows) {
    const plant = row.plant.trim() || '1000';
    if (!plants.includes(plant)) plants.push(plant);
  }
  return plants.slice(0, 3);
}
