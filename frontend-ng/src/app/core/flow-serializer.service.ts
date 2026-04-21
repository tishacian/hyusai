import { Injectable } from '@angular/core';

/**
 * Flow serialization — the contract between `/systems/new` (Form) and
 * `/orchestration` (Drawflow / Flow).
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
 *     the flow carries **extra** nodes (user-authored in Drawflow), it
 *     returns `extended: true` so the builder can lock the affected
 *     sections with an "Edited in Flow" badge — we never silently drop
 *     operator intent.
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

export interface CanonicalFlowNode {
  id: string;
  type: CanonicalNodeType | string;
  label?: string;
  /**
   * Section payload for builder-originated nodes. Free-form bag indexed
   * by the caller; the serializer only cares about the canonical keys.
   */
  data?: Record<string, unknown>;
  /** Pixel position — only meaningful for Drawflow. */
  position?: { x: number; y: number };
}

export interface CanonicalFlowEdge {
  from: string;
  to: string;
  label?: string;
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

/** Minimal Drawflow JSON shape (we only read/write the parts we use). */
export interface DrawflowNode {
  id: number;
  name: string;
  data: Record<string, unknown>;
  class?: string;
  html?: string;
  typenode?: boolean;
  inputs: Record<string, { connections: { node: string; input: string }[] }>;
  outputs: Record<string, { connections: { node: string; output: string }[] }>;
  pos_x: number;
  pos_y: number;
}

export interface DrawflowGraph {
  drawflow: {
    Home: {
      data: Record<string, DrawflowNode>;
    };
  };
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
        label: draft.name || 'Objective',
        data: { name: draft.name, objective: draft.objective },
        position: { x: 60, y: 80 },
      },
      {
        id: 'builder.capability',
        type: 'capability',
        label: 'Capability',
        data: { capability_id: draft.capability_id },
        position: { x: 320, y: 80 },
      },
      {
        id: 'builder.skills',
        type: 'skill',
        label: 'Bundled skills',
        data: {},
        position: { x: 580, y: 80 },
      },
      {
        id: 'builder.context',
        type: 'context',
        label: 'Context',
        data: {
          collections: draft.collections,
          reuse_context_id: draft.reuse_context_id,
          rag_mode: draft.rag_mode,
        },
        position: { x: 840, y: 80 },
      },
      {
        id: 'builder.policy',
        type: 'policy',
        label: 'Policy',
        data: {
          execution_mode: draft.execution_mode,
          default_prompt_type: draft.default_prompt_type,
          default_model: draft.default_model,
          policy: this.policyFromDraft(draft),
        },
        position: { x: 1100, y: 80 },
      },
      {
        id: 'builder.launch',
        type: 'launch',
        label: 'Launch',
        data: {},
        position: { x: 1360, y: 80 },
      },
    ];

    const edges: CanonicalFlowEdge[] = [];
    for (let i = 0; i < nodes.length - 1; i += 1) {
      edges.push({ from: nodes[i].id, to: nodes[i + 1].id });
    }

    return {
      source: 'form',
      extended: false,
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
   * Materialize a canonical flow into a Drawflow graph that can be
   * `drawflow.import()`-ed directly. Canonical node ids are re-numbered
   * into integer keys as Drawflow expects, with a lookup preserved on
   * each node's `data.canonical_id` so the reverse projection is
   * deterministic.
   */
  materialize(flow: CanonicalFlow): DrawflowGraph {
    const data: Record<string, DrawflowNode> = {};
    const idToNum = new Map<string, number>();
    flow.nodes.forEach((n, idx) => {
      const num = idx + 1;
      idToNum.set(n.id, num);
      data[String(num)] = {
        id: num,
        name: String(n.type),
        class: `flow-node flow-node-${n.type}`,
        html: this.nodeHtml(n),
        typenode: false,
        data: { ...(n.data ?? {}), canonical_id: n.id, canonical_type: n.type },
        inputs: { input_1: { connections: [] } },
        outputs: { output_1: { connections: [] } },
        pos_x: n.position?.x ?? 60 + idx * 260,
        pos_y: n.position?.y ?? 80,
      };
    });

    for (const edge of flow.edges) {
      const fromNum = idToNum.get(edge.from);
      const toNum = idToNum.get(edge.to);
      if (!fromNum || !toNum) continue;
      const fromNode = data[String(fromNum)];
      const toNode = data[String(toNum)];
      fromNode.outputs['output_1'].connections.push({
        node: String(toNum),
        output: 'input_1',
      });
      toNode.inputs['input_1'].connections.push({
        node: String(fromNum),
        input: 'output_1',
      });
    }

    return { drawflow: { Home: { data } } };
  }

  /**
   * Read a Drawflow graph back into a canonical flow, preserving
   * `canonical_id` markers we wrote at materialize time. Nodes that
   * were added in Drawflow without a canonical id keep their
   * drawflow-generated id and are flagged as `custom`.
   */
  project(graph: DrawflowGraph): CanonicalFlow {
    const raw = graph?.drawflow?.Home?.data ?? {};
    const numToCanonical = new Map<string, string>();
    const nodes: CanonicalFlowNode[] = [];
    let hasExtra = false;

    for (const [key, node] of Object.entries(raw)) {
      const canonicalId = (node.data?.['canonical_id'] as string) || `flow.${key}`;
      const type =
        (node.data?.['canonical_type'] as string) || node.name || 'custom';
      if (!CANONICAL_ID_SET.has(canonicalId) && type !== 'source' && type !== 'sink') {
        hasExtra = true;
      }
      numToCanonical.set(key, canonicalId);
      const { canonical_id: _ci, canonical_type: _ct, ...rest } = node.data ?? {};
      nodes.push({
        id: canonicalId,
        type,
        label: this.extractLabel(node),
        data: rest,
        position: { x: node.pos_x, y: node.pos_y },
      });
    }

    const edges: CanonicalFlowEdge[] = [];
    for (const [key, node] of Object.entries(raw)) {
      const fromId = numToCanonical.get(key);
      if (!fromId) continue;
      for (const out of Object.values(node.outputs ?? {})) {
        for (const conn of out.connections ?? []) {
          const toId = numToCanonical.get(conn.node);
          if (toId) edges.push({ from: fromId, to: toId });
        }
      }
    }

    return {
      source: 'flow',
      extended: hasExtra,
      nodes,
      edges,
    };
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

  private nodeHtml(n: CanonicalFlowNode): string {
    const label = n.label ?? String(n.type);
    return `<div class="fn-title">${this.escape(label)}</div>`;
  }

  private extractLabel(node: DrawflowNode): string {
    const raw = node.html ?? '';
    const match = raw.match(/>(.*?)</);
    return match?.[1] ?? node.name ?? '';
  }

  private escape(s: string): string {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
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
