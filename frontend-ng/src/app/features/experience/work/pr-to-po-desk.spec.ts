import assert from 'node:assert/strict';
import test from 'node:test';

import {
  APPROVED_PR_FILTER,
  APPROVED_PR_TOP,
  DEMO_JUSTIFICATION_PR,
  LIVE_ACCT,
  LIVE_BUDGET,
  LIVE_PO_HEADER,
  LIVE_PO_ITEM,
  LIVE_PR_ITEM,
  LIVE_PR_ITEM_BY_KEY,
  PO_HEADER_CAP,
  PO_ITEM_TOP,
  acctAssgmtReadBody,
  approvedPrItemReadBody,
  askFactory,
  budgetOkFromRead,
  budgetReadBody,
  composeDesk,
  extractJustificationText,
  factoryTerrainReadBodies,
  fundFromRead,
  shouldOpenFactoryPortal,
  donutSlices,
  hanaLaneFromPreview,
  interpretFactoryAsk,
  isFactoryWriteTool,
  justificationReadBody,
  laneFromPreview,
  mergeHeaderPreviews,
  offersSelectedJustification,
  orderCoverage,
  pickDeskColumns,
  poHeaderReadBody,
  poItemReadBody,
  selectedPrFromLane,
  supplierShares,
  terrainShares,
  uniquePurchaseOrders,
  withCompileFacts,
  withJustificationFact,
} from './pr-to-po-desk';

test('prefers PDF item columns on the PR lane', () => {
  assert.deepEqual(
    pickDeskColumns(
      [
        'PurchaseRequisition',
        'PurchaseRequisitionItem',
        'PurchaseRequisitionItemText',
        'MaterialGroup',
        'RequestedQuantity',
        'Plant',
      ],
      'pr',
    ),
    [
      'PurchaseRequisition',
      'PurchaseRequisitionItem',
      'PurchaseRequisitionItemText',
      'MaterialGroup',
      'RequestedQuantity',
    ],
  );
});

test('prefers business columns over the raw OData left-edge', () => {
  assert.deepEqual(
    pickDeskColumns(
      ['__metadata', 'to_PurchaseReqnItem', 'PurchaseRequisition', 'CreationDate', 'Plant'],
      'pr',
    ),
    ['PurchaseRequisition', 'CreationDate', 'Plant'],
  );
  assert.deepEqual(
    pickDeskColumns(
      ['TaskSupports', 'InstanceID', 'TaskDefinitionName', 'TaskTitle', 'Priority'],
      'inbox',
    ),
    ['TaskTitle', 'TaskDefinitionName', 'Priority', 'InstanceID'],
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
  const wrapped = laneFromPreview('gr', 'sap_gr', {
    ok: true,
    columns: ['status', 'error', 'message'],
    rows: [['403', 'True', 'No service found']],
    row_count: 1,
  });
  assert.equal(wrapped.status, 'caution');
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
  assert.equal(briefing.stations.find((station) => station.id === 'write')?.status, 'sealed');
  assert.equal(briefing.stations.find((station) => station.id === 'connect')?.status, 'blocked');
});

test('the compiled dossier keeps the described PR, not the first empty header', () => {
  const pr = laneFromPreview('pr', 'sap', {
    ok: true,
    tool: 'get_A_PurchaseRequisitionHeader',
    columns: ['PurchaseRequisition', 'PurReqnDescription'],
    rows: [
      ['1000000000', ''],
      ['1000000033', 'Ahmed - Approved By site Petty Cash'],
    ],
    row_count: 2,
  });
  const po = laneFromPreview('po', 'hikma', {
    ok: true,
    tool: 'get_A_PurchaseOrder',
    columns: ['PurchaseOrder', 'Supplier'],
    rows: [['4200000000', '100012']],
    row_count: 1,
  });
  const briefing = composeDesk([pr, po], 0);
  assert.equal(briefing.headlineParams['pr'], 'Ahmed - Approved By site Petty Cash');
  assert.equal(briefing.facts.find((fact) => fact.id === 'pr')?.value, 'Ahmed - Approved By site Petty Cash');
});

test('the factory compiles a dossier from live SAP columns and keeps the write sealed', () => {
  const pr = laneFromPreview('pr', 'sap', {
    ok: true,
    tool: 'get_A_PurchaseRequisitionHeader',
    columns: ['PurchaseRequisition', 'PurReqnDescription'],
    rows: [['1000008', 'Ahmed - Approved By site Petty Cash']],
    row_count: 1,
  });
  const inbox = laneFromPreview('inbox', 'sap_inbox', {
    ok: true,
    tool: 'listTaskCollection',
    columns: ['TaskTitle'],
    rows: [['Release TR transaction 1000008']],
    row_count: 1,
  });
  const po = laneFromPreview('po', 'hikma', {
    ok: true,
    tool: 'get_A_PurchaseOrder',
    columns: ['PurchaseOrder', 'PurchaseOrderType', 'Supplier'],
    rows: [
      ['4200000000', 'ZAPO', '100012'],
      ['4200000001', 'ZAPO', '100012'],
      ['4200000002', 'NB', '100099'],
    ],
    row_count: 3,
  });
  const briefing = composeDesk([pr, inbox, po], 0);
  assert.equal(briefing.headlineKey, 'experience.pr_to_po.desk.headline.compiled');
  assert.equal(briefing.headlineParams['pr'], 'Ahmed - Approved By site Petty Cash');
  assert.equal(briefing.headlineParams['supplier'], '100012');
  assert.deepEqual(
    briefing.facts.map((fact) => fact.id),
    ['pr', 'inbox', 'supplier', 'format'],
  );
  assert.equal(briefing.facts.find((fact) => fact.id === 'supplier')?.via, 'get_A_PurchaseOrder');
  assert.equal(briefing.stations.find((station) => station.id === 'compile')?.status, 'done');
  assert.equal(briefing.stations.find((station) => station.id === 'compile')?.via, 'python_recipe_v1');
  assert.equal(briefing.stations.find((station) => station.id === 'decide')?.status, 'ready');
  assert.equal(briefing.stations.find((station) => station.id === 'write')?.status, 'sealed');
  assert.equal(briefing.voiceKey, 'experience.pr_to_po.desk.voice.compiled');
  assert.equal(briefing.voiceParams['format'], 'ZAPO');
  assert.equal(briefing.selectedPrId, '1000008');
});

test('justification stays a desk fact and never unseals the write', () => {
  const pr = laneFromPreview('pr', 'sap', {
    ok: true,
    tool: 'get_A_PurchaseRequisitionHeader',
    columns: ['PurchaseRequisition', 'PurReqnDescription'],
    rows: [['1000000033', 'Ahmed - Approved By site Petty Cash']],
    row_count: 1,
  });
  const briefing = composeDesk([pr], 0);
  assert.equal(briefing.selectedPrId, '1000000033');
  assert.equal(offersSelectedJustification(briefing.selectedPrId), true);
  assert.equal(offersSelectedJustification(DEMO_JUSTIFICATION_PR), false);
  assert.deepEqual(justificationReadBody(), {
    tool: LIVE_PR_ITEM_BY_KEY,
    arguments: {
      PurchaseRequisition: DEMO_JUSTIFICATION_PR,
      PurchaseRequisitionItem: '10',
      expand: 'to_PurchaseReqnItemText',
    },
  });
  assert.equal(justificationReadBody('1000000033').arguments.PurchaseRequisition, '1000000033');
  assert.equal(
    extractJustificationText({
      data: {
        to_PurchaseReqnItemText: { results: [{ Note: 'Need 40 warehouse scanners.' }] },
      },
    }),
    'Need 40 warehouse scanners.',
  );
  assert.equal(
    extractJustificationText({ justification: 'Finance laptops are past refresh.' }),
    'Finance laptops are past refresh.',
  );
  assert.equal(
    extractJustificationText({
      status: 200,
      data: {
        PurchaseRequisitionItemText: ' LORX  FURNITURE CLEANER  - 650 ML - GRE',
        to_PurchaseReqnItemText: {
          results: [{ NoteDescription: ' LORX  FURNITURE CLEANER  - 650 ML - GREEN' }],
        },
      },
    }),
    'LORX  FURNITURE CLEANER  - 650 ML - GREEN',
  );
  const withText = withJustificationFact(
    briefing,
    'Need 40 warehouse scanners.',
    LIVE_PR_ITEM_BY_KEY,
  );
  assert.equal(withText.facts.find((fact) => fact.id === 'justification')?.value, 'Need 40 warehouse scanners.');
  assert.equal(withText.stations.find((station) => station.id === 'write')?.status, 'sealed');
});

test('charts and coverage stay on the live columns, not invented aliases', () => {
  const pr = laneFromPreview('pr', 'sap', {
    ok: true,
    columns: ['PurchaseRequisition'],
    rows: [['1'], ['2']],
    row_count: 2,
  });
  const po = laneFromPreview('po', 'hikma', {
    ok: true,
    columns: ['PurchaseOrder', 'Supplier'],
    rows: [
      ['4201', '100012'],
      ['4202', '100012'],
      ['4203', '100099'],
    ],
    row_count: 3,
  });
  const briefing = composeDesk([pr, po], 0);
  const terrain = terrainShares(briefing.kpis);
  assert.deepEqual(
    terrain.map((row) => row.id),
    ['pr', 'po'],
  );
  assert.equal(terrain.find((row) => row.id === 'po')?.value, 3);
  const slices = donutSlices(terrain);
  assert.equal(slices[0]?.offset, 0);
  assert.ok((slices[1]?.offset ?? 0) < 0);
  const suppliers = supplierShares([pr, po]);
  assert.equal(suppliers[0]?.id, '100012');
  assert.equal(suppliers[0]?.value, 2);
  const coverage = orderCoverage([pr, po]);
  assert.equal(coverage.prs, 2);
  assert.equal(coverage.pos, 3);
  assert.equal(coverage.pct, 100);
});

test('PDF read bodies match the PIH QA filter and never post a write', () => {
  const approved = approvedPrItemReadBody();
  assert.equal(approved.tool, LIVE_PR_ITEM);
  assert.equal(approved.arguments.top, APPROVED_PR_TOP);
  assert.equal(typeof approved.arguments.top, 'string');
  assert.match(approved.arguments.filter, /IsClosed eq false/);
  assert.equal(approved.arguments.filter.includes("IsClosed eq 'false'"), false);
  assert.equal(approved.arguments.filter, APPROVED_PR_FILTER);
  assert.equal(budgetReadBody('2000276450').tool, LIVE_BUDGET);
  assert.deepEqual(budgetReadBody('2000276450').arguments, { PurchaseRequisition: '2000276450' });
  assert.equal(acctAssgmtReadBody('2000276450').tool, LIVE_ACCT);
  assert.match(acctAssgmtReadBody('2000276450').arguments.filter, /2000276450/);
  const items = poItemReadBody('L001');
  assert.equal(items.tool, LIVE_PO_ITEM);
  assert.equal(items.arguments.top, PO_ITEM_TOP);
  assert.equal(typeof items.arguments.top, 'string');
  assert.equal(poHeaderReadBody('4500000123').tool, LIVE_PO_HEADER);
  const terrain = factoryTerrainReadBodies({
    id: '2000276450',
    materialGroup: 'L001',
    poIds: ['4501', '4502', '4503', '4504', '4505', '4506'],
  });
  assert.equal(terrain.filter((body) => body.tool === LIVE_PO_HEADER).length, PO_HEADER_CAP);
  assert.deepEqual(
    terrain.map((body) => body.tool),
    [LIVE_PR_ITEM, LIVE_BUDGET, LIVE_ACCT, LIVE_PO_ITEM, LIVE_PO_HEADER, LIVE_PO_HEADER, LIVE_PO_HEADER, LIVE_PO_HEADER, LIVE_PO_HEADER],
  );
  for (const body of terrain) {
    assert.equal(isFactoryWriteTool(body.tool), false);
  }
  assert.equal(isFactoryWriteTool('post_A_PurchaseOrder'), true);
  assert.equal(isFactoryWriteTool('fi_DiscardFromPurchasing'), true);
  assert.equal(isFactoryWriteTool('fi_EnableForPurchasing'), true);
});

test('item-shaped PRs compile budget and fund facts and keep the write sealed', () => {
  const pr = laneFromPreview('pr', 'sap', {
    ok: true,
    tool: LIVE_PR_ITEM,
    columns: [
      'PurchaseRequisition',
      'PurchaseRequisitionItem',
      'PurchaseRequisitionItemText',
      'MaterialGroup',
    ],
    rows: [['2000276450', '10', 'LORX FURNITURE CLEANER - 650 ML - GREEN', 'L001']],
    row_count: 65833,
  });
  assert.equal(pr.rowCount, 1);
  const selected = selectedPrFromLane(pr);
  assert.equal(selected.id, '2000276450');
  assert.equal(selected.materialGroup, 'L001');
  assert.match(selected.label, /LORX/);
  const po = laneFromPreview('po', 'hikma', {
    ok: true,
    tool: LIVE_PO_HEADER,
    columns: ['PurchaseOrder', 'PurchaseOrderType', 'Supplier'],
    rows: [['4500000123', 'ZAPO', '100012']],
    row_count: 1,
  });
  const briefing = withCompileFacts(composeDesk([pr, po], 0), {
    budget: 'ok',
    budgetVia: LIVE_BUDGET,
    fund: '2821',
    fundscenter: 'FC01',
    fundVia: LIVE_ACCT,
  });
  assert.equal(briefing.facts.find((fact) => fact.id === 'pr')?.value.includes('LORX'), true);
  assert.equal(briefing.facts.find((fact) => fact.id === 'budget')?.value, 'ok');
  assert.equal(briefing.facts.find((fact) => fact.id === 'fund')?.value, '2821');
  assert.equal(briefing.facts.find((fact) => fact.id === 'fundscenter')?.value, 'FC01');
  assert.equal(briefing.stations.find((station) => station.id === 'write')?.status, 'sealed');
  assert.deepEqual(budgetOkFromRead({ result: [] }), { ok: true, reason: 'ok' });
  assert.deepEqual(budgetOkFromRead({ result: [{ Type: 'E', Message: 'over' }] }), {
    ok: false,
    reason: 'over',
  });
  assert.deepEqual(fundFromRead({ result: [{ Fund: '2821', FundsCenter: 'FC01' }] }), {
    fund: '2821',
    fundscenter: 'FC01',
  });
  assert.deepEqual(
    uniquePurchaseOrders({
      columns: ['PurchaseOrder', 'MaterialGroup'],
      rows: [
        ['4501', 'L001'],
        ['4501', 'L001'],
        ['4502', 'L001'],
      ],
    }),
    ['4501', '4502'],
  );
  const merged = mergeHeaderPreviews([
    { ok: true, tool: LIVE_PO_HEADER, columns: ['PurchaseOrder', 'Supplier'], rows: [['4501', '100012']] },
    { ok: true, tool: LIVE_PO_HEADER, columns: ['PurchaseOrder', 'Supplier'], rows: [['4502', '100099']] },
  ]);
  assert.equal(merged?.rows.length, 2);
});

test('asking the factory stays deterministic and never unseals the write', () => {
  const po = laneFromPreview('po', 'hikma', {
    ok: true,
    columns: ['PurchaseOrder', 'PurchaseOrderType', 'Supplier'],
    rows: [['4201', 'ZAPO', '100012']],
    row_count: 1,
  });
  const briefing = composeDesk([po], 0);
  assert.equal(interpretFactoryAsk('Who is the majority supplier?'), 'supplier');
  assert.equal(interpretFactoryAsk('how many purchase orders'), 'po');
  assert.equal(interpretFactoryAsk('combien de commandes'), 'po');
  assert.equal(interpretFactoryAsk('fournisseurs'), 'supplier');
  assert.equal(interpretFactoryAsk('po'), 'po');
  assert.equal(interpretFactoryAsk('ecrire'), 'write');
  assert.equal(interpretFactoryAsk(''), 'empty');
  const write = askFactory('can we write', briefing, [po]);
  assert.equal(write.intent, 'write');
  assert.equal(write.focus, null);
  assert.match(write.key, /ask\.answer\.write$/);
  const supplier = askFactory('supplier', briefing, [po]);
  assert.equal(supplier.focus, 'po');
  assert.equal(supplier.params['supplier'], '100012');
  assert.equal(briefing.stations.find((station) => station.id === 'write')?.status, 'sealed');
  assert.equal(shouldOpenFactoryPortal('can we write'), false);
  assert.equal(shouldOpenFactoryPortal('how many purchase orders'), false);
  assert.equal(shouldOpenFactoryPortal('next'), false);
  assert.equal(shouldOpenFactoryPortal(''), false);
  assert.equal(shouldOpenFactoryPortal('explain the compiled dossier to the buyer'), true);
});
