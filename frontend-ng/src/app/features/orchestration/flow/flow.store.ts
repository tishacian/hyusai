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
  type DecisionNodeConfig,
  type NodeKind,
  type NodePort,
} from '@app/core/flow-serializer.service';

/** Non-graph sidecars of a CanonicalFlow, preserved across a round-trip. */
export interface FlowMeta {
  /** Forward-compatible top-level sidecars are kept verbatim here. Graph keys
   *  are deliberately excluded by `metaFromFlow` and projected from the live
   *  store instead. */
  [key: string]: unknown;
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
  variable_namespaces?: string[];
}

/** A point-in-time graph snapshot used by the undo/redo history stacks. */
interface FlowSnapshot {
  nodes: CanonicalFlowNode[];
  edges: CanonicalFlowEdge[];
  selectedNodeId: string | null;
  meta: FlowMeta;
}

interface FlowState {
  nodes: CanonicalFlowNode[];
  edges: CanonicalFlowEdge[];
  selectedNodeId: string | null;
  dirty: boolean;
  /** Monotone token for every persistable state replacement or mutation. */
  revision: number;
  meta: FlowMeta;
  past: FlowSnapshot[];
  future: FlowSnapshot[];
}

/** Partial node accepted by `addNode` — id/kind are filled in if absent. */
export type NewFlowNode = Partial<CanonicalFlowNode> & {
  type: CanonicalFlowNode['type'];
};

/** One atomic inspector intent for a Decision node. Config, route handles,
 * branch edges and default selection are mutated in a single undo frame. */
export type DecisionMutation =
  | { type: 'add'; branch?: Partial<DecisionNodeConfig['branches'][number]> }
  | { type: 'update'; index: number; patch: Partial<DecisionNodeConfig['branches'][number]> }
  | { type: 'remove'; index: number }
  | { type: 'move'; index: number; direction: -1 | 1 }
  | { type: 'set_default'; label?: string };

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
  revision: 0,
  meta: { ...DEFAULT_META },
  past: [],
  future: [],
};

function clone<T>(value: T): T {
  return structuredClone(value);
}

/** Keep every canonical/forward-compatible top-level sidecar while ensuring
 * graph state has a single owner (`nodes` / `edges` signals). */
function metaFromFlow(flow: CanonicalFlow): FlowMeta {
  const record = flow as CanonicalFlow & Record<string, unknown>;
  const { nodes: _nodes, edges: _edges, ...sidecars } = record;
  return {
    ...clone(sidecars),
    source: flow.source ?? 'flow',
    extended: flow.extended ?? false,
    schema_version: flow.schema_version ?? 3,
  } as FlowMeta;
}

/** Stable identity for an edge in the canonical (id-less) edge model. */
export function edgeKey(edge: CanonicalFlowEdge): string {
  const branchLabel = (edge.kind ?? 'data') === 'branch'
    ? edge.branch_label ?? edge.label ?? ''
    : '';
  return [
    edge.kind ?? 'data',
    edge.from,
    edge.to,
    branchLabel,
    edge.from_port ?? '',
    edge.to_port ?? '',
  ].join('\u0001');
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

function decisionBranches(node: CanonicalFlowNode): DecisionNodeConfig['branches'] {
  const raw = (node.config as Record<string, unknown> | undefined)?.['branches'];
  if (!Array.isArray(raw)) return [];
  return raw.map((branch) => {
    const record = branch && typeof branch === 'object' && !Array.isArray(branch)
      ? branch as Record<string, unknown>
      : {};
    return {
      label: typeof record['label'] === 'string' ? record['label'] : '',
      condition: typeof record['condition'] === 'string' ? record['condition'] : '',
    };
  });
}

/** Route outputs must have unique non-empty connector ids even while an
 * invalid draft (duplicate/blank label) is being edited. The config retains
 * the invalid value so validation still blocks Save; the canvas stays sound. */
function decisionOutputs(
  branches: DecisionNodeConfig['branches'],
  previous: NodePort[] | undefined,
): NodePort[] {
  const previousByName = new Map((previous ?? []).map((port) => [port.name, port]));
  const seen = new Set<string>();
  const outputs: NodePort[] = [];
  for (const branch of branches) {
    if (!branch.label || seen.has(branch.label)) continue;
    seen.add(branch.label);
    outputs.push(previousByName.get(branch.label) ?? {
      name: branch.label,
      schema: 'object',
    });
  }
  return outputs;
}

function renameDecisionOutput(
  outputs: NodePort[] | undefined,
  rename: { from: string; to: string } | undefined,
): NodePort[] | undefined {
  if (!rename) return outputs;
  return (outputs ?? []).map((port) => port.name === rename.from
    ? { ...port, name: rename.to }
    : port);
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
      meta: clone(store.meta()),
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
        meta: clone(snapshot.meta),
        dirty: true,
        revision: store.revision() + 1,
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
          revision: store.revision() + 1,
          past: [],
          future: [],
          meta: metaFromFlow(normalized),
        });
      },

      /** Replace the graph as a user edit (e.g. JSON import). Unlike `load`,
       *  this preserves one undo checkpoint and remains dirty until persisted. */
      replaceAsEdit(flow: CanonicalFlow): void {
        const normalized = serializer.normalize(flow);
        checkpoint();
        patchState(store, {
          nodes: clone(normalized.nodes),
          edges: clone(normalized.edges),
          selectedNodeId: null,
          dirty: true,
          revision: store.revision() + 1,
          meta: metaFromFlow(normalized),
        });
      },

      /** Project the live graph back into a CanonicalFlow for persistence. */
      snapshot(): CanonicalFlow {
        const meta = clone(store.meta());
        return {
          ...meta,
          nodes: clone(store.nodes()),
          edges: clone(store.edges()),
        } as CanonicalFlow;
      },

      /** Mark the current revision as saved. A stale async response cannot
       *  clean a newer edit when its expected revision no longer matches. */
      markSaved(expectedRevision?: number): boolean {
        if (expectedRevision !== undefined && expectedRevision !== store.revision()) {
          return false;
        }
        patchState(store, { dirty: false });
        return true;
      },

      setSource(source: 'form' | 'flow'): void {
        if (store.meta().source === source) return;
        patchState(store, {
          meta: { ...store.meta(), source },
          dirty: true,
          revision: store.revision() + 1,
        });
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
          revision: store.revision() + 1,
        });
        return id;
      },

      /** Remove a node and every incident edge in one undo frame.
       *
       * This is deliberately fail-closed: deleting a Skill, Governance guard
       * or ordinary task must never create a new executable route implicitly.
       * An operator can reconnect the remaining nodes as a separate, visible
       * and independently undoable authoring intent. */
      removeNode(nodeId: string): void {
        if (!store.nodes().some((node) => node.id === nodeId)) return;
        checkpoint();
        patchState(store, {
          nodes: store.nodes().filter((node) => node.id !== nodeId),
          edges: store.edges().filter(
            (edge) => edge.from !== nodeId && edge.to !== nodeId,
          ),
          selectedNodeId:
            store.selectedNodeId() === nodeId ? null : store.selectedNodeId(),
          dirty: true,
          revision: store.revision() + 1,
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
          revision: store.revision() + 1,
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
          revision: store.revision() + 1,
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
          revision: store.revision() + 1,
        });
      },

      /** Apply a complete Decision editor operation atomically. A rename
       * updates its route edge labels + ports and default in the same store
       * revision; a removal drops its routes in that same undoable step. */
      mutateDecision(nodeId: string, mutation: DecisionMutation): void {
        const node = store.nodes().find((candidate) => candidate.id === nodeId);
        if (!node || (node.kind ?? 'task') !== 'decision') return;

        const branches = decisionBranches(node);
        let nextBranches = branches.map((branch) => ({ ...branch }));
        const rawConfig = {
          ...((node.config as Record<string, unknown> | undefined) ?? {}),
        };
        let defaultBranch = typeof rawConfig['default_branch'] === 'string'
          ? rawConfig['default_branch']
          : undefined;
        let nextEdges = store.edges();
        let renamedPort: { from: string; to: string } | undefined;

        if (mutation.type === 'add') {
          const used = new Set(nextBranches.map((branch) => branch.label));
          let sequence = nextBranches.length + 1;
          let label = mutation.branch?.label ?? `branch_${sequence}`;
          while (used.has(label)) {
            sequence += 1;
            label = `branch_${sequence}`;
          }
          nextBranches.push({
            label,
            condition: mutation.branch?.condition ?? 'False',
          });
        } else if (mutation.type === 'update') {
          if (mutation.index < 0 || mutation.index >= nextBranches.length) return;
          const previousLabel = nextBranches[mutation.index].label;
          nextBranches[mutation.index] = {
            ...nextBranches[mutation.index],
            ...mutation.patch,
          };
          const nextLabel = nextBranches[mutation.index].label;
          const previousLabelStillOwned = nextBranches.some(
            (branch, index) => index !== mutation.index && branch.label === previousLabel,
          );
          if (nextLabel !== previousLabel && !previousLabelStillOwned) {
            renamedPort = { from: previousLabel, to: nextLabel };
            nextEdges = nextEdges.map((edge) => {
              if (
                edge.from !== nodeId ||
                (edge.kind ?? 'data') !== 'branch' ||
                (edge.branch_label ?? edge.label) !== previousLabel
              ) return edge;
              return {
                ...edge,
                branch_label: nextLabel,
                ...(edge.from_port === previousLabel ? { from_port: nextLabel } : {}),
                ...(edge.label === previousLabel ? { label: nextLabel } : {}),
              };
            });
            if (defaultBranch === previousLabel) defaultBranch = nextLabel;
          }
        } else if (mutation.type === 'remove') {
          if (
            nextBranches.length <= 2 ||
            mutation.index < 0 ||
            mutation.index >= nextBranches.length
          ) return;
          const [removed] = nextBranches.splice(mutation.index, 1);
          const labelStillOwned = nextBranches.some((branch) => branch.label === removed.label);
          if (!labelStillOwned) {
            nextEdges = nextEdges.filter((edge) => !(
              edge.from === nodeId &&
              (edge.kind ?? 'data') === 'branch' &&
              (edge.branch_label ?? edge.label) === removed.label
            ));
            if (defaultBranch === removed.label) defaultBranch = undefined;
          }
        } else if (mutation.type === 'move') {
          const target = mutation.index + mutation.direction;
          if (
            mutation.index < 0 ||
            mutation.index >= nextBranches.length ||
            target < 0 ||
            target >= nextBranches.length
          ) return;
          const [moved] = nextBranches.splice(mutation.index, 1);
          nextBranches.splice(target, 0, moved);
        } else {
          defaultBranch = mutation.label || undefined;
        }

        const nextConfig: Record<string, unknown> = {
          ...rawConfig,
          branches: nextBranches,
        };
        if (defaultBranch === undefined) delete nextConfig['default_branch'];
        else nextConfig['default_branch'] = defaultBranch;

        checkpoint();
        patchState(store, {
          nodes: store.nodes().map((candidate) => candidate.id === nodeId
            ? {
              ...candidate,
              config: nextConfig,
              outputs: decisionOutputs(
                nextBranches,
                renameDecisionOutput(candidate.outputs, renamedPort),
              ),
            }
            : candidate),
          edges: nextEdges,
          dirty: true,
          revision: store.revision() + 1,
        });
      },

      /** Add an edge (deduped on semantics, endpoints, branch and ports). */
      connect(edge: CanonicalFlowEdge): void {
        if (edge.from === edge.to) return;
        if (store.edges().some((e) => sameEdge(e, edge))) return;
        checkpoint();
        patchState(store, {
          edges: [...store.edges(), { kind: 'data', ...edge }],
          dirty: true,
          revision: store.revision() + 1,
        });
      },

      /** Remove the edge matching semantics, endpoints, branch and ports. */
      disconnect(edge: CanonicalFlowEdge): void {
        if (!store.edges().some((e) => sameEdge(e, edge))) return;
        checkpoint();
        patchState(store, {
          edges: store.edges().filter((e) => !sameEdge(e, edge)),
          dirty: true,
          revision: store.revision() + 1,
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
          revision: store.revision() + 1,
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
          revision: store.revision() + 1,
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
          revision: store.revision() + 1,
        });
      },

      // ---- bulk -----------------------------------------------------------
      clear(): void {
        if (store.nodes().length === 0 && store.edges().length === 0) return;
        checkpoint();
        patchState(store, {
          nodes: [],
          edges: [],
          selectedNodeId: null,
          dirty: true,
          revision: store.revision() + 1,
        });
      },
    };
  }),
);
