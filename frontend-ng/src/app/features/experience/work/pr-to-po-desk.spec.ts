import assert from 'node:assert/strict';
import test from 'node:test';

import {
  composeDesk,
  hanaLaneFromPreview,
  laneFromPreview,
  pickDeskColumns,
} from './pr-to-po-desk';

test('prefers business columns over the raw OData left-edge', () => {
  assert.deepEqual(
    pickDeskColumns(
      ['__metadata', 'to_PurchaseReqnItem', 'PurchaseRequisition', 'CreationDate', 'Plant'],
      'pr',
    ),
    ['PurchaseRequisition', 'CreationDate', 'Plant'],
  );
});

test('a live PR preview becomes a live lane with the advertised tool name', () => {
  const lane = laneFromPreview('pr', 'sap', {
    ok: true,
    tool: 'get_A_PurchaseRequisitionHeader',
    columns: ['PurchaseRequisition', 'PurchaseRequisitionType', 'CreationDate'],
    rows: [
      ['10001234', 'NB', '2026-08-01'],
      ['10001235', 'NB', '2026-08-02'],
    ],
    row_count: 2,
  });
  assert.equal(lane.status, 'live');
  assert.equal(lane.tool, 'get_A_PurchaseRequisitionHeader');
  assert.equal(lane.rowCount, 2);
  assert.deepEqual(lane.columns[0], 'PurchaseRequisition');
});

test('a 403 on goods receipt is caution, not a silent empty table', () => {
  const lane = laneFromPreview('gr', 'sap_gr', null, 'SAP refused the material document (403)');
  assert.equal(lane.status, 'caution');
  assert.match(lane.detail, /403/);
});

test('HANA demo tables count as live context, not a connector failure', () => {
  const lane = hanaLaneFromPreview({
    ok: true,
    source: 'demo_dataset',
    sample_table: 'DEMO_EQUIPMENT',
    tables: [{ name: 'DEMO_EQUIPMENT' }, { name: 'DEMO_MAINTENANCE_ORDERS' }],
    columns: ['EQUIPMENT_ID', 'PLANT', 'STATUS'],
    rows: [['P-12', '3000', 'OPEN']],
    row_count: 1,
  });
  assert.equal(lane.status, 'live');
  assert.equal(lane.rowCount, 2);
  assert.equal(lane.source, 'demo_dataset');
});

test('the briefing names live counts and sends the human to decide when a dossier waits', () => {
  const pr = laneFromPreview('pr', 'sap', {
    ok: true,
    tool: 'get_A_PurchaseRequisitionHeader',
    columns: ['PurchaseRequisition'],
    rows: [['1'], ['2'], ['3']],
    row_count: 3,
  });
  const inbox = laneFromPreview('inbox', 'sap_inbox', {
    ok: true,
    tool: 'getTaskCollection',
    columns: ['TaskTitle'],
    rows: [['Approve PR']],
    row_count: 1,
  });
  const briefing = composeDesk([pr, inbox], 1);
  assert.equal(briefing.headlineKey, 'experience.pr_to_po.desk.headline.live');
  assert.equal(briefing.headlineParams['prs'], 3);
  assert.equal(briefing.headlineParams['tasks'], 1);
  assert.equal(briefing.nextKey, 'experience.pr_to_po.desk.next.decide');
  assert.equal(briefing.kpis[0]?.tone, 'ok');
});

test('a dark terrain asks for a retry, not a write', () => {
  const briefing = composeDesk([laneFromPreview('pr', 'sap', null, 'unreachable')], 0);
  assert.equal(briefing.headlineKey, 'experience.pr_to_po.desk.headline.none');
  assert.equal(briefing.nextKey, 'experience.pr_to_po.desk.next.retry');
});
