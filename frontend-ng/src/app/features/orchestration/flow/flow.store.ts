/**
 * FlowStore — the single source of truth for the Flow Builder.
 *
 * Design tenets (Phase 1 / FOUNDATION):
 *   - **Canvas-agnostic.** The store knows nothing about Foblex (or any
 *     rendering library). It speaks the `CanonicalFlow` pivot model only.
 *     The canvas reads signals and pushes user intents back through the
 *     public methods below; it never reaches into store internals.
 *   - **Serializer is the boundary.** `load(CanonicalFlow)` hydrates the
 *     store, `snapshot()` projects it back out. The CanonicalFlow stays the
 *     contract with the backend (`flow_definition`).
 *   - **History lives here.** Undo/redo is a first-class store concern, not
 *     deferred to a later phase. Structural mutations checkpoint
 *     automatically; the canvas calls `checkpoint()` at drag-start so node
 *     moves are undoable as a single step.
 *
 * This public API is STABLE — later phases (P2 manifest inspector, P3 dynamic
 * palette, P4 persistence/undo-redo UI) build on it without changing it:
 *   - P2 inspector  → `updateNodeData(id, path, value)` / `patchNode`
 *   - P3 palette     → `addNode(partial)`
 *   - P4 persistence → `snapshot()`, `load()`, `markSaved()`, `undo()`,
 *                      `redo()`, `dirty`, `canUndo`, `canRedo`
 */
import { computed, inject } from '@angular/core';
import {
  patchState,
  signalStore,
  withComputed,
  withMethods,
  withState,
} from '@ngrx/signals';
import {
  FlowSerializerService,
  type CanonicalFlow,
  type CanonicalFlowEdge,
  type CanonicalFlowNode,
  type CanonicalPolicy,
  type NodeKind,
} from '@app/core/flow-serializer.service';

/** Non-graph sidecars of a CanonicalFlow, preserved across a round-trip. */
export interface FlowMeta {
  variant?: string;
  source: 'form' | 'flow';
  extended: boolean;
  schema_version: number;
  /** Dropping this on save would silently demote a strict DAG to the
   *  sequential walker (which ignores `inputs_map`), so it must round-trip. */
  io_mode?: 'overlay' | 'strict';
  policy?: CanonicalPolicy;
  collections?: string[];
  rag_mode?: string;
  canonical_rag_mode?: string;
  context_reused?: boolean;
  template_id?: string;
  template_name?: string;
}

/** A point-in-time graph snapshot used by the undo/redo history stacks. */
interface FlowSnapshot {
  nodes: CanonicalFlowNode[];
  edges: CanonicalFlowEdge[];
  selectedNodeId: string | null;
}

interface FlowState {
  nodes: CanonicalFlowNode[];
  edges: CanonicalFlowEdge[];
  selectedNodeId: string | null;
  dirty: boolean;
  meta: FlowMeta;
  past: FlowSnapshot[];
  future: FlowSnapshot[];
}

/** Partial node accepted by `addNode` — id/kind are filled in if absent. */
export type NewFlowNode = Partial<CanonicalFlowNode> & {
  type: CanonicalFlowNode['type'];
};

const HISTORY_LIMIT = 60;

const DEFAULT_META: FlowMeta = {
  source: 'flow',
  extended: false,
  schema_version: 3,
};

const initialState: FlowState = {
  nodes: [],
  edges: [],
  selectedNodeId: null,
  dirty: false,
  meta: { ...DEFAULT_META },
  past: [],
  future: [],
};

function clone<T>(value: T): T {
  return structuredClone(value);
}

/** Stable identity for an edge in the canonical (id-less) edge model. */
export function edgeKey(edge: CanonicalFlowEdge): string {
  return [edge.from, edge.to, edge.from_port ?? '', edge.to_port ?? ''].join('\u0001');
}

function sameEdge(a: CanonicalFlowEdge, b: CanonicalFlowEdge): boolean {
  return edgeKey(a) === edgeKey(b);
}

let nodeSeq = 0;
function freshNodeId(): string {
  nodeSeq += 1;
  return `flow.${Date.now().toString(36)}.${nodeSeq.toString(36)}`;
}

/** Immutable dotted-path set. Returns a new object graph; never mutates. */
function setPath(
  root: Record<string, unknown> | undefined,
  path: string,
  value: unknown,
): Record<string, unknown> {
  const segments = path.split('.').filter((s) => s.length > 0);
  const next: Record<string, unknown> = { ...(root ?? {}) };
  if (segments.length === 0) return next;
  let cursor = next;
  for (let i = 0; i < segments.length - 1; i += 1) {
    const key = segments[i];
    const child = cursor[key];
    cursor[key] =
      child && typeof child === 'object' && !Array.isArray(child)
        ? { ...(child as Record<string, unknown>) }
        : {};
    cursor = cursor[key] as Record<string, unknown>;
  }
  cursor[segments[segments.length - 1]] = value;
  return next;
}

export const FlowStore = signalStore(
  withState<FlowState>(initialState),
  withComputed((store) => ({
    selectedNode: computed<CanonicalFlowNode | null>(() => {
      const id = store.selectedNodeId();
      return id ? store.nodes().find((n) => n.id === id) ?? null : null;
    }),
    nodeCount: computed(() => store.nodes().length),
    edgeCount: computed(() => store.edges().length),
    canUndo: computed(() => store.past().length > 0),
    canRedo: computed(() => store.future().length > 0),
  })),
  withMethods((store) => {
    const serializer = inject(FlowSerializerService);

    const captureSnapshot = (): FlowSnapshot => ({
      nodes: clone(store.nodes()),
      edges: clone(store.edges()),
      selectedNodeId: store.selectedNodeId(),
    });

    /** Push the current graph onto the undo stack and clear the redo stack. */
    const checkpoint = (): void => {
      const past = [...store.past(), captureSnapshot()].slice(-HISTORY_LIMIT);
      patchState(store, { past, future: [] });
    };

    const restore = (snapshot: FlowSnapshot): void => {
      patchState(store, {
        nodes: clone(snapshot.nodes),
        edges: clone(snapshot.edges),
        selectedNodeId: snapshot.selectedNodeId,
        dirty: true,
      });
    };

    return {
      // ---- lifecycle / serializer boundary -------------------------------
      /**
       * Replace the entire graph from a CanonicalFlow. Resets history and the
       * dirty flag (the loaded graph is, by definition, the saved baseline).
       */
      load(flow: CanonicalFlow): void {
        const normalized = serializer.normalize(flow);
        patchState(store, {
          nodes: clone(normalized.nodes),
          edges: clone(normalized.edges),
          selectedNodeId: null,
          dirty: false,
          past: [],
          future: [],
          meta: {
            variant: normalized.variant,
            source: normalized.source ?? 'flow',
            extended: normalized.extended ?? false,
            schema_version: normalized.schema_version ?? 3,
            io_mode: normalized.io_mode,
            policy: normalized.policy,
            collections: normalized.collections,
            rag_mode: normalized.rag_mode,
            canonical_rag_mode: normalized.canonical_rag_mode,
            context_reused: normalized.context_reused,
            template_id: normalized.template_id,
            template_name: normalized.template_name,
          },
        });
      },

      /** Project the live graph back into a CanonicalFlow for persistence. */
      snapshot(): CanonicalFlow {
        const meta = store.meta();
        return {
          variant: meta.variant,
          source: meta.source,
          extended: meta.extended,
          schema_version: meta.schema_version,
          io_mode: meta.io_mode,
          policy: meta.policy,
          collections: meta.collections,
          rag_mode: meta.rag_mode,
          canonical_rag_mode: meta.canonical_rag_mode,
          context_reused: meta.context_reused,
          template_id: meta.template_id,
          template_name: meta.template_name,
          nodes: clone(store.nodes()),
          edges: clone(store.edges()),
        };
      },

      /** Mark the current state as the saved baseline (clears dirty). */
      markSaved(): void {
        patchState(store, { dirty: false });
      },

      setSource(source: 'form' | 'flow'): void {
        patchState(store, { meta: { ...store.meta(), source } });
      },

      // ---- selection -----------------------------------------------------
      setSelection(nodeId: string | null): void {
        if (store.selectedNodeId() === nodeId) return;
        patchState(store, { selectedNodeId: nodeId });
      },

      // ---- structural mutations (auto-checkpointed) ----------------------
      /** Add a node; returns its id. Selects it. */
      addNode(node: NewFlowNode): string {
        checkpoint();
        const id = node.id ?? freshNodeId();
        const created: CanonicalFlowNode = {
          id,
          type: node.type,
          kind: node.kind ?? ('task' as NodeKind),
          label: node.label ?? String(node.type),
          data: node.data ?? {},
          config: node.config ?? {},
          inputs: node.inputs ?? [],
          outputs: node.outputs ?? [],
          position: node.position ?? { x: 120, y: 120 },
        };
        patchState(store, {
          nodes: [...store.nodes(), created],
          selectedNodeId: id,
          dirty: true,
        });
        return id;
      },

      removeNode(nodeId: string): void {
        if (!store.nodes().some((n) => n.id === nodeId)) return;
        checkpoint();
        patchState(store, {
          nodes: store.nodes().filter((n) => n.id !== nodeId),
          edges: store.edges().filter((e) => e.from !== nodeId && e.to !== nodeId),
          selectedNodeId:
            store.selectedNodeId() === nodeId ? null : store.selectedNodeId(),
          dirty: true,
        });
      },

      /** Shallow-patch a node (label, kind, config, position, …). */
      patchNode(nodeId: string, patch: Partial<CanonicalFlowNode>): void {
        const exists = store.nodes().some((n) => n.id === nodeId);
        if (!exists) return;
        checkpoint();
        patchState(store, {
          nodes: store
            .nodes()
            .map((n) => (n.id === nodeId ? { ...n, ...patch } : n)),
          dirty: true,
        });
      },

      /**
       * Write a value into a node's `data` bag at a dotted path. This is the
       * P2 manifest write-back seam — e.g.
       * `updateNodeData(id, 'retrieval_defaults.top_k', 8)`.
       */
      updateNodeData(nodeId: string, path: string, value: unknown): void {
        const exists = store.nodes().some((n) => n.id === nodeId);
        if (!exists) return;
        checkpoint();
        patchState(store, {
          nodes: store.nodes().map((n) =>
            n.id === nodeId
              ? { ...n, data: setPath(n.data, path, value) }
              : n,
          ),
          dirty: true,
        });
      },

      /** Same as `updateNodeData` but targets the `config` bag. */
      updateNodeConfig(nodeId: string, path: string, value: unknown): void {
        const exists = store.nodes().some((n) => n.id === nodeId);
        if (!exists) return;
        checkpoint();
        patchState(store, {
          nodes: store.nodes().map((n) =>
            n.id === nodeId
              ? { ...n, config: setPath(n.config as Record<string, unknown>, path, value) }
              : n,
          ),
          dirty: true,
        });
      },

      /** Add an edge (deduped on from/to/ports). */
      connect(edge: CanonicalFlowEdge): void {
        if (edge.from === edge.to) return;
        if (store.edges().some((e) => sameEdge(e, edge))) return;
        checkpoint();
        patchState(store, {
          edges: [...store.edges(), { kind: 'data', ...edge }],
          dirty: true,
        });
      },

      /** Remove the edge matching from/to/ports. */
      disconnect(edge: CanonicalFlowEdge): void {
        if (!store.edges().some((e) => sameEdge(e, edge))) return;
        checkpoint();
        patchState(store, {
          edges: store.edges().filter((e) => !sameEdge(e, edge)),
          dirty: true,
        });
      },

      /**
       * Re-target an existing edge (Foblex reassign). Removes `previous` and
       * adds `next` as one undoable step.
       */
      reassignEdge(previous: CanonicalFlowEdge, next: CanonicalFlowEdge): void {
        if (next.from === next.to) return;
        checkpoint();
        const withoutPrev = store.edges().filter((e) => !sameEdge(e, previous));
        const exists = withoutPrev.some((e) => sameEdge(e, next));
        patchState(store, {
          edges: exists ? withoutPrev : [...withoutPrev, { kind: 'data', ...next }],
          dirty: true,
        });
      },

      // ---- node movement (history handled via checkpoint at drag-start) --
      /**
       * Update a node's position. Does NOT checkpoint — the canvas calls
       * `checkpoint()` once at drag-start so a whole drag is one undo step.
       */
      moveNode(nodeId: string, position: { x: number; y: number }): void {
        patchState(store, {
          nodes: store
            .nodes()
            .map((n) => (n.id === nodeId ? { ...n, position } : n)),
          dirty: true,
        });
      },

      // ---- history -------------------------------------------------------
      /** Mark an undoable checkpoint (used by the canvas at drag-start). */
      checkpoint,

      undo(): void {
        const past = store.past();
        if (past.length === 0) return;
        const previous = past[past.length - 1];
        const future = [captureSnapshot(), ...store.future()].slice(0, HISTORY_LIMIT);
        patchState(store, { past: past.slice(0, -1), future });
        restore(previous);
      },

      redo(): void {
        const future = store.future();
        if (future.length === 0) return;
        const nextSnapshot = future[0];
        const past = [...store.past(), captureSnapshot()].slice(-HISTORY_LIMIT);
        patchState(store, { future: future.slice(1), past });
        restore(nextSnapshot);
      },

      /**
       * Apply a batch of positions (e.g. an auto-layout result) as a single
       * undoable step.
       */
      setPositions(positions: Record<string, { x: number; y: number }>): void {
        checkpoint();
        patchState(store, {
          nodes: store.nodes().map((n) =>
            positions[n.id] ? { ...n, position: positions[n.id] } : n,
          ),
          dirty: true,
        });
      },

      // ---- bulk -----------------------------------------------------------
      clear(): void {
        checkpoint();
        patchState(store, {
          nodes: [],
          edges: [],
          selectedNodeId: null,
          dirty: true,
        });
      },
    };
  }),
);
