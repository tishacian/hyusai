/**
 * NAWA Agent Studio — a client of the server run, nothing more.
 *
 * The PR → PO agent is the published `pr_to_po_flow` DAG. The studio starts a
 * Run through the Experience binding, projects the Run (checkpoints, skill
 * invocations, HITL package) onto the node list, and answers the gate with the
 * canonical HITL decision. It never reads SAP itself and never composes a
 * payload: every request and response shown here is the one the server made.
 *
 * Angular-free so the unit spec pins the projection without a TestBed.
 */

import type { Run, SkillInvocation } from '@app/core/canonical-api.service';

export type StudioMode = 'run' | 'chat';

export type StudioNodeId =
  | 'requisitions'
  | 'select'
  | 'budget'
  | 'discard'
  | 'justification'
  | 'history'
  | 'derive'
  | 'dossier'
  | 'summarise'
  | 'gate'
  | 'post'
  | 'reject'
  | 'audit';

export const STUDIO_NODE_ORDER: readonly StudioNodeId[] = [
  'requisitions',
  'select',
  'budget',
  'discard',
  'justification',
  'history',
  'derive',
  'dossier',
  'summarise',
  'gate',
  'post',
  'reject',
  'audit',
];

/** Studio node → DAG node id in `pr_to_po_flow` (backend `connectors/mcp/flow.py`). */
export const STUDIO_DAG_NODE: Record<StudioNodeId, string> = {
  requisitions: 'task.list_prs',
  select: 'task.select_pr',
  budget: 'task.budget',
  discard: 'task.reject',
  justification: 'task.justification',
  history: 'task.hikma',
  derive: 'task.majority',
  dossier: 'task.format_dossier',
  summarise: 'task.summarise',
  gate: 'hitl.approve_po',
  post: 'task.create_po',
  reject: 'task.handle_rejection',
  audit: 'task.audit',
};

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
  select: 'derive',
  budget: 'read',
  discard: 'write',
  justification: 'read',
  history: 'read',
  derive: 'derive',
  dossier: 'derive',
  summarise: 'derive',
  gate: 'gate',
  post: 'write',
  reject: 'write',
  audit: 'derive',
};

export const BAPI_SERVER_ID = 'bapi_po';
export const LIVE_BAPI_CREATE = 'BAPI_PO_CREATE1';
export const LIVE_BAPI_COMMIT = 'BAPI_TRANSACTION_COMMIT';
export const LIVE_BAPI_ROLLBACK = 'BAPI_TRANSACTION_ROLLBACK';
export const LIVE_DISCARD = 'fi_DiscardFromPurchasing';
export const LIVE_PR_ITEM = 'get_A_PurchaseRequisitionItem';
export const LIVE_PR_ITEM_BY_KEY = 'get_A_PurchaseRequisitionItem_by_key';
export const LIVE_BUDGET = 'fi_Validate';
export const LIVE_PO_HEADER = 'get_A_PurchaseOrder';

/** Guardrails the presenter can flip; they ride the run input as `disabled_tools`. */
export const STUDIO_GUARDRAIL_TOOLS: readonly string[] = [
  LIVE_BAPI_CREATE,
  LIVE_BAPI_COMMIT,
  LIVE_DISCARD,
];

/** Demo-scenario order — the fifth chip opens the in-conversation write dialogue. */
export const STUDIO_CHAT_CHIPS: readonly string[] = [
  'open_prs',
  'suppliers',
  'why_rejected',
  'would_post',
  'create',
];

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
  error: string;
}

export function initialStudioNodes(): StudioNodeState[] {
  return STUDIO_NODE_ORDER.map((id) => ({
    id,
    status: 'idle',
    noteKey: '',
    noteParams: {},
    calls: [],
    error: '',
  }));
}

type Dict = Record<string, unknown>;

function dict(value: unknown): Dict {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Dict) : {};
}

function text(value: unknown): string {
  return value == null ? '' : String(value).trim();
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

/** Body sent to the Experience binding when the human launches a run. */
export function studioRunPayload(
  disabledTools: ReadonlySet<string>,
  prId = '',
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    disabled_tools: [...disabledTools].filter((name) => STUDIO_GUARDRAIL_TOOLS.includes(name)),
  };
  if (prId.trim()) payload['pr_id'] = prId.trim();
  return payload;
}

export function runInvocations(run: Run | null | undefined): SkillInvocation[] {
  const raw = run as unknown as { invocations?: unknown; skill_invocations?: unknown } | null;
  const rows = list(raw?.skill_invocations).length ? list(raw?.skill_invocations) : list(raw?.invocations);
  return rows.filter((row): row is SkillInvocation => !!row && typeof row === 'object');
}

function invocationNode(row: SkillInvocation): string {
  return text(dict(row.trace)['node_id']);
}

/** Latest invocation the walker recorded for a DAG node (a retry wins). */
export function invocationFor(run: Run | null | undefined, dagNodeId: string): SkillInvocation | null {
  let found: SkillInvocation | null = null;
  for (const row of runInvocations(run)) {
    if (invocationNode(row) === dagNodeId) found = row;
  }
  return found;
}

export function nodeOutput(run: Run | null | undefined, dagNodeId: string): Dict {
  return dict(invocationFor(run, dagNodeId)?.output_ref);
}

export interface StudioWriteOutcome {
  sealed: boolean;
  called: boolean;
  blocked: boolean;
  sapOk: boolean;
  committed: boolean;
  poNumber: string;
  rolledBack: boolean;
  messages: string[];
}

function messagesOf(output: Dict): string[] {
  const rows = list(output['messages']);
  const out = rows
    .map((row) => {
      const item = dict(row);
      return `${text(item['type'])}: ${text(item['message'])}`.trim();
    })
    .filter((line) => line !== ':');
  const detail = text(output['detail']);
  if (!out.length && detail) out.push(detail);
  return out;
}

/** The gate's verdict as the write skill returned it — top-level on the node output. */
export function writeOutcomeFromOutput(output: Dict | null | undefined): StudioWriteOutcome | null {
  if (!output || !Object.keys(output).length) return null;
  const sealed = output['sealed'] === true;
  const blocked = output['blocked'] === true;
  const called = output['called'] === true;
  const sapOk = output['sap_ok'] === true;
  return {
    sealed,
    called,
    blocked,
    sapOk,
    committed: output['committed'] === true || (called && sapOk && !('committed' in output)),
    poNumber: text(output['po_number']),
    rolledBack: output['rolled_back'] === true,
    messages: messagesOf(output),
  };
}

export function postOutcome(run: Run | null | undefined): StudioWriteOutcome | null {
  return writeOutcomeFromOutput(nodeOutput(run, STUDIO_DAG_NODE.post));
}

export function rejectOutcome(run: Run | null | undefined): StudioWriteOutcome | null {
  return writeOutcomeFromOutput(nodeOutput(run, STUDIO_DAG_NODE.reject));
}

function isMcpOutput(output: Dict): boolean {
  return 'server_id' in output && ('tool' in output || 'contract_tool' in output);
}

/** One transcript row per call the server made on this node — verbatim. */
export function callsFromInvocation(
  row: SkillInvocation | null,
  kind: StudioNodeKind,
): StudioCall[] {
  if (!row) return [];
  const output = dict(row.output_ref);
  const request = row.input_ref ?? {};
  const failed = row.status === 'failed';
  if (kind === 'write') {
    const rows = list(output['calls']).map(dict).filter((item) => Object.keys(item).length);
    const items = rows.length ? rows : [output];
    return items.map((item) => {
      const verdict = writeOutcomeFromOutput(item);
      const sent = dict(item['arguments'] ?? dict(item['result'])['arguments']);
      return {
        server: text(item['server_id']) || text(output['server_id']),
        tool: text(item['tool']) || text(item['contract_tool']) || text(output['tool']),
        request: Object.keys(sent).length ? sent : request,
        response: item,
        ok: !failed && !!verdict && (verdict.sealed || verdict.sapOk),
        write: true,
        blocked: !!verdict?.blocked,
        sealed: !!verdict?.sealed,
        durationMs: Number(item['duration_ms'] ?? row.latency_ms ?? 0) || 0,
      };
    });
  }
  const mcp = isMcpOutput(output);
  return [
    {
      server: mcp ? text(output['server_id']) : 'agentium',
      tool: mcp ? text(output['tool']) || text(output['contract_tool']) : text(row.skill_slug),
      request,
      response: failed ? { ok: false, error: row.error ?? 'failed', ...output } : output,
      ok: !failed,
      write: false,
      blocked: false,
      sealed: false,
      durationMs: Number(output['duration_ms'] ?? row.latency_ms ?? 0) || 0,
    },
  ];
}

interface Checkpoint {
  kind: string;
  node_id?: string;
  status?: string;
  pause?: boolean;
  error?: string;
  skipped_reason?: string;
}

function checkpoints(run: Run | null | undefined): Checkpoint[] {
  return list(run?.checkpoints).map((row) => dict(row) as unknown as Checkpoint);
}

/** Last checkpoint state per DAG node id: running / completed / failed / skipped / paused. */
export function dagNodeStates(run: Run | null | undefined): Map<string, { status: string; error: string }> {
  const out = new Map<string, { status: string; error: string }>();
  for (const cp of checkpoints(run)) {
    const nodeId = text(cp.node_id);
    if (!nodeId) continue;
    if (cp.kind === 'node_start') {
      out.set(nodeId, { status: 'running', error: '' });
    } else if (cp.kind === 'node_end') {
      if (cp.pause) out.set(nodeId, { status: 'paused', error: '' });
      else if (cp.status === 'skipped') out.set(nodeId, { status: 'skipped', error: '' });
      else if (cp.status === 'failed') out.set(nodeId, { status: 'failed', error: text(cp.error) });
      else out.set(nodeId, { status: 'completed', error: '' });
    } else if (cp.kind === 'hitl_resume' || cp.kind === 'hitl_decided') {
      out.set(nodeId, { status: 'completed', error: '' });
    }
  }
  return out;
}

function plural(count: number): number {
  return Number.isFinite(count) ? count : 0;
}

/** Per-node one-liner the head shows, read from the server output. */
export function nodeNote(
  id: StudioNodeId,
  run: Run | null | undefined,
  state: { status: string; error: string } | undefined,
): { noteKey: string; noteParams: Record<string, string | number> } {
  const none = { noteKey: '', noteParams: {} };
  if (!state || state.status === 'running') return none;
  const out = nodeOutput(run, STUDIO_DAG_NODE[id]);
  const select = nodeOutput(run, STUDIO_DAG_NODE.select);
  switch (id) {
    case 'requisitions':
      return {
        noteKey: 'experience.pr_to_po.studio.note.requisitions',
        noteParams: {
          shown: plural(list(select['candidates']).length),
          total: plural(list(out['prs']).length),
        },
      };
    case 'select':
      if (out['empty'] === true) {
        return { noteKey: 'experience.pr_to_po.studio.note.select_empty', noteParams: {} };
      }
      return {
        noteKey: 'experience.pr_to_po.studio.note.select',
        noteParams: {
          pr: text(out['pr_id']) || '—',
          candidates: list(out['candidates']).map(text).join(', ') || '—',
        },
      };
    case 'budget':
      if (state.status !== 'completed') return none;
      return {
        noteKey: out['budget_ok'] === false
          ? 'experience.pr_to_po.studio.note.budget_ko'
          : 'experience.pr_to_po.studio.note.budget_ok',
        noteParams: { pr: text(out['pr_id']) || '—', reason: text(out['reason']) || 'ok' },
      };
    case 'discard':
    case 'reject': {
      if (state.status === 'skipped') {
        return {
          noteKey: id === 'discard'
            ? 'experience.pr_to_po.studio.note.discard_skipped'
            : 'experience.pr_to_po.studio.note.reject_skipped',
          noteParams: {},
        };
      }
      const verdict = writeOutcomeFromOutput(out);
      const pr = text(select['pr_id']) || '—';
      if (!verdict) return none;
      if (verdict.blocked) {
        return { noteKey: 'experience.pr_to_po.studio.note.post_blocked', noteParams: { pr } };
      }
      if (verdict.sealed) {
        return { noteKey: 'experience.pr_to_po.studio.note.reject_sealed', noteParams: { pr } };
      }
      return {
        noteKey: verdict.sapOk
          ? 'experience.pr_to_po.studio.note.reject_done'
          : 'experience.pr_to_po.studio.note.reject_failed',
        noteParams: { pr },
      };
    }
    case 'justification':
      if (state.status !== 'completed') return none;
      return {
        noteKey: text(out['justification'])
          ? 'experience.pr_to_po.studio.note.justification'
          : 'experience.pr_to_po.studio.note.justification_empty',
        noteParams: { pr: text(out['pr_id']) || text(select['pr_id']) || '—' },
      };
    case 'history':
      if (state.status !== 'completed') return none;
      return {
        noteKey: 'experience.pr_to_po.studio.note.history',
        noteParams: { count: plural(list(out['pos']).length), type: text(out['pr_type']) || 'ZNPR' },
      };
    case 'derive':
      if (state.status !== 'completed') return none;
      return {
        noteKey: 'experience.pr_to_po.studio.note.derive',
        noteParams: {
          supplier: text(out['supplier']) || '—',
          votes: plural(Number(out['vote_count'] ?? 0)),
          terms: text(out['payment_terms']) || '—',
        },
      };
    case 'dossier':
      if (state.status !== 'completed') return none;
      return { noteKey: 'experience.pr_to_po.studio.note.dossier', noteParams: {} };
    case 'summarise':
      if (state.status !== 'completed') return none;
      return {
        noteKey: text(out['completion'])
          ? 'experience.pr_to_po.studio.note.summarise'
          : 'experience.pr_to_po.studio.note.summarise_empty',
        noteParams: { pr: text(select['pr_id']) || '—' },
      };
    case 'gate':
      if (state.status === 'paused') {
        return { noteKey: 'experience.pr_to_po.studio.note.gate', noteParams: { count: 1 } };
      }
      return { noteKey: 'experience.pr_to_po.studio.note.gate_done', noteParams: {} };
    case 'post': {
      if (state.status === 'skipped') {
        return { noteKey: 'experience.pr_to_po.studio.note.post_skipped', noteParams: {} };
      }
      const verdict = writeOutcomeFromOutput(out);
      if (!verdict) return none;
      if (verdict.blocked) return { noteKey: 'experience.pr_to_po.studio.note.post_blocked', noteParams: {} };
      if (verdict.sealed) return { noteKey: 'experience.pr_to_po.studio.note.post_sealed', noteParams: {} };
      if (verdict.sapOk && verdict.poNumber) {
        return { noteKey: 'experience.pr_to_po.studio.note.post_done', noteParams: { pos: verdict.poNumber } };
      }
      return { noteKey: 'experience.pr_to_po.studio.note.post_failed', noteParams: {} };
    }
    case 'audit':
      if (state.status !== 'completed') return none;
      return { noteKey: 'experience.pr_to_po.studio.note.audit', noteParams: {} };
  }
}

function statusOf(
  id: StudioNodeId,
  run: Run | null | undefined,
  state: { status: string; error: string } | undefined,
): StudioNodeStatus {
  if (!state) return 'idle';
  switch (state.status) {
    case 'running':
      return 'running';
    case 'paused':
      return 'waiting';
    case 'skipped':
      return 'skipped';
    case 'failed':
      return 'error';
  }
  const out = nodeOutput(run, STUDIO_DAG_NODE[id]);
  if (id === 'budget' && out['budget_ok'] === false) return 'warn';
  if (id === 'justification' && !text(out['justification'])) return 'warn';
  if (id === 'select' && out['price_missing'] === true) return 'warn';
  if (STUDIO_NODE_KIND[id] === 'write') {
    const verdict = writeOutcomeFromOutput(out);
    if (verdict?.blocked) return 'warn';
    if (verdict && !verdict.sealed && !verdict.sapOk) return 'error';
  }
  return 'done';
}

/** The whole node list, projected from one Run. Pure: same Run, same nodes. */
export function studioNodesFromRun(run: Run | null | undefined): StudioNodeState[] {
  if (!run) return initialStudioNodes();
  const states = dagNodeStates(run);
  return STUDIO_NODE_ORDER.map((id) => {
    const dagId = STUDIO_DAG_NODE[id];
    const state = states.get(dagId);
    const note = nodeNote(id, run, state);
    return {
      id,
      status: statusOf(id, run, state),
      noteKey: note.noteKey,
      noteParams: note.noteParams,
      calls: callsFromInvocation(invocationFor(run, dagId), STUDIO_NODE_KIND[id]),
      error: state?.error ?? '',
    };
  });
}

export type StudioDecision = 'pending' | 'approved' | 'rejected';

export interface StudioProvenance {
  field: string;
  value: string;
  sourceKey: string;
  sourceParams: Record<string, string | number>;
}

/** The HITL package the server compiled — what the human decides on. */
export interface StudioProposal {
  runId: string;
  prId: string;
  item: string;
  label: string;
  plant: string;
  currency: string;
  quantity: string;
  unit: string;
  netPrice: string;
  /** SAP rejects a create when the PR carries 0.00 (06/215 "Please enter net price"). */
  priceMissing: boolean;
  amount: number;
  supplier: string;
  purchGroup: string;
  paymentTerms: string;
  incoterms: string;
  format: string;
  budgetOk: boolean;
  budgetReason: string;
  justification: string;
  voteCount: number;
  candidates: string[];
  totalOpen: number;
  dossier: string;
  provenance: StudioProvenance[];
}

function money(value: unknown): number {
  const parsed = Number(text(value));
  return Number.isFinite(parsed) ? parsed : 0;
}

export function proposalAmount(quantity: unknown, netPrice: unknown): number {
  return Math.round(money(quantity) * money(netPrice) * 100) / 100;
}

export function proposalProvenance(proposal: Omit<StudioProposal, 'provenance'>): StudioProvenance[] {
  const rows: StudioProvenance[] = [];
  if (proposal.supplier) {
    rows.push({
      field: 'supplier',
      value: proposal.supplier,
      sourceKey: 'experience.pr_to_po.studio.provenance.supplier',
      sourceParams: { votes: proposal.voteCount, plant: proposal.plant },
    });
  }
  rows.push({
    field: 'purch_org',
    value: proposal.plant,
    sourceKey: 'experience.pr_to_po.studio.provenance.purch_org',
    sourceParams: { plant: proposal.plant },
  });
  rows.push({
    field: 'currency',
    value: proposal.currency,
    sourceKey: 'experience.pr_to_po.studio.provenance.currency',
    sourceParams: { pr: proposal.prId },
  });
  if (proposal.paymentTerms) {
    rows.push({
      field: 'payment_terms',
      value: proposal.paymentTerms,
      sourceKey: 'experience.pr_to_po.studio.provenance.payment_terms',
      sourceParams: { votes: proposal.voteCount },
    });
  }
  rows.push({
    field: 'delivery_date',
    value: 'floor',
    sourceKey: 'experience.pr_to_po.studio.provenance.delivery',
    sourceParams: {},
  });
  rows.push(
    proposal.priceMissing
      ? {
          field: 'net_price',
          value: '0.00',
          sourceKey: 'experience.pr_to_po.studio.provenance.price_missing',
          sourceParams: {},
        }
      : {
          field: 'net_price',
          value: proposal.netPrice,
          sourceKey: 'experience.pr_to_po.studio.provenance.price',
          sourceParams: { pr: proposal.prId },
        },
  );
  return rows;
}

/**
 * Reads the gate package off `run.hitl.upstream` (the HITL node's inputs_map)
 * and falls back to the node outputs for anything an older flow omitted.
 */
export function proposalFromRun(run: Run | null | undefined): StudioProposal | null {
  if (!run) return null;
  const upstream = dict(run.hitl?.upstream);
  const select = nodeOutput(run, STUDIO_DAG_NODE.select);
  const majority = nodeOutput(run, STUDIO_DAG_NODE.derive);
  const budget = nodeOutput(run, STUDIO_DAG_NODE.budget);
  const summary = nodeOutput(run, STUDIO_DAG_NODE.summarise);
  const dossier = nodeOutput(run, STUDIO_DAG_NODE.dossier);
  const pr = dict(upstream['pr'] ?? select['pr']);
  const prId = text(upstream['pr_id']) || text(select['pr_id']) || text(pr['PurchaseRequisition']);
  if (!prId) return null;
  const proposed = dict(upstream['proposed_po'] ?? majority['proposed_po']);
  const quantity = text(pr['RequestedQuantity']) || '1';
  const netPrice = text(pr['PurchaseRequisitionPrice']) || '0.00';
  const priceMissing = upstream['price_missing'] === true
    || select['price_missing'] === true
    || !(money(netPrice) > 0);
  const base: Omit<StudioProposal, 'provenance'> = {
    runId: run.id,
    prId,
    item: text(upstream['PurchaseRequisitionItem']) || text(select['PurchaseRequisitionItem']) || text(pr['PurchaseRequisitionItem']) || '10',
    label: text(pr['PurchaseRequisitionItemText']) || text(pr['PurReqnDescription']) || prId,
    plant: text(pr['Plant']) || text(select['Plant']) || '1000',
    currency: text(pr['PurReqnItemCurrency']) || text(proposed['currency']) || 'QAR',
    quantity,
    unit: text(pr['BaseUnit']) || 'EA',
    netPrice,
    priceMissing,
    amount: proposalAmount(quantity, netPrice),
    supplier: text(upstream['supplier']) || text(majority['supplier']) || text(proposed['supplier']),
    purchGroup: text(upstream['purch_group']) || text(majority['purch_group']),
    paymentTerms: text(upstream['payment_terms']) || text(majority['payment_terms']),
    incoterms: text(upstream['incoterms']) || text(majority['incoterms']),
    format: text(upstream['format']) || text(majority['format']) || text(proposed['format']),
    budgetOk: (upstream['budget'] ?? budget['budget_ok']) !== false,
    budgetReason: text(upstream['budget_reason']) || text(budget['reason']),
    justification: text(upstream['justification_summary']) || text(summary['completion']),
    voteCount: Number(upstream['vote_count'] ?? majority['vote_count'] ?? 0) || 0,
    candidates: list(upstream['candidates'] ?? select['candidates']).map(text).filter(Boolean),
    totalOpen: Number(upstream['total_open'] ?? select['total_open'] ?? 0) || 0,
    dossier: text(upstream['formatted']) || text(dossier['formatted']),
  };
  return { ...base, provenance: proposalProvenance(base) };
}

/** Candidates the run named but did not take — one run each, pinned by id. */
export function nextCandidates(proposal: StudioProposal | null): string[] {
  if (!proposal) return [];
  return proposal.candidates.filter((id) => id !== proposal.prId);
}

export function runDecision(run: Run | null | undefined): StudioDecision {
  if (!run) return 'pending';
  const states = dagNodeStates(run);
  const post = states.get(STUDIO_DAG_NODE.post)?.status;
  const reject = states.get(STUDIO_DAG_NODE.reject)?.status;
  if (post && post !== 'skipped') return 'approved';
  if (reject && reject !== 'skipped') return 'rejected';
  const decision = text(run.hitl?.decision_status);
  if (decision === 'approved' || decision === 'accepted') return 'approved';
  if (decision === 'rejected') return 'rejected';
  return 'pending';
}

/** A decided gate is still `hitl_pending` until the background resume starts. */
export function gateDecided(run: Run | null | undefined): boolean {
  const status = text(run?.hitl?.decision_status);
  return status === 'accepted' || status === 'approved' || status === 'rejected';
}

export function runIsBusy(run: Run | null | undefined): boolean {
  if (!run) return false;
  if (run.status === 'pending' || run.status === 'running') return true;
  return run.status === 'hitl_pending' && gateDecided(run);
}

/** Terminal for the poller: done, or waiting on a decision nobody took yet. */
export function runIsSettled(run: Run | null | undefined): boolean {
  if (!run) return false;
  if (run.status === 'completed' || run.status === 'failed' || run.status === 'cancelled') return true;
  return run.status === 'hitl_pending' && !gateDecided(run);
}

const JSON_PREVIEW_CAP = 4000;

/** Verbatim JSON for the expandable call cards, capped for the DOM. */
export function studioJson(value: unknown): string {
  let out: string;
  try {
    out = JSON.stringify(value, null, 2) ?? '';
  } catch {
    out = String(value);
  }
  if (out.length <= JSON_PREVIEW_CAP) return out;
  return `${out.slice(0, JSON_PREVIEW_CAP)}\n… (${out.length - JSON_PREVIEW_CAP} chars truncated)`;
}

export function formatStudioAmount(amount: number, currency: string): string {
  return `${amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency || 'QAR'}`;
}

/** Open requisition rows the server read, for the chat fact sheet. */
export interface StudioOpenRow {
  prId: string;
  item: string;
  label: string;
  quantity: string;
  unit: string;
  netPrice: string;
  currency: string;
  plant: string;
}

export function openRowsFromRun(run: Run | null | undefined, cap = 8): StudioOpenRow[] {
  const select = nodeOutput(run, STUDIO_DAG_NODE.select);
  const rows = list(select['prs']).length ? list(select['prs']) : list(nodeOutput(run, STUDIO_DAG_NODE.requisitions)['prs']);
  const seen = new Set<string>();
  const out: StudioOpenRow[] = [];
  for (const raw of rows) {
    const row = dict(raw);
    const prId = text(row['PurchaseRequisition']) || text(row['pr_id']);
    if (!prId || seen.has(prId)) continue;
    seen.add(prId);
    out.push({
      prId,
      item: text(row['PurchaseRequisitionItem']) || '10',
      label: text(row['PurchaseRequisitionItemText']) || text(row['title']) || prId,
      quantity: text(row['RequestedQuantity']) || '1',
      unit: text(row['BaseUnit']) || 'EA',
      netPrice: text(row['PurchaseRequisitionPrice']) || '0.00',
      currency: text(row['PurReqnItemCurrency']) || 'QAR',
      plant: text(row['Plant']) || '1000',
    });
    if (out.length >= cap) break;
  }
  return out;
}

/**
 * Live SAP facts injected verbatim into the chat prompt. The classic chat
 * cannot call tools; the server run did the reads and the model answers from
 * this sheet — never from an imagined "planned read".
 */
export function studioFactSheet(run: Run | null | undefined): string {
  if (!run) return '';
  const lines: string[] = [];
  const proposal = proposalFromRun(run);
  const rows = openRowsFromRun(run);
  const total = proposal?.totalOpen || list(nodeOutput(run, STUDIO_DAG_NODE.requisitions)['prs']).length;
  lines.push(`open approved ZNPR requisition items: ${total} (showing ${rows.length})`);
  for (const row of rows) {
    lines.push(
      `PR ${row.prId}/${row.item} "${row.label}" — ${row.quantity} ${row.unit} × ${row.netPrice} ${row.currency}, plant ${row.plant}`,
    );
  }
  if (proposal) {
    lines.push(
      `plant ${proposal.plant} → majority of ${proposal.voteCount} recent orders: supplier ${proposal.supplier || '—'}, terms ${proposal.paymentTerms || '—'}, incoterms ${proposal.incoterms || '—'}, group ${proposal.purchGroup || '—'}`,
    );
    lines.push(
      `budget check on PR ${proposal.prId}: ${proposal.budgetOk ? 'ok' : 'refused'}${proposal.budgetReason && proposal.budgetReason !== 'ok' ? ` (${proposal.budgetReason})` : ''}`,
    );
    if (proposal.justification) lines.push(`justification summary: ${proposal.justification}`);
    const outcome = postOutcome(run);
    const decision = runDecision(run);
    const state = outcome?.poNumber && outcome.sapOk
      ? `posted as PO ${outcome.poNumber}`
      : outcome?.sealed
        ? 'approved, write sealed (envelope only)'
        : outcome?.blocked
          ? 'approved, write blocked by a guardrail'
          : decision === 'pending'
            ? 'waiting for the human gate'
            : decision;
    lines.push(
      `proposal PR ${proposal.prId} "${proposal.label}" — ${formatStudioAmount(proposal.amount, proposal.currency)} to supplier ${proposal.supplier || '—'} type ${proposal.format || 'ZLPO'} (${state})`,
    );
    if (proposal.candidates.length) lines.push(`next candidates: ${proposal.candidates.join(', ')}`);
  }
  return lines.join('; ');
}

/**
 * The in-conversation write dialogue. The chat model never writes: the fifth
 * chip opens this exchange, the human confirms inside the thread, and the
 * confirmation is the canonical HITL decision on the server run.
 */
export type ChatWriteStage =
  | 'preparing'
  | 'proposing'
  | 'posting'
  | 'posted'
  | 'failed'
  | 'blocked'
  | 'sealed'
  | 'cancelled';

export interface ChatWriteDialogue {
  runId: string;
  proposal: StudioProposal | null;
  stage: ChatWriteStage;
  calls: StudioCall[];
  outcome: StudioWriteOutcome | null;
}

export function openChatWriteDialogue(runId: string, proposal: StudioProposal | null): ChatWriteDialogue {
  return { runId, proposal, stage: proposal ? 'proposing' : 'preparing', calls: [], outcome: null };
}

export function chatWriteStageFromOutcome(outcome: StudioWriteOutcome): ChatWriteStage {
  if (outcome.blocked) return 'blocked';
  if (outcome.sealed) return 'sealed';
  if (outcome.sapOk && outcome.poNumber) return 'posted';
  return 'failed';
}

/** Advance the dialogue from the polled Run — pure, so the spec can drive it. */
export function chatWriteDialogueFromRun(
  dialogue: ChatWriteDialogue,
  run: Run | null | undefined,
): ChatWriteDialogue {
  if (!run || run.id !== dialogue.runId) return dialogue;
  if (dialogue.stage === 'cancelled') return dialogue;
  const proposal = proposalFromRun(run) ?? dialogue.proposal;
  if (run.status === 'hitl_pending' && !gateDecided(run)) {
    return dialogue.stage === 'posting'
      ? { ...dialogue, proposal }
      : { ...dialogue, proposal, stage: 'proposing' };
  }
  if (runIsBusy(run)) {
    return { ...dialogue, proposal, stage: dialogue.stage === 'posting' ? 'posting' : 'preparing' };
  }
  const outcome = postOutcome(run);
  const calls = callsFromInvocation(invocationFor(run, STUDIO_DAG_NODE.post), 'write');
  if (!outcome) {
    return {
      ...dialogue,
      proposal,
      calls,
      stage: 'failed',
      outcome: {
        sealed: false,
        called: false,
        blocked: false,
        sapOk: false,
        committed: false,
        poNumber: '',
        rolledBack: false,
        messages: [text(run.error) || 'run ended without a write'],
      },
    };
  }
  return { ...dialogue, proposal, calls, outcome, stage: chatWriteStageFromOutcome(outcome) };
}
