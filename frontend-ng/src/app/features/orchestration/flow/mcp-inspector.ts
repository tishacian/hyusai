/** Named MCP skills and the generic call. Inspector chips name the server, not HANA. */

export const MCP_NAMED_SERVER: Record<string, 'sap' | 'hikma'> = {
  sap_list_approved_prs_v1: 'sap',
  sap_check_budget_v1: 'sap',
  sap_get_justification_v1: 'sap',
  sap_reject_pr_v1: 'sap',
  hikma_list_pos_by_type_v1: 'hikma',
  sap_create_po_v1: 'sap',
  sap_handle_rejection_v1: 'sap',
};

export const MCP_CALL_SKILL = 'mcp_call_v1';

export const MCP_SKILL_SLUGS = new Set<string>([...Object.keys(MCP_NAMED_SERVER), MCP_CALL_SKILL]);

export function isMcpSkillSlug(slug: string | null | undefined): boolean {
  return !!slug && MCP_SKILL_SLUGS.has(slug);
}

export function mcpServerIdForSlug(
  slug: string | null | undefined,
  params?: Record<string, unknown> | null,
): string {
  if (!slug) return '';
  const named = MCP_NAMED_SERVER[slug];
  if (named) return named;
  if (slug !== MCP_CALL_SKILL) return '';
  const raw = params?.['server_id'];
  return typeof raw === 'string' ? raw.trim() : '';
}
