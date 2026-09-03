/** Contract for `GET/PUT /workspaces/{slug}/chat-execution`. */

export const CHAT_EXECUTION_MODES = ['classic', 'hybrid', 'agentic_default'] as const;
export type ChatExecutionMode = (typeof CHAT_EXECUTION_MODES)[number];

export interface ChatExecutionState {
  workspace_id: string;
  workspace_slug: string;
  mode: ChatExecutionMode;
  percentage: number;
  fallback: string;
  salt: string;
  policy_version: number;
  managed_by: string;
  agentic_kill_switch_enabled: boolean;
  target_system_id: string | null;
  target_system_name: string | null;
  control_policy_id: string | null;
  flow_revision: string | null;
  contract_valid: boolean;
  collection_slug: string | null;
  collection_status: string | null;
  collection_chunk_count: number | null;
  invariants: string[];
  rollout_ready: boolean;
  modes: ChatExecutionMode[];
  changed: boolean;
  audit_event_id: string | null;
}

export function isChatExecutionMode(value: unknown): value is ChatExecutionMode {
  return typeof value === 'string' && (CHAT_EXECUTION_MODES as readonly string[]).includes(value);
}

export function clampChatExecutionPercentage(value: unknown): number {
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, Math.round(n)));
}

export function parseChatExecution(raw: unknown): ChatExecutionState {
  const data = raw && typeof raw === 'object' && !Array.isArray(raw)
    ? (raw as Record<string, unknown>)
    : {};
  const invariants = Array.isArray(data['invariants'])
    ? data['invariants'].map((item) => String(item)).filter(Boolean)
    : [];
  const modes = Array.isArray(data['modes'])
    ? data['modes'].filter(isChatExecutionMode)
    : [...CHAT_EXECUTION_MODES];
  return {
    workspace_id: String(data['workspace_id'] || ''),
    workspace_slug: String(data['workspace_slug'] || ''),
    mode: isChatExecutionMode(data['mode']) ? data['mode'] : 'hybrid',
    percentage: clampChatExecutionPercentage(data['percentage']),
    fallback: String(data['fallback'] || 'classic'),
    salt: String(data['salt'] || ''),
    policy_version: Number(data['policy_version'] || 0) || 0,
    managed_by: String(data['managed_by'] || 'workspace'),
    agentic_kill_switch_enabled: data['agentic_kill_switch_enabled'] === true,
    target_system_id: data['target_system_id'] ? String(data['target_system_id']) : null,
    target_system_name: data['target_system_name'] ? String(data['target_system_name']) : null,
    control_policy_id: data['control_policy_id'] ? String(data['control_policy_id']) : null,
    flow_revision: data['flow_revision'] ? String(data['flow_revision']) : null,
    contract_valid: data['contract_valid'] === true,
    collection_slug: data['collection_slug'] ? String(data['collection_slug']) : null,
    collection_status: data['collection_status'] ? String(data['collection_status']) : null,
    collection_chunk_count:
      typeof data['collection_chunk_count'] === 'number' ? data['collection_chunk_count'] : null,
    invariants,
    rollout_ready: data['rollout_ready'] === true || invariants.length === 0,
    modes: modes.length ? modes : [...CHAT_EXECUTION_MODES],
    changed: data['changed'] === true,
    audit_event_id: data['audit_event_id'] ? String(data['audit_event_id']) : null,
  };
}

export function chatExecutionSaveBody(
  mode: ChatExecutionMode,
  percentage: unknown,
): { mode: ChatExecutionMode; percentage: number } {
  return {
    mode,
    percentage: mode === 'classic' ? 0 : clampChatExecutionPercentage(percentage),
  };
}
