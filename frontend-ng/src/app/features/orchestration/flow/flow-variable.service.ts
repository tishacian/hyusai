/**
 * Variable-membrane catalog (P2) — the upstream-output source the
 * variable-picker reads.
 *
 * Pure, Angular-free helpers (only `type` imports, erased at build) so the
 * non-trivial graph walk is unit-testable in the lightweight `node:test`
 * harness without DI or a live backend — same pattern as
 * `flow-manifest-strip.vm.ts`.
 *
 * `upstreamOutputs(selectedNodeId, …)` returns the typed output ports of
 * every node that is strictly *upstream* (a graph ancestor) of the selected
 * node. "Upstream" is defined exactly as `validateFlow`'s `variable_unresolved`
 * check (backward reachability over the edge list), so the picker never offers
 * a candidate the design-time checklist would then flag. Candidates are
 * ordered by topological position for a stable, readable list.
 *
 * Each candidate carries the source node id, the output port name, its schema
 * (for the type filter), and a human label. A candidate maps to a typed
 * `VariableRef` of `{ node_id, path: [port] }` when written into `inputs_map`.
 */
import {
  primitivesIncompatible,
  type CanonicalFlowEdge,
  type CanonicalFlowNode,
  type VariableRef,
} from '@app/core/flow-serializer.service';
import { portsFromSchema } from './flow.types';
import { hitlPorts } from '@app/core/flow-hitl-ports';

/** One pickable upstream output port. */
export interface VariableCandidate {
  /** Upstream node id the value is read from. */
  node_id: string;
  /** Output port name on that node (the first `VariableRef.path` segment). */
  port: string;
  /** Compact schema hint, used by the type filter. */
  schema: string;
  /** Human label, e.g. `Retrieve · context`. */
  label: string;
}

/** Separator for the encoded `<node_id>·<port>` select option value. Uses a
 *  control char that cannot appear in a node id or port name. */
const ENCODE_SEP = '\u0001';

/** Sentinel select value that keeps a legacy dot-path string untouched. */
export const LEGACY_VARIABLE_VALUE = '\u0001legacy';

/**
 * Typed output ports of every node strictly upstream of `selectedNodeId`.
 *
 * Upstream = graph ancestors (backward reachable over the edge list), matching
 * `validateFlow`. When a node declares no canonical `outputs`, the optional
 * `outputSchemaFor` enrichment derives ports from the manifest unit's
 * `implementation.output_schema` (via `portsFromSchema`).
 */
export function upstreamOutputs(
  selectedNodeId: string | null | undefined,
  nodes: CanonicalFlowNode[],
  edges: CanonicalFlowEdge[],
  options?: {
    /** Topological order for stable candidate sorting (e.g. `topoSort`). */
    order?: readonly string[] | null;
    /** Fallback output schema for nodes with no declared ports. */
    outputSchemaFor?: (
      nodeId: string,
    ) => Record<string, unknown> | null | undefined;
  },
): VariableCandidate[] {
  if (!selectedNodeId) return [];
  const ids = new Set(nodes.map((n) => n.id));
  if (!ids.has(selectedNodeId)) return [];

  // Reverse adjacency → ancestors (same definition as validateFlow).
  const rev = new Map<string, string[]>();
  nodes.forEach((n) => rev.set(n.id, []));
  for (const e of edges) {
    if (!ids.has(e.from) || !ids.has(e.to)) continue;
    rev.get(e.to)!.push(e.from);
  }
  const ancestors = new Set<string>();
  const stack = [...(rev.get(selectedNodeId) ?? [])];
  while (stack.length > 0) {
    const cur = stack.pop()!;
    if (ancestors.has(cur)) continue;
    ancestors.add(cur);
    stack.push(...(rev.get(cur) ?? []));
  }
  ancestors.delete(selectedNodeId); // never read from self

  // Order upstream nodes by topological position when available.
  const order = options?.order ?? nodes.map((n) => n.id);
  const pos = new Map<string, number>();
  order.forEach((id, i) => pos.set(id, i));
  const byId = new Map(nodes.map((n) => [n.id, n] as const));
  const upstreamIds = [...ancestors].sort(
    (a, b) => (pos.get(a) ?? 0) - (pos.get(b) ?? 0),
  );

  const out: VariableCandidate[] = [];
  for (const id of upstreamIds) {
    const node = byId.get(id);
    if (!node) continue;
    let ports = hitlPorts(node, 'outputs') ?? node.outputs ?? [];
    if (ports.length === 0 && options?.outputSchemaFor) {
      ports = portsFromSchema(options.outputSchemaFor(id));
    }
    for (const p of ports) {
      out.push({
        node_id: id,
        port: p.name,
        schema: p.schema,
        label: `${node.label ?? id} · ${p.name}`,
      });
    }
  }
  return out;
}

/**
 * Keep only candidates whose schema is compatible with `targetSchema`,
 * reusing the SAME primitive-compat rule as `validateFlow`
 * (`number`/`integer` compatible; unknown / `ref:` / cross-primitive
 * skipped). So the picker offers exactly what the checklist would accept.
 */
export function filterCompatibleCandidates(
  candidates: VariableCandidate[],
  targetSchema: string,
): VariableCandidate[] {
  return candidates.filter((c) => !primitivesIncompatible(c.schema, targetSchema));
}

/** Encode a candidate into an opaque `<select>` option value. */
export function encodeCandidateValue(node_id: string, port: string): string {
  return `${node_id}${ENCODE_SEP}${port}`;
}

/** Decode a `<select>` option value back into a `{ node_id, port }` pair. */
export function decodeCandidateValue(
  value: string,
): { node_id: string; port: string } | null {
  const at = value.indexOf(ENCODE_SEP);
  if (at < 0) return null;
  return { node_id: value.slice(0, at), port: value.slice(at + ENCODE_SEP.length) };
}

/** A typed `VariableRef` built from a decoded option value. */
export function variableRefFor(node_id: string, port: string): VariableRef {
  return { node_id, path: [port] };
}

/** Human label for a stored `VariableRef` (used when the ref is not in the
 *  type-filtered candidate list, so it still displays). */
export function variableRefLabel(ref: VariableRef): string {
  const path = ref.path.length > 0 ? ref.path.join('.') : '·';
  return `${ref.node_id} · ${path}`;
}
