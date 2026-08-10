/**
 * Truthful projection of a System's persisted graph, and the discriminator
 * that decides whether the System view may describe it as one.
 *
 * A System can be backed by three very different things: the RAG pipeline
 * projected from the System Builder form, the always-on workspace chat
 * manifest, or a real DAG authored in the Flow Builder and walked by the run
 * engine. Only the third one may be rendered as a graph. Discrimination is
 * therefore positive-evidence only: without a proof of run-engine authorship
 * the caller keeps whatever it rendered before.
 */
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import { derivedIngressKind } from '@app/features/orchestration/flow/flow-contract-bindings.vm';

/** Persisted marker of the always-on workspace chat System (backend
 *  `bootstrap.WORKSPACE_CHAT_VARIANT`). Its nodes document code, they are
 *  never executed. */
const CHAT_FLOW_VARIANT = 'chat_transverse_v1';

/** Variants that already own a bespoke rendering in the System view. */
const SPECIALISED_VARIANTS = new Set([
  'intelligence',
  'expert_knowledge_capture',
  'translation_suite',
]);

const INGRESS_KINDS = new Set(['manual', 'chat', 'http', 'schedule', 'event']);

const INGRESS_LABELS: Record<string, string> = {
  manual: 'Manual',
  chat: 'Chat',
  http: 'HTTP',
  schedule: 'Schedule',
  event: 'Event',
};

/** Structural read model — the transport carries more than `System` declares. */
export interface SystemFlowSource {
  id?: string;
  flow_definition?: Record<string, unknown> | null;
  settings?: Record<string, unknown> | null;
  published_flow_version_id?: string | null;
  published_at?: string | null;
  published_by?: string | null;
}

/** Server-derived runtime sidecar (`GET /systems/{id}/flow-manifest`). */
export interface SystemFlowManifestEvidence {
  system_id?: string;
  runtime_surface?: string | null;
  runtime_mode?: string | null;
  unit_catalog?: Array<{
    id?: string;
    skill_slug?: string | null;
    runtime_status?: string | null;
    operational?: boolean;
  }> | null;
}

export interface FlowTriggerSummary {
  nodeId: string;
  kind: string;
  label: string;
}

export interface FlowStepSummary {
  nodeId: string;
  label: string;
  kind: string;
  skillSlug: string | null;
  runtimeStatus: string | null;
  operational: boolean;
}

export interface SystemFlowProfile {
  nodeCount: number;
  edgeCount: number;
  steps: FlowStepSummary[];
  triggers: FlowTriggerSummary[];
  skillSlugs: string[];
  runtimeMode: string | null;
  publishedVersionId: string | null;
  publishedAt: string | null;
  publishedBy: string | null;
  promotedFromScratchpad: boolean;
}

/**
 * True only when the System demonstrably carries a run-engine graph.
 *
 * Every branch below is a veto or a proof; an unknown, empty or ambiguous
 * `flow_definition` returns `false` so the historical rendering survives.
 */
export function isFlowBackedSystem(
  system: SystemFlowSource | null | undefined,
  manifest?: SystemFlowManifestEvidence | null,
): boolean {
  if (!system) return false;
  const flow = asRecord(system.flow_definition);
  if (!flow) return false;

  const nodes = flowNodes(flow);
  if (nodes.length === 0) return false;

  const variant = readString(flow['variant'])?.toLowerCase() ?? '';
  if (variant === CHAT_FLOW_VARIANT || SPECIALISED_VARIANTS.has(variant)) return false;

  const settings = asRecord(system.settings) ?? {};
  if (readString(settings['system_type']) === 'workspace_chat') return false;

  // `form` is the System Builder projection of a RAG pipeline, not a graph.
  const source = readString(flow['source']);
  if (source === 'form') return false;
  if (source !== 'flow' && !nodes.some(ingressKind)) return false;

  // The server owns the last word on which runtime reads this flow. It only
  // ever narrows the verdict: an absent manifest changes nothing.
  if (
    manifest &&
    (!manifest.system_id || !system.id || manifest.system_id === system.id) &&
    manifest.runtime_surface === 'chat_runtime'
  ) {
    return false;
  }
  return true;
}

/** The graph description, or `null` when the System is not flow-backed. */
export function systemFlowProfile(
  system: SystemFlowSource | null | undefined,
  manifest?: SystemFlowManifestEvidence | null,
): SystemFlowProfile | null {
  if (!isFlowBackedSystem(system, manifest)) return null;

  const flow = asRecord(system!.flow_definition) ?? {};
  const nodes = flowNodes(flow);
  const units = manifestUnits(system!.id, manifest);

  const steps: FlowStepSummary[] = nodes.map((node, index) => {
    const nodeId = readString(node['id']) ?? `node-${index + 1}`;
    const unit = units.get(nodeId);
    const skillSlug = readString(asRecord(node['config'])?.['skill_slug'])
      ?? readString(asRecord(node['data'])?.['skill_slug'])
      ?? readString(unit?.skill_slug)
      ?? null;
    return {
      nodeId,
      label: readString(node['label']) ?? nodeId,
      kind: readString(node['kind']) ?? readString(node['type']) ?? 'task',
      skillSlug,
      runtimeStatus: readString(unit?.runtime_status) ?? null,
      operational: unit?.operational === true,
    };
  });

  const triggers: FlowTriggerSummary[] = [];
  for (const [index, node] of nodes.entries()) {
    const kind = ingressKind(node);
    if (!kind) continue;
    const nodeId = readString(node['id']) ?? `node-${index + 1}`;
    triggers.push({
      nodeId,
      kind,
      label: readString(node['label']) ?? INGRESS_LABELS[kind] ?? kind,
    });
  }

  return {
    nodeCount: nodes.length,
    edgeCount: asArray(flow['edges']).filter((edge) => !!asRecord(edge)).length,
    steps,
    triggers,
    skillSlugs: [...new Set(steps.map((step) => step.skillSlug).filter(isNonEmpty))],
    runtimeMode: readString(manifest?.runtime_mode) ?? null,
    publishedVersionId: readString(system!.published_flow_version_id) ?? null,
    publishedAt: readString(system!.published_at) ?? null,
    publishedBy: readString(system!.published_by) ?? null,
    promotedFromScratchpad: isPromotedFromScratchpad(system),
  };
}

/** Provenance marker written by the scratchpad promotion path. */
export function isPromotedFromScratchpad(
  system: SystemFlowSource | null | undefined,
): boolean {
  return readString(asRecord(system?.settings)?.['origin']) === 'scratchpad_promote';
}

/** Card badge that never claims a pipeline the System does not run. */
export function systemCatalogBadge(
  system: SystemFlowSource | null | undefined,
  ragMode?: string | null,
): string {
  if (isFlowBackedSystem(system)) return 'Flow';
  const flow = asRecord(system?.flow_definition) ?? {};
  const settings = asRecord(system?.settings) ?? {};
  if (
    readString(flow['variant'])?.toLowerCase() === CHAT_FLOW_VARIANT ||
    readString(settings['system_type']) === 'workspace_chat'
  ) {
    return 'Chat';
  }
  return ragMode?.trim() || 'OmniRAG';
}

/**
 * The entry kind publication will actually register for this node: the
 * declared `config.ingress_kind` when present, otherwise the one derived from
 * the node type. Deriving is delegated to the spec-locked mirror of
 * `flow_contracts._ingress_kind` so this view cannot advertise a trigger the
 * backend would not publish.
 */
function ingressKind(node: Record<string, unknown>): string | null {
  if (readString(node['kind']) !== 'source') return null;
  const declared = readString(asRecord(node['config'])?.['ingress_kind']);
  if (declared) return INGRESS_KINDS.has(declared) ? declared : null;
  return derivedIngressKind(node as unknown as CanonicalFlowNode);
}

function flowNodes(flow: Record<string, unknown>): Record<string, unknown>[] {
  return asArray(flow['nodes'])
    .map((node) => asRecord(node))
    .filter((node): node is Record<string, unknown> => !!node && isNonEmpty(node['id']));
}

function manifestUnits(
  systemId: string | undefined,
  manifest: SystemFlowManifestEvidence | null | undefined,
): Map<string, NonNullable<SystemFlowManifestEvidence['unit_catalog']>[number]> {
  const units = new Map<
    string,
    NonNullable<SystemFlowManifestEvidence['unit_catalog']>[number]
  >();
  if (!manifest) return units;
  if (systemId && manifest.system_id && manifest.system_id !== systemId) return units;
  for (const unit of manifest.unit_catalog ?? []) {
    const id = readString(unit?.id);
    if (id) units.set(id, unit);
  }
  return units;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function readString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function isNonEmpty(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}
