import assert from 'node:assert/strict';
import test from 'node:test';

import {
  classifyMcpToolKind,
  describeMcpTool,
  groupMcpTools,
  humanizeMcpName,
} from './mcp-catalog';

test('classifies live SAP names as read or write without inventing aliases', () => {
  assert.equal(classifyMcpToolKind('get_A_PurchaseRequisitionHeader'), 'read');
  assert.equal(classifyMcpToolKind('list_approved_prs'), 'read');
  assert.equal(classifyMcpToolKind('post_A_PurchaseOrder'), 'write');
  assert.equal(classifyMcpToolKind('create_po'), 'write');
  assert.equal(classifyMcpToolKind('reject_pr'), 'write');
});

test('humanizes OData and custom-field names for the catalog', () => {
  assert.equal(humanizeMcpName('PurchaseRequisition'), 'Purchase Requisition');
  assert.equal(humanizeMcpName('YY1_POCustomFields'), 'YY1 PO Custom Fields');
  assert.equal(describeMcpTool('get_A_PurchaseRequisitionHeader').entity, 'PurchaseRequisition');
  assert.equal(describeMcpTool('get_A_PurchaseRequisitionItem').entity, 'PurchaseRequisition');
  assert.equal(describeMcpTool('get_A_PurchaseRequisitionHeader_by_key').entity, 'PurchaseRequisition');
  assert.equal(describeMcpTool('get_YY1_POCustomFields').entity, 'YY1_POCustomFields');
});

test('groups header and item tools on the same object', () => {
  const groups = groupMcpTools([
    { name: 'get_A_PurchaseRequisitionHeader', description: 'Read a PR header' },
    { name: 'post_A_PurchaseRequisitionItem', description: 'Create a PR item' },
    { name: 'get_YY1_POCustomFields', description: '' },
  ]);
  assert.equal(groups.length, 2);
  const pr = groups.find((group) => group.entity === 'PurchaseRequisition');
  assert.ok(pr);
  assert.equal(pr?.label, 'Purchase Requisition');
  assert.equal(pr?.read.length, 1);
  assert.equal(pr?.write.length, 1);
  assert.equal(pr?.read[0]?.description, 'Read a PR header');
});
