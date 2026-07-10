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
 *
 * Backward-compat: `inputs_map` still accepts a legacy dot-path string
 * (e.g. `"session.objective"`); v2 flows keep those untouched. The
 * typed `VariableRef` form is the v3 enrichment — both shapes coexist.
 */
export interface VariableRef {
  node_id: string;
  path: string[];
}

/** Reserved variable namespaces that resolve outside the node graph. */
export const RESERVED_VARIABLE_NAMESPACES: readonly string[] = [
  'workspace',
  'system',
  'run',
  'node',
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
}

/** Validation diagnostic for a flow graph. */
export interface FlowValidationIssue {
  level: 'error' | 'warn';
  node_id?: string;
  edge_index?: number;
  code:
    | 'dangling_edge'
    | 'join_without_fork'
    | 'fork_without_join'
    | 'decision_no_branches'
    | 'task_no_skill'
    | 'cycle_detected'
    | 'unreachable_node'
    | 'port_type_mismatch'
    // v3: a ``config.inputs_map`` VariableRef points at a node_id/port
    // that is not a reserved namespace and not present upstream. Warn
    // level — design-time hint, never blocks a save.
    | 'variable_unresolved'
    | 'hitl_no_prompt'
    | 'loop_no_budget'
    | 'retry_no_target'
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

    const nodes = flow.nodes.map((n) => {
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

    let forkCount = 0;
    let joinCount = 0;

    for (const n of flow.nodes) {
      const kind = n.kind ?? 'task';
      const cfg = (n.config ?? {}) as Record<string, unknown>;
      if (kind === 'fork') forkCount += 1;
      if (kind === 'join') joinCount += 1;

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
        const branches = cfg['branches'];
        if (!Array.isArray(branches) || branches.length < 2) {
          issues.push({
            level: 'error',
            node_id: n.id,
            code: 'decision_no_branches',
            message: `Decision "${n.label ?? n.id}" needs at least two branches.`,
          });
        }
      }
      if (kind === 'loop') {
        const budget = cfg['max_iterations'];
        if (typeof budget !== 'number' || budget <= 0) {
          issues.push({
            level: 'error',
            node_id: n.id,
            code: 'loop_no_budget',
            message: `Loop "${n.label ?? n.id}" is missing a positive max_iterations budget.`,
          });
        }
      }
      if (kind === 'retry') {
        const attempts = cfg['max_attempts'];
        if (typeof attempts !== 'number' || attempts <= 0) {
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
            message: `HITL "${n.label ?? n.id}" should include an approver prompt.`,
          });
        }
      }
    }

    if (joinCount > 0 && forkCount === 0) {
      issues.push({
        level: 'warn',
        code: 'join_without_fork',
        message: 'Flow has join node(s) but no fork — join will degenerate to passthrough.',
      });
    }
    if (forkCount > 0 && joinCount === 0) {
      issues.push({
        level: 'warn',
        code: 'fork_without_join',
        message: 'Flow has fork node(s) but no join — branches may race to the sink.',
      });
    }

    if (this.hasCycle(adj)) {
      issues.push({
        level: 'error',
        code: 'cycle_detected',
        message: 'Flow contains a cycle outside a loop node. Use a loop kind for controlled iteration.',
      });
    }

    // v3 — data-membrane diagnostics (both warn level; never block a
    // save). Kept in lockstep with the backend ``dag_validator``.
    const byId = new Map(flow.nodes.map((n) => [n.id, n] as const));

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
    // node_id/port not present upstream. Legacy dot-path strings are
    // skipped (they are resolved by the run engine, not the graph).
    for (const n of flow.nodes) {
      const inputsMap = (n.config as Record<string, unknown> | undefined)?.['inputs_map'];
      if (!inputsMap || typeof inputsMap !== 'object') continue;
      let ancestors: Set<string> | null = null;
      for (const [port, raw] of Object.entries(inputsMap as Record<string, unknown>)) {
        if (!this.isVariableRef(raw)) continue;
        const ref = raw as VariableRef;
        if (RESERVED_VARIABLE_NAMESPACES.includes(ref.node_id)) continue;
        if (!ids.has(ref.node_id)) {
          issues.push({
            level: 'warn',
            node_id: n.id,
            code: 'variable_unresolved',
            message: `Input "${port}" references unknown node "${ref.node_id}".`,
          });
          continue;
        }
        if (ancestors === null) ancestors = this.ancestorsOf(n.id, rev);
        if (!ancestors.has(ref.node_id)) {
          issues.push({
            level: 'warn',
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
            level: 'warn',
            node_id: n.id,
            code: 'variable_unresolved',
            message: `Input "${port}" reads port "${head}" not declared on "${ref.node_id}".`,
          });
        }
      }
    }

    return issues;
  }

  /** A value is a typed VariableRef (v3) iff it carries a string
   *  `node_id` and an array `path`; anything else (incl. legacy dot-path
   *  strings) is treated as opaque and skipped by validation. */
  private isVariableRef(value: unknown): value is VariableRef {
    return (
      !!value &&
      typeof value === 'object' &&
      typeof (value as { node_id?: unknown }).node_id === 'string' &&
      Array.isArray((value as { path?: unknown }).path)
    );
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
