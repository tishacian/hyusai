import assert from 'node:assert/strict';
import { test } from 'node:test';
import { automationGovernedPalette } from './automation-palette';

test('an automation can add approval, cited retrieval and a sealed SAP write', () => {
  const items = automationGovernedPalette();
  assert.deepEqual(items.map((item) => item.label), ['Approval', 'Retrieve', 'SAP write']);
  const approval = items[0];
  assert.equal(approval.kind, 'hitl');
  assert.ok(approval.outputs?.some((port) => port.name === 'decided_by'));
  const retrieve = items[1].config as Record<string, unknown>;
  assert.equal(retrieve['skill_slug'], 'semantic_search_v1');
  assert.deepEqual(items[1].outputs?.map((port) => port.name), ['passage', 'source']);
  const write = items[2].config as Record<string, unknown>;
  assert.equal(write['skill_slug'], 'sap_create_po_v1');
  assert.deepEqual(write['inputs_map'], {});
});
