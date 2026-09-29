/**
 * L32 — the work receipt of the PR to PO Studio.
 *
 * "For an agentic product, the agent's work is the product." The receipt is a
 * one-line summary built only from what the server Run recorded: steps the
 * walker settled, SAP reads it actually made, the budget verdict, and the
 * agent's working time from checkpoint timestamps. Anything the Run does not
 * carry is left out, never estimated.
 *
 * Angular-free so the unit spec pins it without a TestBed.
 */

import type { Run } from '@app/core/canonical-api.service';
import {
  LIVE_BAPI_COMMIT,
  LIVE_BAPI_CREATE,
  LIVE_DISCARD,
  STUDIO_DAG_NODE,
  STUDIO_NODE_KIND,
  STUDIO_NODE_ORDER,
  invocationFor,
  nodeOutput,
  type StudioNodeId,
  type StudioNodeKind,
  type StudioNodeState,
  type StudioNodeStatus,
} from './pr-to-po-studio';

type Dict = Record<string, unknown>;

function dict(value: unknown): Dict {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Dict) : {};
}

function text(value: unknown): string {
  return value == null ? '' : String(value).trim();
}

/**
 * Checkpoint `t` is `datetime.utcnow().isoformat()` on the walker: naive UTC.
 * A string without an offset is read as UTC; anything unparsable is unknown.
 */
export function checkpointTime(value: unknown): number | null {
  const raw = text(value);
  if (!raw) return null;
  const zoned = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw) ? raw : `${raw}Z`;
  const ms = Date.parse(zoned);
  return Number.isFinite(ms) ? ms : null;
}

interface TimedCheckpoint {
  kind: string;
  nodeId: string;
  at: number | null;
}

function timedCheckpoints(run: Run | null | undefined): TimedCheckpoint[] {
  const rows = Array.isArray(run?.checkpoints) ? run!.checkpoints! : [];
  return rows.map((row) => {
    const cp = dict(row);
    return { kind: text(cp['kind']), nodeId: text(cp['node_id']), at: checkpointTime(cp['t']) };
  });
}

/** Wall-clock of one step: last `node_start` → the `node_end` that follows it. */
export function stepDurationMs(run: Run | null | undefined, dagNodeId: string): number | null {
  let start: number | null = null;
  let duration: number | null = null;
  for (const cp of timedCheckpoints(run)) {
    if (cp.nodeId !== dagNodeId) continue;
    if (cp.kind === 'node_start') {
      start = cp.at;
      duration = null;
    } else if (cp.kind === 'node_end' && start != null && cp.at != null && cp.at >= start) {
      duration = cp.at - start;
    }
  }
  return duration;
}

/**
 * The agent's working time, the wait for the human decision excluded:
 * run start → the gate opening, plus the resume → the last event after it.
 * Without a gate, run start → the last event. Missing timestamps → null.
 */
export function agentWorkMs(run: Run | null | undefined): number | null {
  const rows = timedCheckpoints(run).filter((cp) => cp.at != null);
  if (!rows.length) return null;
  const gate = STUDIO_DAG_NODE.gate;
  const startRow = rows.find((cp) => cp.kind === 'run_start') ?? rows[0];
  const start = startRow.at!;
  const gateOpen = rows.find((cp) => cp.kind === 'node_start' && cp.nodeId === gate)?.at ?? null;
  const resume = rows.find((cp) => cp.kind === 'hitl_resume' && cp.nodeId === gate)?.at ?? null;
  const last = rows[rows.length - 1].at!;
  let total: number;
  if (gateOpen != null) {
    total = Math.max(0, gateOpen - start);
    if (resume != null && last > resume) total += last - resume;
  } else {
    total = last - start;
  }
  return total > 0 ? total : null;
}

export interface ReceiptReads {
  server: string;
  count: number;
}

/** How a read's system is named on the receipt: `sap` → SAP, else the server id, capitalised. */
export function readSystemLabel(server: string): string {
  const id = text(server);
  if (id.toLowerCase() === 'sap') return 'SAP';
  return id ? id.charAt(0).toUpperCase() + id.slice(1) : id;
}

export interface WorkReceipt {
  /** Steps the walker settled as completed (the gate itself excluded). */
  stepsDone: number;
  stepsFailed: number;
  /** Successful read calls on an MCP server, grouped by server id, in order. */
  reads: ReceiptReads[];
  /** Budget verdict once the budget step completed; null otherwise. */
  budget: { ok: boolean; reason: string } | null;
  agentMs: number | null;
  /** The step the walker is on right now, if any. */
  current: StudioNodeId | null;
}

const COUNTED: ReadonlySet<StudioNodeStatus> = new Set(['done', 'warn']);

export function workReceipt(run: Run | null | undefined, nodes: readonly StudioNodeState[]): WorkReceipt {
  const reads: ReceiptReads[] = [];
  let stepsDone = 0;
  let stepsFailed = 0;
  let current: StudioNodeId | null = null;
  for (const node of nodes) {
    if (node.status === 'running' && !current) current = node.id;
    if (node.id === 'gate') continue;
    if (COUNTED.has(node.status)) stepsDone += 1;
    if (node.status === 'error') stepsFailed += 1;
    for (const call of node.calls) {
      if (call.write || !call.ok || !call.server || call.server === 'agentium') continue;
      const row = reads.find((item) => item.server === call.server);
      if (row) row.count += 1;
      else reads.push({ server: call.server, count: 1 });
    }
  }
  const budgetNode = nodes.find((node) => node.id === 'budget');
  const budgetOut = nodeOutput(run, STUDIO_DAG_NODE.budget);
  const budget = budgetNode && COUNTED.has(budgetNode.status)
    ? { ok: budgetOut['budget_ok'] !== false, reason: text(budgetOut['reason']) }
    : null;
  return { stepsDone, stepsFailed, reads, budget, agentMs: agentWorkMs(run), current };
}

export interface ChronologyStep {
  id: StudioNodeId;
  status: StudioNodeStatus;
  kind: StudioNodeKind;
  labelKey: string;
  /** Tool or skill the server really called — shown second, never first. */
  technical: string;
  durationMs: number | null;
  invocationId: string | null;
}

function firstStartIndex(run: Run | null | undefined): Map<string, number> {
  const out = new Map<string, number>();
  timedCheckpoints(run).forEach((cp, index) => {
    if (cp.kind === 'node_start' && cp.nodeId && !out.has(cp.nodeId)) out.set(cp.nodeId, index);
  });
  return out;
}

/**
 * The steps that really happened, in the order the walker started them.
 * Steps not reached yet are not events and stay out.
 */
export function chronology(run: Run | null | undefined, nodes: readonly StudioNodeState[]): ChronologyStep[] {
  const order = firstStartIndex(run);
  const reached = nodes.filter((node) => node.status !== 'idle');
  const rank = (id: StudioNodeId) => order.get(STUDIO_DAG_NODE[id]) ?? 10_000 + STUDIO_NODE_ORDER.indexOf(id);
  return [...reached]
    .sort((a, b) => rank(a.id) - rank(b.id))
    .map((node) => {
      const dagId = STUDIO_DAG_NODE[node.id];
      const invocation = invocationFor(run, dagId);
      const call = node.calls[0];
      const technical = (call && call.server !== 'agentium' ? call.tool : '')
        || text(invocation?.skill_slug)
        || dagId;
      return {
        id: node.id,
        status: node.status,
        kind: STUDIO_NODE_KIND[node.id],
        labelKey: `experience.pr_to_po.studio.node.${node.id}`,
        technical,
        // The gate's span is the human's wait, not the agent's work; a skipped
        // branch did no work at all.
        durationMs: node.id === 'gate' || node.status === 'skipped' ? null : stepDurationMs(run, dagId),
        invocationId: text(invocation?.id) || null,
      };
    });
}

/** Guardrails the Run was launched with (`input.disabled_tools`). */
export function runDisabledTools(run: Run | null | undefined): Set<string> {
  const input = dict(run?.input_ref);
  const raw = Array.isArray(input['disabled_tools']) ? input['disabled_tools'] : [];
  return new Set(raw.map(text).filter(Boolean));
}

export type GateBranch = 'approve' | 'reject';

export interface GateConsequence {
  step: StudioNodeId;
  key: string;
  params: Record<string, string | number>;
  /** Tool names the step calls, shown as a secondary identifier. */
  tools: string[];
  tone: 'write' | 'sealed' | 'blocked' | 'trace';
}

/** What each gate answer runs next in `pr_to_po_flow` (after `hitl.approve_po`). */
export const GATE_BRANCH_STEPS: Record<GateBranch, readonly StudioNodeId[]> = {
  approve: ['post', 'audit'],
  reject: ['reject', 'audit'],
};

/**
 * "What your approval triggers", read off the steps still ahead of the gate
 * and the conditions the Run carries: the workspace seal and the guardrails
 * the Run was launched with. A step that already ran is not a consequence.
 */
export function gateConsequences(
  branch: GateBranch,
  nodes: readonly StudioNodeState[],
  options: { unsealed: boolean; disabledTools: ReadonlySet<string>; prId: string },
): GateConsequence[] {
  const pending = new Set(nodes.filter((node) => node.status === 'idle').map((node) => node.id));
  const out: GateConsequence[] = [];
  const base = 'experience.pr_to_po.studio.receipt.next';
  for (const step of GATE_BRANCH_STEPS[branch]) {
    if (!pending.has(step)) continue;
    if (step === 'audit') {
      out.push({ step, key: `${base}.audit`, params: {}, tools: [], tone: 'trace' });
      continue;
    }
    if (step === 'post') {
      const tools = [LIVE_BAPI_CREATE, LIVE_BAPI_COMMIT];
      if (options.disabledTools.has(LIVE_BAPI_CREATE)) {
        out.push({ step, key: `${base}.post_blocked`, params: {}, tools: [LIVE_BAPI_CREATE], tone: 'blocked' });
      } else if (!options.unsealed) {
        out.push({ step, key: `${base}.post_sealed`, params: {}, tools, tone: 'sealed' });
      } else if (options.disabledTools.has(LIVE_BAPI_COMMIT)) {
        out.push({ step, key: `${base}.post_no_commit`, params: {}, tools: [LIVE_BAPI_CREATE], tone: 'blocked' });
      } else {
        out.push({ step, key: `${base}.post`, params: {}, tools, tone: 'write' });
      }
      continue;
    }
    const params = { pr: options.prId || '—' };
    if (options.disabledTools.has(LIVE_DISCARD)) {
      out.push({ step, key: `${base}.reject_blocked`, params, tools: [LIVE_DISCARD], tone: 'blocked' });
    } else if (!options.unsealed) {
      out.push({ step, key: `${base}.reject_sealed`, params, tools: [LIVE_DISCARD], tone: 'sealed' });
    } else {
      out.push({ step, key: `${base}.reject`, params, tools: [LIVE_DISCARD], tone: 'write' });
    }
  }
  return out;
}

export interface GateCheck {
  id: 'budget' | 'price' | 'justification' | 'supplier';
  ok: boolean;
  key: string;
  params: Record<string, string | number>;
  tool: string;
}

function callTool(run: Run | null | undefined, id: StudioNodeId): string {
  const out = nodeOutput(run, STUDIO_DAG_NODE[id]);
  return text(out['tool']) || text(out['contract_tool']) || text(invocationFor(run, STUDIO_DAG_NODE[id])?.skill_slug);
}

/**
 * "What the agent checked": one line per check a completed step really made,
 * with its verdict. A step that did not complete contributes nothing.
 */
export function gateChecks(
  run: Run | null | undefined,
  nodes: readonly StudioNodeState[],
  proposal: {
    prId: string;
    priceMissing: boolean;
    netPrice: string;
    currency: string;
    supplier: string;
    voteCount: number;
    plant: string;
    justification: string;
  } | null,
  locale = 'fr',
): GateCheck[] {
  if (!proposal) return [];
  const done = (id: StudioNodeId) => COUNTED.has(nodes.find((node) => node.id === id)?.status ?? 'idle');
  const base = 'experience.pr_to_po.studio.receipt.check';
  const out: GateCheck[] = [];
  if (done('budget')) {
    const budget = nodeOutput(run, STUDIO_DAG_NODE.budget);
    const ok = budget['budget_ok'] !== false;
    const reason = text(budget['reason']);
    out.push({
      id: 'budget',
      ok,
      key: ok ? `${base}.budget_ok` : `${base}.budget_ko`,
      params: { reason: reason && reason !== 'ok' ? reason : '' },
      tool: callTool(run, 'budget'),
    });
  }
  if (done('select')) {
    out.push({
      id: 'price',
      ok: !proposal.priceMissing,
      key: proposal.priceMissing ? `${base}.price_missing` : `${base}.price_ok`,
      params: {
        pr: proposal.prId,
        price: formatReceiptAmount(Number(proposal.netPrice) || 0, proposal.currency, locale),
      },
      tool: '',
    });
  }
  if (done('justification')) {
    const found = !!text(nodeOutput(run, STUDIO_DAG_NODE.justification)['justification']);
    out.push({
      id: 'justification',
      ok: found,
      key: found ? `${base}.justification_ok` : `${base}.justification_empty`,
      params: { pr: proposal.prId },
      tool: callTool(run, 'justification'),
    });
  }
  if (done('derive') && proposal.supplier) {
    const history = nodeOutput(run, STUDIO_DAG_NODE.history);
    out.push({
      id: 'supplier',
      ok: true,
      key: `${base}.supplier`,
      params: {
        votes: proposal.voteCount,
        type: text(history['pr_type']) || 'ZNPR',
        plant: proposal.plant,
      },
      tool: callTool(run, 'history'),
    });
  }
  return out;
}

/** A refusal is a decision with a reason: blank is not a reason. */
export function rejectReasonError(reason: string | null | undefined): string | null {
  return text(reason) ? null : 'experience.pr_to_po.studio.gate.reason_required';
}

export function formatReceiptDuration(ms: number, locale: string): string {
  const tag = locale === 'fr' ? 'fr-FR' : 'en-US';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) {
    const seconds = ms / 1000;
    const digits = seconds < 10 ? 1 : 0;
    return `${seconds.toLocaleString(tag, { minimumFractionDigits: digits, maximumFractionDigits: digits })} s`;
  }
  const total = Math.round(ms / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes} min ${String(seconds).padStart(2, '0')} s`;
}

export function formatReceiptAmount(amount: number, currency: string, locale: string): string {
  const tag = locale === 'fr' ? 'fr-FR' : 'en-US';
  const figure = amount.toLocaleString(tag, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency ? `${figure} ${currency}` : figure;
}
