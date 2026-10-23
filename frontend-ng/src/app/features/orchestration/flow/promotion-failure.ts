/**
 * Why "Save as System" was refused, in words the author can act on.
 *
 * The server names the rule a draft breaks (`detail.code`, and the step in
 * `detail.path`). Known rules map to a message that says what to do; any
 * other refusal keeps the generic message.
 */
const KNOWN = new Set([
  'skill_not_bound_to_system',
  'skill_contract_missing',
  'skill_contract_mismatch',
  'flow_output_sink_required',
  'flow_output_sink_ambiguous',
  'ingress_unknown',
  'ingress_source_not_root',
  'ingress_node_kind_invalid',
  'ingress_kind_invalid',
  'schema_invalid',
  'schema_too_large',
  'schema_too_deep',
  'schema_remote_ref_forbidden',
  'graph_config_conflict',
  'agent_loop_allowlist_empty',
  'agent_loop_configuration',
  'data_prep_invalid',
  'data_prep_spec_invalid',
  'data_source_invalid',
]);

export interface PromotionFailure {
  /** i18n key of the message. */
  key: string;
  /** Step the server pointed at, when it named one. */
  nodeId: string | null;
}

export function promotionFailure(error: unknown): PromotionFailure {
  const detail = (error as { error?: { detail?: unknown } } | null)?.error?.detail;
  const body = detail && typeof detail === 'object' ? detail as Record<string, unknown> : {};
  const raw = typeof body['code'] === 'string' ? body['code'] : typeof body['error'] === 'string' ? body['error'] : '';
  const code = raw.trim().toLowerCase();
  const path = typeof body['path'] === 'string' ? body['path'] : '';
  const nodeId = path.startsWith('nodes/') ? path.slice('nodes/'.length).split('/')[0] || null : null;
  return { key: KNOWN.has(code) ? `flow.promote.error.code.${code}` : 'flow.promote.error.failed', nodeId };
}
