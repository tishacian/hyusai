import assert from 'node:assert/strict';
import test from 'node:test';
import { isMcpSkillSlug, mcpServerIdForSlug } from './mcp-inspector';

test('named MCP skills point at sap or hikma, never HANA', () => {
  assert.equal(mcpServerIdForSlug('sap_create_po_v1'), 'sap');
  assert.equal(mcpServerIdForSlug('hikma_list_pos_by_type_v1'), 'hikma');
  assert.equal(mcpServerIdForSlug('sap_hana_query_v1'), '');
  assert.equal(isMcpSkillSlug('sap_reject_pr_v1'), true);
  assert.equal(isMcpSkillSlug('sap_hana_query_v1'), false);
});

test('mcp_call_v1 reads server_id from params', () => {
  assert.equal(mcpServerIdForSlug('mcp_call_v1', { server_id: 'hikma' }), 'hikma');
  assert.equal(mcpServerIdForSlug('mcp_call_v1', {}), '');
});
