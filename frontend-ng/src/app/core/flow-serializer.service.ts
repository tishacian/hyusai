import { Injectable } from '@angular/core';

/**
 * Flow serialization — the contract between `/systems/new` (Form) and
 * `/orchestration` (Flow builder).
 *
 * `flow_definition` is a free-form JSON on the `System` model. Today it
 * comes in two shapes in the wild:
 *
 *   1. The System Builder shape (all Vague A systems):
 *      `{ collections, rag_mode, canonical_rag_mode, context_reused,
 *         policy: {...} }`
 *
 *   2. The Intelligence seed shape (News Lab):
 *      `{ variant: 'intelligence', nodes: [...], edges: [...] }`
 *
 * This service unifies both under a single `CanonicalFlow` shape that
 * always carries **both** the semantic sections (collections, rag_mode,
 * policy) **and** the rendered `nodes[]` + `edges[]` graph. The source
 * of truth stays `flow_definition` on the backend — we do not duplicate
 * anything — we simply guarantee a lossless projection both ways.
 *
 * Round-trip guarantees:
 *
 *   - `formToFlow(draft)` emits a flow with canonical node ids
 *     (`builder.objective`, `builder.capability`, …). Every section of
 *     the builder canvas maps to exactly one node.
 *   - `flowToForm(flow, current)` reads those canonical ids back. If
 *     the flow carries **extra** nodes (user-authored in the Flow
 *     builder), it returns `extended: true` so the builder can lock the
 *     affected sections with an "Edited in Flow" badge — we never
 *     silently drop operator intent.
 *   - `source` (`'form' | 'flow'`) tracks who wrote last. The builder
 *     sets it to `'form'` on launch; `/orchestration` sets it to
 *     `'flow'` on save.
 */

/** Canonical node types that both the Form and the Flow understand. */
export type CanonicalNodeType =
  | 'objective'
  | 'capability'
  | 'skill'
  | 'context'
  | 'policy'
  | 'launch'
  | 'source'
  | 'sink'
  | 'custom';

/**
 * Execution kind — orthogonal to the semantic `type`.
 *
 * `type` carries the builder's meaning ("this is the Context section");
 * `kind` tells the DAG runtime what to do with the node at execution
 * time. Builder-authored canonical nodes are always `task` (no-op in
 * runtime; the run engine extracts skills from the System, not the
 * flow). Flow-authored nodes choose any kind to compose a real DAG.
 */
export type NodeKind =
  | 'task'      // Execute a Skill (LLM call or deterministic op).
  | 'decision'  // Branch on condition → N outgoing edges w/ branch_label.
  | 'fork'      // Fan out: N branches run in parallel.
  | 'join'      // Fan in: wait for N incoming branches.
  | 'loop'      // Repeat body until condition or max_iterations.
  | 'agent_loop' // Bounded think → gate → act loop (chooses next skill).
  | 'retry'     // Retry target on error with backoff.
  | 'hitl'      // Pause for Human-in-the-loop approval.
  | 'subflow'   // Nested execution of another System.
  | 'source'    // Flow input (from trigger).
  | 'asset'     // Declarative data source (e.g. a knowledge collection).
  | 'sink';     // Flow output.

/**
 * Typed I/O contract for a node. `schema` is a compact hint:
 * primitive (`'string' | 'number' | 'boolean' | 'object' | 'array'`) or
 * a dotted path to a shared schema (`'ref:run.input'`). The frontend
 * uses it for hover previews and simple validation; the backend can
 * use it later to enforce dataflow correctness.
 */
export interface NodePort {
  name: string;
  schema: string;
  required?: boolean;
  description?: string;
}

/**
 * A typed variable selector into the run's data membrane (v3).
 *
 * `node_id` is either an upstream node id whose output the value is read
 * from, OR one of the reserved namespaces below; `path` walks into that
 * source's output object (e.g. `['retrieval', 'sources', '0', 'id']`).
 *
 * Reserved namespaces (NOT node ids) — addressable from any node:
 *   - `workspace` : workspace-scoped settings / context.
 *   - `system`    : the running System's static config (model, policy…).
 *   - `run`       : per-run inputs (the trigger payload, run id…).
 *   - `node`      : self-reference to the current node's own scope.
 *   - `context`   : the System's canonical Context snapshot.
 *
 * Backward-compat: `inputs_map` still accepts a legacy dot-path string
 * (e.g. `"session.objective"`); v2 flows keep those untouched. The
 * typed `VariableRef` form is the v3 enrichment — both shapes coexist.
 */
export interface VariableRef {
  node_id: string;
  path: string[];
  /** Strict-mode selectors are required unless explicitly opted out. */
  required?: boolean;
}

/** Stable validation reason for the JSON VariableRef contract.
 *
 * Kept in lockstep with ``variable_ref_validation_error`` in the backend:
 * an empty path selects the whole node/namespace, while node ids and every
 * path segment must be non-empty strings. ``required`` never accepts truthy
 * string/number substitutes.
 */
export function variableRefValidationError(value: unknown): string | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return 'must_be_object';
  const candidate = value as { node_id?: unknown; path?: unknown; required?: unknown };
  if (typeof candidate.node_id !== 'string' || candidate.node_id.trim().length === 0) {
    return 'node_id_must_be_non_empty_string';
  }
  if (
    !Array.isArray(candidate.path) ||
    candidate.path.some(
      (segment) => typeof segment !== 'string' || segment.trim().length === 0,
    )
  ) {
    return 'path_must_be_string_array';
  }
  if ('required' in candidate && typeof candidate.required !== 'boolean') {
    return 'required_must_be_boolean';
  }
  return null;
}

export function isValidVariableRef(value: unknown): value is VariableRef {
  return variableRefValidationError(value) === null;
}

/** Reserved variable namespaces that resolve outside the node graph. */
export const RESERVED_VARIABLE_NAMESPACES: readonly string[] = [
  'workspace',
  'system',
  'run',
  'node',
  'context',
] as const;

/**
 * True only when BOTH schemas are known primitives and they are
 * incompatible. Unknown / `ref:`-style / non-primitive schemas are not
 * comparable and never flagged. `number`/`integer` are treated as
 * compatible. This is the SINGLE source of truth for primitive dataflow
 * compatibility — `validateFlow` (the `port_type_mismatch` check) and the
 * variable-picker candidate filter both consume it, so the design-time
 * checklist and the picker can never disagree.
 */
export function primitivesIncompatible(a: string, b: string): boolean {
  const primitives = new Set(['string', 'number', 'integer', 'boolean', 'object', 'array']);
  if (!primitives.has(a) || !primitives.has(b)) return false;
  if (a === b) return false;
  const numeric = new Set(['number', 'integer']);
  if (numeric.has(a) && numeric.has(b)) return false;
  return true;
}

/**
 * Kind-specific config payload. Typed as a discriminated union for
 * IDE support, but always persisted as a free-form bag so forward-
 * compatibility is cheap.
 */
export interface TaskNodeConfig {
  skill_id?: string | null;
  skill_slug?: string;
  /**
   * Map input port name → source value. Either a legacy dot-path string
   * (v2) or a typed {@link VariableRef} selector (v3). Both forms are
   * preserved verbatim across normalize — the v2→v3 backfill never
   * rewrites legacy strings.
   */
  inputs_map?: Record<string, string | VariableRef>;
  /** Strict-mode predecessor fields intentionally forwarded unchanged. */
  passthrough_inputs?: string[];
  /** Map output port name → context key to write. */
  outputs_map?: Record<string, string>;
}

export interface DecisionNodeConfig {
  branches: { label: string; condition: string }[];
  default_branch?: string;
}

export interface ForkNodeConfig {
  /** Names of the parallel branches (free-form labels). */
  branches: string[];
}

export interface JoinNodeConfig {
  /** Wait for all, any, or race-win strategy. */
  strategy: 'all' | 'any' | 'race';
}

export interface LoopNodeConfig {
  max_iterations: number;
  break_on?: string;
  iterator?: string;
}

export interface AgentLoopNodeConfig {
  goal: {
    objective: string;
    done_when: string[];
    status?: 'active' | 'blocked' | 'needs_approval' | 'complete';
  };
  decide_skill?: 'decide_next_v1';
  skill_allowlist: string[];
  confidence_floor?: number;
  budget: { max_turns: number; max_cost?: number; deadline_ms?: number };
  privilege_tier?: 'recommend' | 'act' | 'act_with_approval';
  on_budget?: 'exit' | 'ask_human';
}

export interface RetryNodeConfig {
  max_attempts: number;
  backoff_ms: number;
  /** Optional filter: only retry for specific error kinds. */
  on_errors?: string[];
}

export interface HitlNodeConfig {
  prompt: string;
  timeout_ms?: number;
  /** Roles allowed to approve/reject. */
  approvers?: string[];
  prompt_kind?: 'choice' | 'validate_draft' | 'missing_file' | 'approve_write';
}

export interface SubflowNodeConfig {
  /** Target System to execute as a nested run. */
  system_id: string;
  /** Project parent context keys into child input. */
  input_map?: Record<string, string>;
}

export type KindConfig =
  | TaskNodeConfig
  | DecisionNodeConfig
  | ForkNodeConfig
  | JoinNodeConfig
  | LoopNodeConfig
  | AgentLoopNodeConfig
  | RetryNodeConfig
  | HitlNodeConfig
  | SubflowNodeConfig
  | Record<string, unknown>;

export interface CanonicalFlowNode {
  id: string;
  type: CanonicalNodeType | string;
  /**
   * Execution semantics. Optional for backward compat: readers should
   * default to `'task'` when absent.
   */
  kind?: NodeKind;
  label?: string;
  /**
   * Section payload for builder-originated nodes. Free-form bag indexed
   * by the caller; the serializer only cares about the canonical keys.
   */
  data?: Record<string, unknown>;
  /** Typed input ports. Empty = implicit passthrough. */
  inputs?: NodePort[];
  /** Typed output ports. Empty = implicit passthrough. */
  outputs?: NodePort[];
  /** Kind-specific config. Shape depends on `kind`. */
  config?: KindConfig;
  /** Pixel position on the canvas. */
  position?: { x: number; y: number };
}

export interface CanonicalFlowEdge {
  from: string;
  to: string;
  /**
   * What travels on this edge. `data` = value passthrough (port→port),
   * `control` = pure sequencing, `branch` = outcome of a `decision`
   * or `fork` (requires `branch_label`).
   */
  kind?: 'data' | 'control' | 'branch';
  branch_label?: string;
  /** Source port name (when kind='data'). */
  from_port?: string;
  /** Target port name (when kind='data'). */
  to_port?: string;
  label?: string;
}

/** Runtime-relevant edge identity encoded without delimiter collisions. */
export function canonicalEdgeIdentity(edge: CanonicalFlowEdge): string {
  const branchLabel = edge.branch_label ?? edge.label ?? '';
  return JSON.stringify({
    branch_label: String(branchLabel),
    from: String(edge.from ?? ''),
    from_port: String(edge.from_port ?? ''),
    kind: String(edge.kind || 'data'),
    to: String(edge.to ?? ''),
    to_port: String(edge.to_port ?? ''),
  });
}

/**
 * A reusable flow starter. Persisted client-side in Vague C (starter
 * kit shipped with the app) and server-side in Vague D.
 */
export interface FlowTemplate {
  id: string;
  name: string;
  description?: string;
  category?: 'rag' | 'agent' | 'automation' | 'research' | 'compliance' | 'custom';
  /** Emoji or icon slug for quick visual identification. */
  icon?: string;
  flow: CanonicalFlow;
}

export interface CanonicalPolicy {
  max_cost?: number;
  max_latency_ms?: number;
  confidence_threshold?: number;
  temperature?: number;
  require_citations?: boolean;
  enable_audit?: boolean;
}

export interface CanonicalFlow {
  /** Free-form marker for specialised Systems (`intelligence`, …). */
  variant?: string;
  /** Which surface wrote this flow last. */
  source?: 'form' | 'flow';
  /**
   * `true` when the Flow graph carries nodes that do not map back to a
   * canonical Form section. The Form should then lock the affected
   * sections with an "Edited in Flow" badge.
   */
  extended?: boolean;

  nodes: CanonicalFlowNode[];
  edges: CanonicalFlowEdge[];

  /** Semantic mirror of the builder state — never authoritative on its
   *  own; the `nodes[]` graph stays the canonical projection. */
  policy?: CanonicalPolicy;
  collections?: string[];
  rag_mode?: string;
  canonical_rag_mode?: string;
  context_reused?: boolean;

  /** Optional template lineage (set when the flow was spawned from a
   *  FlowTemplate). Does not imply a live link — a flow is its own
   *  standalone graph once instantiated. */
  template_id?: string;
  template_name?: string;

  /** Optional schema version for the flow itself — lets us evolve the
   *  shape with safe migrations. Current = 3 (v1 = Vague A/B, v2 = C,
   *  v3 = variable-membrane: typed ports + `VariableRef` selectors).
   *  `normalize()` performs an idempotent, non-destructive v2→v3
   *  backfill so older flows keep working unchanged. */
  schema_version?: number;
  /** Overlay is legacy-compatible; strict is authoritative only behind the
   *  Workspace ``flow_v3_dag_authoritative`` feature. */
  io_mode?: 'overlay' | 'strict';
  /** Logical pool buckets written by outputs_map and readable by inputs_map. */
  variable_namespaces?: string[];
  /** Optional Flow-wide public result schema. */
  output_contract?: Record<string, unknown>;
}

/** Validation diagnostic for a flow graph. */
export interface FlowValidationIssue {
  level: 'error' | 'warn';
  node_id?: string;
  edge_index?: number;
  code:
    | 'flow_invalid'
    | 'nodes_invalid'
    | 'node_invalid'
    | 'edges_invalid'
    | 'edge_invalid'
    | 'node_id_duplicate'
    | 'edge_duplicate'
    | 'dangling_edge'
    | 'join_without_fork'
    | 'fork_without_join'
    | 'decision_no_branches'
    | 'decision_branch_invalid'
    | 'decision_condition_invalid'
    | 'decision_branch_duplicate'
    | 'decision_default_invalid'
    | 'decision_branch_unwired'
    | 'branch_edge_invalid'
    | 'fork_fanout_invalid'
    | 'fork_unjoined'
    | 'join_fanin_invalid'
    | 'join_without_matching_fork'
    | 'branch_label_invalid'
    | 'join_strategy_invalid'
    | 'task_no_skill'
    | 'cycle_detected'
    | 'unreachable_node'
    | 'port_type_mismatch'
    // v3: a ``config.inputs_map`` VariableRef points at a node_id/port
    // that is not a reserved namespace and not present upstream. Warn
    // level — design-time hint, never blocks a save.
    | 'variable_unresolved'
    | 'variable_contract_invalid'
    | 'hitl_no_prompt'
    | 'loop_no_budget'
    | 'retry_no_target'
    | 'ingress_kind_invalid'
    | 'ingress_node_kind_invalid'
    | 'ingress_source_not_root'
    | 'flow_output_sink_required'
    | 'flow_output_sink_ambiguous'
    // Emitted server-side by ``dag_validator.validate_flow`` when a
    // node has zero inbound *and* zero outbound edges in a multi-node
    // flow (leftover of a half-finished drag/drop). Vague E / E3.1.
    | 'node_orphan';
  message: string;
}

/**
 * A structural view of the builder draft. We keep this deliberately
 * loose (`Record<string, unknown>`-like) so the serializer does not
 * pull in the full `system-builder.component` typing — this service
 * lives in `core/` and must stay dependency-free.
 */
export interface SystemBuilderDraft {
  name: string;
  objective: string;
  capability_id: string | null;
  collections: string[];
  rag_mode: string;
  reuse_context_id: string | null;
  default_prompt_type: string;
  default_model: string;
  execution_mode: string;
  temperature: number;
  max_cost: number;
  max_latency_ms: number;
  confidence_threshold: number;
  require_citations: boolean;
  enable_audit: boolean;
}

export type CanonicalNodeId =
  | 'builder.objective'
  | 'builder.capability'
  | 'builder.skills'
  | 'builder.context'
  | 'builder.policy'
  | 'builder.launch';

const CANONICAL_NODE_IDS: readonly CanonicalNodeId[] = [
  'builder.objective',
  'builder.capability',
  'builder.skills',
  'builder.context',
  'builder.policy',
  'builder.launch',
] as const;

const CANONICAL_ID_SET = new Set<string>(CANONICAL_NODE_IDS);

/** Client-side structural check for the same deliberately small predicate DSL
 * accepted by the backend. The server remains authoritative; this catches
 * empty/unsafe expressions early without evaluating operator input. */
export function decisionConditionValidationError(expression: unknown): string | null {
  if (typeof expression !== 'string' || !expression.trim()) return 'condition_empty';

  const text = expression.trim();
  let masked = '';
  let quote = '';
  let escaped = false;
  const delimiters: string[] = [];
  const closing: Record<string, string> = { ')': '(', ']': '[', '}': '{' };

  for (const char of text) {
    if (quote) {
      masked += ' ';
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === quote) quote = '';
      continue;
    }
    if (char === "'" || char === '"') {
      quote = char;
      masked += 's';
      continue;
    }
    if (char === '(' || char === '[' || char === '{') delimiters.push(char);
    else if (char in closing && delimiters.pop() !== closing[char]) {
      return 'condition_syntax_error';
    }
    masked += char;
  }
  if (quote || delimiters.length > 0) return 'condition_syntax_error';

  // Python's expression AST admits only the nodes allowlisted by the runtime:
  // no calls, subscripts, comprehensions, mappings, arithmetic or assignment.
  if (/[^A-Za-z0-9_\s.,<>=!+\-()[\]{}]/.test(masked)) return 'condition_unsupported';
  if (/(^|[^<>=!])=($|[^=])/.test(masked)) return 'condition_syntax_error';
  if (/\b(lambda|if|else|for|while|await|yield|is)\b/.test(masked)) {
    return 'condition_unsupported';
  }
  if (/(?:\b[A-Za-z_]\w*|\])\s*\[/.test(masked)) return 'condition_unsupported';
  if (/(?:\w|\d|[)\]])\s*[+-]/.test(masked)) return 'condition_unsupported';

  const call = /\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*\(/g;
  for (const match of masked.matchAll(call)) {
    if (match[1] !== 'not') return 'condition_unsupported';
  }

  const allowedAttributeRoots = new Set([
    'ctx',
    'context',
    'workspace',
    'system',
    'run',
    'node',
  ]);
  const attributes = /\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)/g;
  for (const match of masked.matchAll(attributes)) {
    if (!allowedAttributeRoots.has(match[1])) return 'condition_unsupported';
  }
  const withoutAttributes = masked.replace(attributes, '').replace(/\d+\.\d+/g, '');
  if (withoutAttributes.includes('.')) return 'condition_unsupported';

  // Operators cannot be left dangling. This intentionally does not attempt
  // evaluation; the backend parser performs the final syntax proof.
  if (/\b(and|or|not|in)\s*$/.test(masked) || /^[<>=!,]/.test(masked)) {
    return 'condition_syntax_error';
  }
  return null;
}

function edgeBranchLabel(edge: CanonicalFlowEdge): string | null {
  const raw = edge.branch_label ?? edge.label;
  return typeof raw === 'string' && raw.trim() ? raw.trim() : null;
}

function distancesFrom(start: string, adj: Map<string, string[]>): Map<string, number> {
  const distances = new Map<string, number>([[start, 0]]);
  const queue = [start];
  while (queue.length > 0) {
    const current = queue.shift()!;
    for (const next of adj.get(current) ?? []) {
      if (distances.has(next)) continue;
      distances.set(next, (distances.get(current) ?? 0) + 1);
      queue.push(next);
    }
  }
  return distances;
}

function laneBypassesJoin(
  start: string,
  joinId: string,
  adj: Map<string, string[]>,
): boolean {
  const seen = new Set<string>();
  const stack = [start];
  while (stack.length > 0) {
    const current = stack.pop()!;
    if (current === joinId || seen.has(current)) continue;
    seen.add(current);
    const outgoing = adj.get(current) ?? [];
    if (outgoing.length === 0) return true;
    stack.push(...outgoing.filter((next) => next !== joinId));
  }
  return false;
}

@Injectable({ providedIn: 'root' })
export class FlowSerializerService {
  /**
   * Project a builder draft into a canonical flow. The emitted graph is
   * linear (Objective → Capability → Skills → Context → Policy → Launch)
   * and carries the semantic payload on each node's `data` bag so the
   * Flow UI can display meaningful labels without re-fetching anything.
   */
  formToFlow(draft: SystemBuilderDraft): CanonicalFlow {
    const nodes: CanonicalFlowNode[] = [
      {
        id: 'builder.objective',
        type: 'objective',
        kind: 'source',
        label: draft.name || 'Objective',
        data: { name: draft.name, objective: draft.objective },
        outputs: [{ name: 'goal', schema: 'string', description: 'User objective' }],
        position: { x: 60, y: 80 },
      },
      {
        id: 'builder.capability',
        type: 'capability',
        kind: 'task',
        label: 'Capability',
        data: { capability_id: draft.capability_id },
        inputs: [{ name: 'goal', schema: 'string' }],
        outputs: [{ name: 'plan', schema: 'object' }],
        position: { x: 320, y: 80 },
      },
      {
        id: 'builder.skills',
        type: 'skill',
        kind: 'task',
        label: 'Bundled skills',
        data: {},
        inputs: [{ name: 'plan', schema: 'object' }],
        outputs: [{ name: 'result', schema: 'object' }],
        position: { x: 580, y: 80 },
      },
      {
        id: 'builder.context',
        type: 'context',
        kind: 'task',
        label: 'Context',
        data: {
          collections: draft.collections,
          reuse_context_id: draft.reuse_context_id,
          rag_mode: draft.rag_mode,
        },
        inputs: [{ name: 'result', schema: 'object' }],
        outputs: [{ name: 'grounded', schema: 'object' }],
        position: { x: 840, y: 80 },
      },
      {
        id: 'builder.policy',
        type: 'policy',
        kind: 'task',
        label: 'Policy',
        data: {
          execution_mode: draft.execution_mode,
          default_prompt_type: draft.default_prompt_type,
          default_model: draft.default_model,
          policy: this.policyFromDraft(draft),
        },
        inputs: [{ name: 'grounded', schema: 'object' }],
        outputs: [{ name: 'checked', schema: 'object' }],
        position: { x: 1100, y: 80 },
      },
      {
        id: 'builder.launch',
        type: 'launch',
        kind: 'sink',
        label: 'Launch',
        data: {},
        inputs: [{ name: 'checked', schema: 'object' }],
        position: { x: 1360, y: 80 },
      },
    ];

    const edges: CanonicalFlowEdge[] = [];
    for (let i = 0; i < nodes.length - 1; i += 1) {
      edges.push({ from: nodes[i].id, to: nodes[i + 1].id, kind: 'data' });
    }

    return {
      source: 'form',
      extended: false,
      schema_version: 3,
      nodes,
      edges,
      policy: this.policyFromDraft(draft),
      collections: [...draft.collections],
      rag_mode: draft.rag_mode,
      canonical_rag_mode: this.canonicalRagMode(draft.rag_mode),
      context_reused: !!draft.reuse_context_id,
    };
  }

  /**
   * Read a canonical flow back into a builder draft. `current` acts as
   * a fallback for every field missing from the flow — we never clobber
   * user-typed values with `undefined`.
   *
   * Returns `extended: true` as soon as the flow carries at least one
   * non-canonical node; the Form is expected to lock the corresponding
   * sections.
   */
  flowToForm(
    flow: CanonicalFlow | null | undefined,
    current: SystemBuilderDraft,
  ): { draft: SystemBuilderDraft; extended: boolean } {
    if (!flow || !Array.isArray(flow.nodes)) {
      return { draft: current, extended: false };
    }

    const byId = new Map<string, CanonicalFlowNode>();
    for (const n of flow.nodes) byId.set(n.id, n);

    const extended =
      flow.extended === true ||
      flow.nodes.some(
        (n) => !CANONICAL_ID_SET.has(n.id) && n.type !== 'source' && n.type !== 'sink',
      );

    const objData = byId.get('builder.objective')?.data ?? {};
    const capData = byId.get('builder.capability')?.data ?? {};
    const ctxData = byId.get('builder.context')?.data ?? {};
    const polData = byId.get('builder.policy')?.data ?? {};
    const policy = this.readPolicy(polData['policy']) ?? flow.policy ?? {};

    const next: SystemBuilderDraft = {
      ...current,
      name: this.str(objData['name'], current.name),
      objective: this.str(objData['objective'], current.objective),
      capability_id: this.strOrNull(capData['capability_id'], current.capability_id),
      collections: this.strArr(
        ctxData['collections'] ?? flow.collections,
        current.collections,
      ),
      rag_mode: this.str(ctxData['rag_mode'] ?? flow.rag_mode, current.rag_mode),
      reuse_context_id: this.strOrNull(
        ctxData['reuse_context_id'],
        current.reuse_context_id,
      ),
      default_prompt_type: this.str(
        polData['default_prompt_type'],
        current.default_prompt_type,
      ),
      default_model: this.str(polData['default_model'], current.default_model),
      execution_mode: this.str(polData['execution_mode'], current.execution_mode),
      temperature: this.num(policy.temperature, current.temperature),
      max_cost: this.num(policy.max_cost, current.max_cost),
      max_latency_ms: this.num(policy.max_latency_ms, current.max_latency_ms),
      confidence_threshold: this.num(
        policy.confidence_threshold,
        current.confidence_threshold,
      ),
      require_citations: this.bool(policy.require_citations, current.require_citations),
      enable_audit: this.bool(policy.enable_audit, current.enable_audit),
    };

    return { draft: next, extended };
  }

  /**
   * Merge a freshly-projected flow with the semantic sidecars that the
   * form wrote last. Called right before persisting — we keep the
   * `collections`/`rag_mode`/`policy` mirrors in sync with whatever the
   * builder node's `data` bag carries, so downstream consumers that
   * still read `flow_definition.collections` (the canonical run engine,
   * RAG wrappers) keep working unchanged.
   */
  annotateSidecars(flow: CanonicalFlow): CanonicalFlow {
    const ctx = flow.nodes.find((n) => n.id === 'builder.context')?.data ?? {};
    const pol = flow.nodes.find((n) => n.id === 'builder.policy')?.data ?? {};
    const policy = this.readPolicy(pol['policy']);
    return {
      ...flow,
      collections: this.strArr(ctx['collections'], flow.collections ?? []),
      rag_mode: this.str(ctx['rag_mode'], flow.rag_mode ?? 'OmniRAG'),
      canonical_rag_mode: this.canonicalRagMode(
        this.str(ctx['rag_mode'], flow.rag_mode ?? 'OmniRAG'),
      ),
      context_reused: !!ctx['reuse_context_id'] || flow.context_reused === true,
      policy: policy ?? flow.policy,
    };
  }

  // ---------- C1 extensions: normalization / validation / topo / runnables ----------

  /** Convert a legacy dot path only when its owner is deterministic.
   *
   * Node ids may contain dots (``task.retrieve.primary``), therefore the
   * longest matching id wins before built-in/declared namespaces are tested.
   * ``null`` means the selector is unknown or structurally ambiguous; callers
   * must preserve the original string and surface validation instead of
   * guessing.
   */
  dotPathToVariableRef(selector: string, flow: CanonicalFlow): VariableRef | null {
    const text = String(selector ?? '').trim();
    if (!text) return null;
    const pathSegments = (tail: string): string[] | null => {
      if (!tail) return [];
      const segments = tail.split('.');
      return segments.some((segment) => segment.trim().length === 0) ? null : segments;
    };
    const nodeIds = flow.nodes.map((node) => node.id).filter((id) => !!id);
    const matches = nodeIds.filter((id) => text === id || text.startsWith(`${id}.`));
    if (matches.length > 0) {
      const longest = Math.max(...matches.map((id) => id.length));
      const winners = matches.filter((id) => id.length === longest);
      if (winners.length !== 1) return null;
      const owner = winners[0];
      const tail = text === owner ? '' : text.slice(owner.length + 1);
      if (text !== owner && !tail) return null;
      const path = pathSegments(tail);
      return path === null ? null : { node_id: owner, path };
    }
    const [head, ...path] = text.split('.');
    const declared = new Set((flow.variable_namespaces ?? []).filter((item) => !!item));
    if (!RESERVED_VARIABLE_NAMESPACES.includes(head) && !declared.has(head)) return null;
    return path.some((segment) => segment.trim().length === 0)
      ? null
      : { node_id: head, path };
  }

  /**
   * Ensure every node carries a `kind` (defaults to `'task'`) and has
   * the minimal shape downstream consumers expect. Performs an
   * idempotent, non-destructive v2→v3 backfill:
   *   - stamps `schema_version: 3` (keeps a higher version if present);
   *   - infers a node's typed input/output ports from the `data` edges
   *     that name a port (`from_port`/`to_port`) when the node declares
   *     none — so a node that participates in dataflow gets an explicit
   *     signature;
   *   - leaves legacy `inputs_map` dot-path strings exactly as-is (no
   *     destructive rewrite to `VariableRef`).
   * Idempotent: a second pass sees the ports already present and skips.
   */
  normalize(flow: CanonicalFlow): CanonicalFlow {
    const edges = flow.edges.map((e) => ({
      ...e,
      kind: e.kind ?? 'data',
    }));

    // Collect port names named by data edges, per node + direction.
    const inferredIn = new Map<string, Set<string>>();
    const inferredOut = new Map<string, Set<string>>();
    for (const e of edges) {
      if (e.kind !== 'data') continue;
      if (e.to_port) {
        (inferredIn.get(e.to) ?? inferredIn.set(e.to, new Set()).get(e.to)!).add(e.to_port);
      }
      if (e.from_port) {
        (inferredOut.get(e.from) ?? inferredOut.set(e.from, new Set()).get(e.from)!).add(
          e.from_port,
        );
      }
    }

    const normalizedNodes = flow.nodes.map((n) => {
      const base = this.normalizeNode(n);
      const wantIn = (base.inputs?.length ?? 0) === 0 && inferredIn.has(base.id);
      const wantOut = (base.outputs?.length ?? 0) === 0 && inferredOut.has(base.id);
      if (!wantIn && !wantOut) return base;
      return {
        ...base,
        inputs: wantIn
          ? [...inferredIn.get(base.id)!].map((name) => ({ name, schema: 'object' }))
          : base.inputs,
        outputs: wantOut
          ? [...inferredOut.get(base.id)!].map((name) => ({ name, schema: 'object' }))
          : base.outputs,
      };
    });

    const conversionFlow: CanonicalFlow = { ...flow, nodes: normalizedNodes, edges };
    const nodes =
      flow.io_mode === 'strict'
        ? normalizedNodes.map((node) => {
            const config = { ...(node.config ?? {}) } as Record<string, unknown>;
            const rawMap = config['inputs_map'];
            if (!rawMap || typeof rawMap !== 'object' || Array.isArray(rawMap)) return node;
            const inputsMap = { ...(rawMap as Record<string, unknown>) };
            for (const [port, selector] of Object.entries(inputsMap)) {
              if (typeof selector !== 'string') continue;
              inputsMap[port] = this.dotPathToVariableRef(selector, conversionFlow) ?? selector;
            }
            return { ...node, config: { ...config, inputs_map: inputsMap } };
          })
        : normalizedNodes;

    const sv =
      typeof flow.schema_version === 'number' && flow.schema_version >= 3
        ? flow.schema_version
        : 3;
    return {
      ...flow,
      schema_version: sv,
      nodes,
      edges,
    };
  }

  normalizeNode(node: CanonicalFlowNode): CanonicalFlowNode {
    return {
      ...node,
      kind: node.kind ?? 'task',
      inputs: node.inputs ?? [],
      outputs: node.outputs ?? [],
      config: node.config ?? {},
    };
  }

  /**
   * Static validation pass against a canonical flow. Runs in O(V+E),
   * never throws — returns a list of diagnostics the UI can surface as
   * inline hints or a validation panel.
   */
  validateFlow(flow: CanonicalFlow): FlowValidationIssue[] {
    const issues: FlowValidationIssue[] = [];
    const ids = new Set(flow.nodes.map((n) => n.id));
    const strict = flow.io_mode === 'strict';
    const declaredNamespaces = new Set(
      (flow.variable_namespaces ?? []).filter((item) => typeof item === 'string' && !!item),
    );
    if (flow.io_mode !== undefined && flow.io_mode !== 'overlay' && flow.io_mode !== 'strict') {
      issues.push({
        level: 'error',
        code: 'variable_contract_invalid',
        message: "io_mode must be 'overlay' or 'strict'.",
      });
    }
    if (strict && (flow.schema_version ?? 0) < 3) {
      issues.push({
        level: 'error',
        code: 'variable_contract_invalid',
        message: "io_mode 'strict' requires schema_version >= 3.",
      });
    }
    const reservedRedeclarations = [...declaredNamespaces].filter((item) =>
      RESERVED_VARIABLE_NAMESPACES.includes(item),
    );
    if (reservedRedeclarations.length > 0) {
      issues.push({
        level: 'error',
        code: 'variable_contract_invalid',
        message: `Built-in namespace(s) cannot be redeclared: ${reservedRedeclarations.join(', ')}.`,
      });
    }

    const nodeIdCounts = new Map<string, number>();
    for (const node of flow.nodes) {
      nodeIdCounts.set(node.id, (nodeIdCounts.get(node.id) ?? 0) + 1);
    }
    for (const [nodeId, count] of [...nodeIdCounts.entries()]
      .filter(([, count]) => count > 1)
      .sort(([left], [right]) => left.localeCompare(right))) {
      issues.push({
        level: 'error',
        node_id: nodeId,
        code: 'node_id_duplicate',
        message: `Node id "${nodeId}" is declared ${count} times; node ids must be unique.`,
      });
    }

    const firstEdgeIndex = new Map<string, number>();
    flow.edges.forEach((edge, edgeIndex) => {
      const identity = canonicalEdgeIdentity(edge);
      if (firstEdgeIndex.has(identity)) {
        issues.push({
          level: 'error',
          edge_index: edgeIndex,
          code: 'edge_duplicate',
          message: 'This route duplicates an earlier edge structurally.',
        });
      } else {
        firstEdgeIndex.set(identity, edgeIndex);
      }
    });

    if (issues.some(
      (issue) => issue.code === 'node_id_duplicate' || issue.code === 'edge_duplicate',
    )) {
      return issues;
    }

    if (strict) {
      const sinkIds = flow.nodes
        .filter((node) => (node.kind ?? 'task') === 'sink')
        .map((node) => node.id)
        .sort();
      if (sinkIds.length === 0) {
        issues.push({
          level: 'error',
          code: 'flow_output_sink_required',
          message: 'A strict Flow must declare exactly one explicit Output node.',
        });
      } else if (sinkIds.length > 1) {
        issues.push({
          level: 'error',
          code: 'flow_output_sink_ambiguous',
          message: `A strict Flow must declare exactly one explicit Output node; found ${sinkIds.length} (${sinkIds.join(', ')}).`,
        });
      }
    }
    const adj = new Map<string, string[]>();
    const rev = new Map<string, string[]>();
    flow.nodes.forEach((n) => {
      adj.set(n.id, []);
      rev.set(n.id, []);
    });

    flow.edges.forEach((e, idx) => {
      if (!ids.has(e.from) || !ids.has(e.to)) {
        issues.push({
          level: 'error',
          edge_index: idx,
          code: 'dangling_edge',
          message: `Edge ${e.from} → ${e.to} references unknown node(s).`,
        });
        return;
      }
      adj.get(e.from)!.push(e.to);
      rev.get(e.to)!.push(e.from);
    });

    for (const n of flow.nodes) {
      const kind = n.kind ?? 'task';
      const cfg = (n.config ?? {}) as Record<string, unknown>;

      if (Object.prototype.hasOwnProperty.call(cfg, 'ingress_kind')) {
        const ingressKind = cfg['ingress_kind'];
        if (
          typeof ingressKind !== 'string' ||
          !['manual', 'chat', 'http', 'schedule', 'event'].includes(ingressKind)
        ) {
          issues.push({
            level: 'error',
            node_id: n.id,
            code: 'ingress_kind_invalid',
            message: 'An entry point must be manual, chat, http, schedule or event.',
          });
        } else if (kind !== 'source') {
          issues.push({
            level: 'error',
            node_id: n.id,
            code: 'ingress_node_kind_invalid',
            message: 'Only a source node can declare an entry point.',
          });
        }
      }
      if (kind === 'source' && (rev.get(n.id)?.length ?? 0) > 0) {
        issues.push({
          level: 'error',
          node_id: n.id,
          code: 'ingress_source_not_root',
          message: 'An executable entry point cannot have inbound edges.',
        });
      }

      if (kind === 'task') {
        const skillId = cfg['skill_id'];
        const skillSlug = cfg['skill_slug'];
        const runtimeRef = cfg['runtime_ref'];
        const hasSkill =
          (typeof skillId === 'string' && skillId.length > 0) ||
          (typeof skillSlug === 'string' && skillSlug.length > 0);
        const hasRuntimeRef = typeof runtimeRef === 'string' && runtimeRef.trim().length > 0;
        const isBuilderNode = CANONICAL_ID_SET.has(n.id);
        if (!hasSkill && !hasRuntimeRef && !isBuilderNode) {
          issues.push({
            level: 'warn',
            node_id: n.id,
            code: 'task_no_skill',
            message: `Task node "${n.label ?? n.id}" has no Skill bound.`,
          });
        }
      }
      if (kind === 'decision') {
        const rawBranches = cfg['branches'];
        if (!Array.isArray(rawBranches) || rawBranches.length < 2) {
          issues.push({
            level: 'error',
            node_id: n.id,
            code: 'decision_no_branches',
            message: `Decision "${n.label ?? n.id}" needs at least two branches.`,
          });
        } else {
          const labels: string[] = [];
          rawBranches.forEach((rawBranch, branchIndex) => {
            if (!rawBranch || typeof rawBranch !== 'object' || Array.isArray(rawBranch)) {
              issues.push({
                level: 'error',
                node_id: n.id,
                code: 'decision_branch_invalid',
                message: `Decision branch ${branchIndex + 1} must be an object.`,
              });
              return;
            }
            const branch = rawBranch as Record<string, unknown>;
            const rawLabel = branch['label'];
            const label = typeof rawLabel === 'string' ? rawLabel.trim() : '';
            if (!label || label !== rawLabel) {
              issues.push({
                level: 'error',
                node_id: n.id,
                code: 'decision_branch_invalid',
                message: `Decision branch ${branchIndex + 1} needs a non-empty, already-trimmed label.`,
              });
            } else {
              labels.push(label);
            }

            const conditionError = decisionConditionValidationError(branch['condition']);
            if (conditionError) {
              issues.push({
                level: 'error',
                node_id: n.id,
                code: 'decision_condition_invalid',
                message: `Decision branch "${label || branchIndex + 1}" has an invalid condition (${conditionError}).`,
              });
            }
          });

          const duplicates = [...new Set(labels.filter(
            (label) => labels.filter((candidate) => candidate === label).length > 1,
          ))].sort();
          if (duplicates.length > 0) {
            issues.push({
              level: 'error',
              node_id: n.id,
              code: 'decision_branch_duplicate',
              message: `Decision branch labels must be unique: ${duplicates.join(', ')}`,
            });
          }

          const defaultBranch = cfg['default_branch'];
          if (
            defaultBranch !== undefined &&
            (
              typeof defaultBranch !== 'string' ||
              !defaultBranch.trim() ||
              !labels.includes(defaultBranch)
            )
          ) {
            issues.push({
              level: 'error',
              node_id: n.id,
              code: 'decision_default_invalid',
              message: 'Decision default_branch must reference an existing branch label.',
            });
          }

          const routedLabels = new Set(
            flow.edges
              .filter((edge) => edge.from === n.id && (edge.kind ?? 'data') === 'branch')
              .map(edgeBranchLabel)
              .filter((label): label is string => label !== null),
          );
          for (const label of [...new Set(labels)].sort()) {
            if (routedLabels.has(label)) continue;
            issues.push({
              level: 'error',
              node_id: n.id,
              code: 'decision_branch_unwired',
              message: `Decision branch "${label}" has no outgoing branch edge.`,
            });
          }
        }
      }
      if (kind === 'loop') {
        const budget = cfg['max_iterations'];
        if (
          typeof budget !== 'number' ||
          !Number.isSafeInteger(budget) ||
          budget <= 0
        ) {
          issues.push({
            level: 'error',
            node_id: n.id,
            code: 'loop_no_budget',
            message: `Loop "${n.label ?? n.id}" is missing a positive max_iterations budget.`,
          });
        }
      }
      if (kind === 'agent_loop') {
        const budget = (cfg['budget'] ?? {}) as { max_turns?: unknown };
        const maxTurns = budget.max_turns ?? cfg['max_turns'];
        if (
          typeof maxTurns !== 'number' ||
          !Number.isSafeInteger(maxTurns) ||
          maxTurns <= 0
        ) {
          issues.push({
            level: 'error',
            node_id: n.id,
            code: 'agent_loop_no_budget',
            message: `Agent loop "${n.label ?? n.id}" is missing a positive max_turns budget.`,
          });
        }
        const allowlist = cfg['skill_allowlist'];
        if (!Array.isArray(allowlist) || allowlist.length < 1 || allowlist.length > 8) {
          issues.push({
            level: 'error',
            node_id: n.id,
            code: 'agent_loop_allowlist',
            message: `Agent loop "${n.label ?? n.id}" needs a skill_allowlist of 1–8 slugs.`,
          });
        }
      }
      if (kind === 'retry') {
        const attempts = cfg['max_attempts'];
        if (
          typeof attempts !== 'number' ||
          !Number.isSafeInteger(attempts) ||
          attempts <= 0
        ) {
          issues.push({
            level: 'error',
            node_id: n.id,
            code: 'retry_no_target',
            message: `Retry "${n.label ?? n.id}" is missing a positive max_attempts.`,
          });
        }
      }
      if (kind === 'hitl') {
        const prompt = cfg['prompt'];
        if (typeof prompt !== 'string' || prompt.trim().length === 0) {
          issues.push({
            level: 'warn',
            node_id: n.id,
            code: 'hitl_no_prompt',
            message: `Human approval "${n.label ?? n.id}" should include an approver prompt.`,
          });
        }
      }
    }

    const byId = new Map(flow.nodes.map((n) => [n.id, n] as const));

    // Branch edges are routing primitives owned by a declared Decision route.
    flow.edges.forEach((edge, edgeIndex) => {
      if ((edge.kind ?? 'data') !== 'branch') return;
      const source = byId.get(edge.from);
      const rawBranches = (source?.config as Record<string, unknown> | undefined)?.['branches'];
      const declared = new Set(
        (Array.isArray(rawBranches) ? rawBranches : [])
          .filter((branch) => !!branch && typeof branch === 'object' && !Array.isArray(branch))
          .map((branch) => (branch as Record<string, unknown>)['label'])
          .filter((label): label is string => typeof label === 'string'),
      );
      const label = edgeBranchLabel(edge);
      if (!source || (source.kind ?? 'task') !== 'decision' || !label || !declared.has(label)) {
        issues.push({
          level: 'error',
          node_id: source?.id,
          edge_index: edgeIndex,
          code: 'branch_edge_invalid',
          message: 'Branch edges must originate from a Decision and carry one of its declared branch labels.',
        });
      }
    });

    const hasCycle = this.hasCycle(adj);
    if (hasCycle) {
      issues.push({
        level: 'error',
        code: 'cycle_detected',
        message: 'Flow contains a cycle outside a loop node. Use a loop kind for controlled iteration.',
      });
    } else {
      const topologyLevel: FlowValidationIssue['level'] = strict ? 'error' : 'warn';
      const forks = flow.nodes
        .filter((node) => (node.kind ?? 'task') === 'fork')
        .map((node) => node.id)
        .sort();
      const joins = flow.nodes
        .filter((node) => (node.kind ?? 'task') === 'join')
        .map((node) => node.id)
        .sort();
      const matchedJoins = new Set<string>();

      for (const joinId of joins) {
        const join = byId.get(joinId)!;
        const strategy = String(
          (join.config as Record<string, unknown> | undefined)?.['strategy'] ?? 'all',
        ).toLowerCase();
        if (!['all', 'any', 'race'].includes(strategy)) {
          issues.push({
            level: topologyLevel,
            node_id: joinId,
            code: 'join_strategy_invalid',
            message: `Join "${joinId}" has unsupported strategy "${strategy}".`,
          });
        }
        if (new Set(rev.get(joinId) ?? []).size < 2) {
          issues.push({
            level: topologyLevel,
            node_id: joinId,
            code: 'join_fanin_invalid',
            message: `Join "${joinId}" needs at least two distinct inbound lanes.`,
          });
        }
      }

      for (const forkId of forks) {
        const outgoing = flow.edges.filter((edge) => edge.from === forkId);
        const lanes = [...new Set(outgoing.map((edge) => edge.to))].sort();
        if (lanes.length < 2) {
          issues.push({
            level: topologyLevel,
            node_id: forkId,
            code: 'fork_fanout_invalid',
            message: `Fork "${forkId}" needs at least two distinct outgoing lanes.`,
          });
        }

        const rawExpected = (
          byId.get(forkId)?.config as Record<string, unknown> | undefined
        )?.['branches'];
        const expected = Array.isArray(rawExpected)
          ? rawExpected
            .filter((label): label is string => typeof label === 'string' && !!label.trim())
            .map((label) => label.trim())
          : [];
        const observed = outgoing.map((edge) => {
          const label = edgeBranchLabel(edge);
          if (label) return label;
          return typeof edge.from_port === 'string' && edge.from_port.trim()
            ? edge.from_port.trim()
            : null;
        });
        const expectedSet = new Set(expected);
        const observedSet = new Set(observed.filter((label): label is string => label !== null));
        const labelsMatch =
          expected.length >= 2 &&
          expectedSet.size === expected.length &&
          observed.every((label) => label !== null) &&
          expectedSet.size === observedSet.size &&
          [...expectedSet].every((label) => observedSet.has(label));
        if (!labelsMatch) {
          issues.push({
            level: topologyLevel,
            node_id: forkId,
            code: 'branch_label_invalid',
            message: `Fork "${forkId}" route labels must be unique and match config.branches.`,
          });
        }

        if (lanes.length < 2) continue;
        const laneDistances = lanes.map((lane) => distancesFrom(lane, adj));
        const candidates = joins
          .filter((joinId) => laneDistances.every((distances) => distances.has(joinId)))
          .sort((left, right) => {
            const leftDistances = laneDistances.map((distances) => distances.get(left)!);
            const rightDistances = laneDistances.map((distances) => distances.get(right)!);
            return (
              Math.max(...leftDistances) - Math.max(...rightDistances) ||
              leftDistances.reduce((sum, value) => sum + value, 0) -
                rightDistances.reduce((sum, value) => sum + value, 0) ||
              left.localeCompare(right)
            );
          });
        const candidate = candidates[0];
        if (
          candidate &&
          !lanes.some((lane) => laneBypassesJoin(lane, candidate, adj))
        ) {
          matchedJoins.add(candidate);
        } else {
          issues.push({
            level: topologyLevel,
            node_id: forkId,
            code: 'fork_unjoined',
            message: `Fork "${forkId}" has no join that reconverges and post-dominates every lane.`,
          });
        }
      }

      for (const joinId of joins) {
        if (matchedJoins.has(joinId)) continue;
        issues.push({
          level: topologyLevel,
          node_id: joinId,
          code: 'join_without_matching_fork',
          message: `Join "${joinId}" is not paired with a real upstream fork.`,
        });
      }
    }

    // v3 — data-membrane diagnostics (both warn level; never block a
    // save). Kept in lockstep with the backend ``dag_validator``.

    // port_type_mismatch: a kind='data' edge whose from_port/to_port
    // reference declared ports with incompatible *primitive* schemas.
    flow.edges.forEach((e, idx) => {
      if ((e.kind ?? 'data') !== 'data') return;
      if (!e.from_port || !e.to_port) return;
      const src = byId.get(e.from);
      const dst = byId.get(e.to);
      if (!src || !dst) return; // already reported as dangling_edge
      const outPort = (src.outputs ?? []).find((p) => p.name === e.from_port);
      const inPort = (dst.inputs ?? []).find((p) => p.name === e.to_port);
      if (!outPort || !inPort) return; // can't compare undeclared ports
      if (primitivesIncompatible(outPort.schema, inPort.schema)) {
        issues.push({
          level: 'warn',
          edge_index: idx,
          code: 'port_type_mismatch',
          message: `Edge ${e.from}.${e.from_port} (${outPort.schema}) → ${e.to}.${e.to_port} (${inPort.schema}) connects incompatible types.`,
        });
      }
    });

    // variable_unresolved: a config.inputs_map VariableRef points at a
    // node_id/port not present upstream. Overlay leaves legacy strings opaque;
    // strict converts only deterministic paths and rejects everything else.
    for (const n of flow.nodes) {
      const config = (n.config as Record<string, unknown> | undefined) ?? {};
      const inputsMap = config['inputs_map'];
      let ancestors: Set<string> | null = null;
      if (inputsMap && typeof inputsMap === 'object' && !Array.isArray(inputsMap)) {
        for (const [port, stored] of Object.entries(inputsMap as Record<string, unknown>)) {
          let raw = stored;
          if (typeof raw === 'string' && strict) {
            const converted = this.dotPathToVariableRef(raw, flow);
            if (!converted) {
              issues.push({
                level: 'error',
                node_id: n.id,
                code: 'variable_unresolved',
                message: `Input "${port}" selector "${raw}" has no unambiguous owner.`,
              });
              continue;
            }
            raw = converted;
          }
          const refCandidate =
            !!raw &&
            typeof raw === 'object' &&
            !Array.isArray(raw) &&
            ['node_id', 'path', 'required'].some((key) => key in (raw as object));
          const refError = refCandidate ? variableRefValidationError(raw) : null;
          if (refError) {
            issues.push({
              level: strict ? 'error' : 'warn',
              node_id: n.id,
              code: 'variable_contract_invalid',
              message: `Input "${port}" has an invalid VariableRef (${refError}).`,
            });
            continue;
          }
          if (!this.isVariableRef(raw)) {
            if (strict) {
              issues.push({
                level: 'error',
                node_id: n.id,
                code: 'variable_unresolved',
                message: `Input "${port}" must be a VariableRef in strict mode.`,
              });
            }
            continue;
          }
          const ref = raw as VariableRef;
          if (
            RESERVED_VARIABLE_NAMESPACES.includes(ref.node_id) ||
            declaredNamespaces.has(ref.node_id)
          ) {
            continue;
          }
          if (!ids.has(ref.node_id)) {
            issues.push({
              level: strict ? 'error' : 'warn',
              node_id: n.id,
              code: 'variable_unresolved',
              message: `Input "${port}" references unknown node "${ref.node_id}".`,
            });
            continue;
          }
          if (ancestors === null) ancestors = this.ancestorsOf(n.id, rev);
          if (!ancestors.has(ref.node_id)) {
            issues.push({
              level: strict ? 'error' : 'warn',
              node_id: n.id,
              code: 'variable_unresolved',
              message: `Input "${port}" reads from "${ref.node_id}", which is not upstream of "${n.id}".`,
            });
            continue;
          }
          const srcOutputs = byId.get(ref.node_id)?.outputs ?? [];
          const head = ref.path[0];
          if (srcOutputs.length > 0 && head && !srcOutputs.some((p) => p.name === head)) {
            issues.push({
              level: strict ? 'error' : 'warn',
              node_id: n.id,
              code: 'variable_unresolved',
              message: `Input "${port}" reads port "${head}" not declared on "${ref.node_id}".`,
            });
          }
        }
      }

      if (strict) {
        const passthrough = config['passthrough_inputs'];
        if (
          passthrough !== undefined &&
          (!Array.isArray(passthrough) || passthrough.some((item) => typeof item !== 'string' || !item))
        ) {
          issues.push({
            level: 'error',
            node_id: n.id,
            code: 'variable_contract_invalid',
            message: 'passthrough_inputs must be a list of input field names.',
          });
        }
        const outputsMap = config['outputs_map'];
        if (outputsMap && typeof outputsMap === 'object' && !Array.isArray(outputsMap)) {
          for (const [port, target] of Object.entries(outputsMap as Record<string, unknown>)) {
            const head = typeof target === 'string' ? target.split('.', 1)[0] : '';
            if (!head || !declaredNamespaces.has(head)) {
              issues.push({
                level: 'error',
                node_id: n.id,
                code: 'variable_contract_invalid',
                message: `Output "${port}" writes an undeclared logical namespace.`,
              });
            }
          }
        }
      }
    }

    return issues;
  }

  /** A value is a typed VariableRef (v3) iff it carries a string
   *  `node_id` and an array `path`; anything else (incl. legacy dot-path
   *  strings) is treated as opaque and skipped by validation. */
  private isVariableRef(value: unknown): value is VariableRef {
    return isValidVariableRef(value);
  }

  /** Backward-reachable set (ancestors) of `nodeId` over the reverse
   *  adjacency built from the (purified) edge list. */
  private ancestorsOf(nodeId: string, rev: Map<string, string[]>): Set<string> {
    const seen = new Set<string>();
    const stack = [...(rev.get(nodeId) ?? [])];
    while (stack.length > 0) {
      const cur = stack.pop()!;
      if (seen.has(cur)) continue;
      seen.add(cur);
      stack.push(...(rev.get(cur) ?? []));
    }
    return seen;
  }

  /**
   * Kahn topological sort. Returns `null` when the graph has a cycle
   * (use validateFlow to surface the diagnostic). Used by the client
   * simulator and the C6 backend extraction step.
   */
  topoSort(flow: CanonicalFlow): string[] | null {
    const indeg = new Map<string, number>();
    const adj = new Map<string, string[]>();
    flow.nodes.forEach((n) => {
      indeg.set(n.id, 0);
      adj.set(n.id, []);
    });
    flow.edges.forEach((e) => {
      if (!indeg.has(e.from) || !indeg.has(e.to)) return;
      indeg.set(e.to, (indeg.get(e.to) ?? 0) + 1);
      adj.get(e.from)!.push(e.to);
    });

    const queue: string[] = [];
    indeg.forEach((deg, id) => {
      if (deg === 0) queue.push(id);
    });

    const out: string[] = [];
    while (queue.length > 0) {
      const id = queue.shift()!;
      out.push(id);
      for (const next of adj.get(id) ?? []) {
        const d = (indeg.get(next) ?? 0) - 1;
        indeg.set(next, d);
        if (d === 0) queue.push(next);
      }
    }
    return out.length === flow.nodes.length ? out : null;
  }

  /**
   * Extract the ordered list of Skill slugs that the backend run engine
   * should execute, based on the flow's task nodes. Non-task kinds are
   * reported as `skipped_kinds` so the UI can warn that advanced nodes
   * are client-simulated only (until the C6 DAG runtime ships).
   */
  extractRunnableSkills(
    flow: CanonicalFlow,
    skillIdToSlug: (id: string) => string | undefined,
  ): { slugs: string[]; skipped_kinds: NodeKind[] } {
    const order = this.topoSort(flow) ?? flow.nodes.map((n) => n.id);
    const byId = new Map(flow.nodes.map((n) => [n.id, n] as const));
    const slugs: string[] = [];
    const skipped: NodeKind[] = [];

    for (const id of order) {
      const node = byId.get(id);
      if (!node) continue;
      const kind = node.kind ?? 'task';
      // `asset` is a declarative data source (structurally like `source`):
      // it binds no skill and never runs, so it is skipped silently rather
      // than reported as an advanced, client-simulated kind.
      if (kind === 'source' || kind === 'sink' || kind === 'asset') continue;
      if (kind !== 'task') {
        skipped.push(kind);
        continue;
      }
      const cfg = (node.config ?? {}) as TaskNodeConfig;
      const slug = cfg.skill_slug ?? (cfg.skill_id ? skillIdToSlug(cfg.skill_id) : undefined);
      if (slug) slugs.push(slug);
    }

    return { slugs, skipped_kinds: skipped };
  }

  private hasCycle(adj: Map<string, string[]>): boolean {
    const white = new Set(adj.keys());
    const gray = new Set<string>();
    const black = new Set<string>();

    const visit = (id: string): boolean => {
      if (black.has(id)) return false;
      if (gray.has(id)) return true;
      gray.add(id);
      white.delete(id);
      for (const next of adj.get(id) ?? []) {
        if (visit(next)) return true;
      }
      gray.delete(id);
      black.add(id);
      return false;
    };

    while (white.size > 0) {
      const id = white.values().next().value as string;
      if (visit(id)) return true;
    }
    return false;
  }

  // ---------- helpers ----------

  private policyFromDraft(draft: SystemBuilderDraft): CanonicalPolicy {
    return {
      max_cost: draft.max_cost,
      max_latency_ms: draft.max_latency_ms,
      confidence_threshold: draft.confidence_threshold,
      temperature: draft.temperature,
      require_citations: draft.require_citations,
      enable_audit: draft.enable_audit,
    };
  }

  private readPolicy(raw: unknown): CanonicalPolicy | undefined {
    if (!raw || typeof raw !== 'object') return undefined;
    const p = raw as Record<string, unknown>;
    return {
      max_cost: this.maybeNum(p['max_cost']),
      max_latency_ms: this.maybeNum(p['max_latency_ms']),
      confidence_threshold: this.maybeNum(p['confidence_threshold']),
      temperature: this.maybeNum(p['temperature']),
      require_citations: this.maybeBool(p['require_citations']),
      enable_audit: this.maybeBool(p['enable_audit']),
    };
  }

  private canonicalRagMode(label: string): string {
    switch (label) {
      case 'OmniRAG':
        return 'chah';
      case 'HAH':
        return 'hah';
      case 'Hybrid':
        return 'hybrid';
      case 'Semantic':
        return 'naive';
      case 'None':
        return 'auto';
      default:
        return 'auto';
    }
  }

  private str(v: unknown, fallback: string): string {
    return typeof v === 'string' && v.length > 0 ? v : fallback;
  }

  private strOrNull(v: unknown, fallback: string | null): string | null {
    if (typeof v === 'string') return v;
    if (v === null) return null;
    return fallback;
  }

  private strArr(v: unknown, fallback: string[]): string[] {
    return Array.isArray(v) ? v.map((x) => String(x)) : fallback;
  }

  private num(v: unknown, fallback: number): number {
    return typeof v === 'number' && !Number.isNaN(v) ? v : fallback;
  }

  private bool(v: unknown, fallback: boolean): boolean {
    return typeof v === 'boolean' ? v : fallback;
  }

  private maybeNum(v: unknown): number | undefined {
    return typeof v === 'number' && !Number.isNaN(v) ? v : undefined;
  }

  private maybeBool(v: unknown): boolean | undefined {
    return typeof v === 'boolean' ? v : undefined;
  }
}
