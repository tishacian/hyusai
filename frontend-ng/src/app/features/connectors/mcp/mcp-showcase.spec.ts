import assert from 'node:assert/strict';
import test from 'node:test';

import {
  inferShowcaseReadiness,
  resolveShowcaseLane,
  showcaseInsight,
  sortShowcaseServers,
} from './mcp-showcase';

test('hostname wins when a credential-file label would swap PR and PO', () => {
  assert.equal(
    resolveShowcaseLane('hikma', 'https://hikmah-s4-pr-mcp.cfapps.eu10.hana.ondemand.com/mcp/'),
    'pr',
  );
  assert.equal(
    resolveShowcaseLane('sap', 'https://hikmah-s4-po-mcp.cfapps.eu10.hana.ondemand.com/mcp/'),
    'po',
  );
  assert.equal(
    resolveShowcaseLane('sap_gr', 'https://hikmah-s4-goods-receipt-mcp.example/mcp/'),
    'gr',
  );
  assert.equal(
    resolveShowcaseLane('sap_inbox', 'https://hikmah-s4-inbox-mcp.example/mcp/'),
    'inbox',
  );
});

test('falls back to the attached server id when the host is unknown', () => {
  assert.equal(resolveShowcaseLane('sap', ''), 'pr');
  assert.equal(resolveShowcaseLane('hikma', ''), 'po');
  assert.equal(resolveShowcaseLane('other', 'https://example.test/mcp/'), null);
});

test('readiness comes from live tool names, not invented PDF aliases', () => {
  assert.equal(
    inferShowcaseReadiness('pr', ['get_A_PurchaseRequisitionHeader', 'post_A_PurchaseRequisitionHeader']),
    'ready',
  );
  assert.equal(inferShowcaseReadiness('po', ['get_A_PurchaseOrder']), 'ready');
  assert.equal(inferShowcaseReadiness('gr', ['get_A_MaterialDocumentHeader']), 'caution');
  assert.equal(
    inferShowcaseReadiness('inbox', [
      'getTaskCollection',
      'listCommentCollection',
      'listWorkflowLogCollection',
    ]),
    'partial',
  );
  assert.equal(inferShowcaseReadiness('pr', []), 'unknown');
});

test('orders the four Nawa servers as the PR to PO showcase', () => {
  const ordered = sortShowcaseServers([
    { id: 'hikma', url: 'https://hikmah-s4-po-mcp.example/mcp/' },
    { id: 'sap_gr', url: 'https://hikmah-s4-goods-receipt-mcp.example/mcp/' },
    { id: 'sap', url: 'https://hikmah-s4-pr-mcp.example/mcp/' },
    { id: 'sap_inbox', url: 'https://hikmah-s4-inbox-mcp.example/mcp/' },
  ]).map((row) => row.id);
  assert.deepEqual(ordered, ['sap', 'sap_inbox', 'hikma', 'sap_gr']);
  const insight = showcaseInsight('sap_gr', 'https://hikmah-s4-goods-receipt-mcp.example/mcp/', [
    'get_A_MaterialDocumentHeader',
  ]);
  assert.equal(insight?.step, 4);
  assert.equal(insight?.service, 'API_MATERIAL_DOCUMENT_SRV');
  assert.ok(insight?.notes.includes('gr'));
});
