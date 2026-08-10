import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  isFlowBackedSystem,
  systemCatalogBadge,
  systemFlowProfile,
  type SystemFlowSource,
} from './system-flow-profile';

/** Shape of the live NAWA reconciliation System: a deterministic graph with
 *  three declared ingresses and no retrieval stage anywhere. */
function reconciliationSystem(
  overrides: Partial<SystemFlowSource> = {},
): SystemFlowSource {
  return {
    id: 'sys-recon',
    flow_definition: {
      source: 'flow',
      schema_version: 3,
      nodes: [
        {
          id: 'source.manual',
          kind: 'source',
          label: 'Manual start',
          config: { ingress_kind: 'manual' },
        },
        {
          id: 'source.deposit',
          kind: 'source',
          label: 'Deposit event',
          config: { ingress_kind: 'event' },
        },
        {
          id: 'source.cron',
          kind: 'source',
          label: 'Nightly',
          config: { ingress_kind: 'schedule' },
        },
        {
          id: 'skill.extract_po',
          kind: 'task',
          label: 'Extract PO lines',
          config: { skill_slug: 'po_lines_extract_v1' },
        },
        {
          id: 'skill.match',
          kind: 'task',
          label: 'Match lines',
          config: { skill_slug: 'recon_match_v1' },
        },
        { id: 'sink.report', kind: 'sink', label: 'Reconciliation report' },
      ],
      edges: [
        { from: 'source.manual', to: 'skill.extract_po', kind: 'data' },
        { from: 'skill.extract_po', to: 'skill.match', kind: 'data' },
        { from: 'skill.match', to: 'sink.report', kind: 'data' },
      ],
    },
    settings: {},
    ...overrides,
  };
}

/** The System Builder projection every classic OmniRAG System carries. */
function formProjectedSystem(): SystemFlowSource {
  return {
    id: 'sys-rag',
    flow_definition: {
      source: 'form',
      schema_version: 3,
      nodes: [
        { id: 'builder.objective', kind: 'source', label: 'Objective' },
        { id: 'builder.context', kind: 'task', label: 'Context' },
        { id: 'builder.launch', kind: 'sink', label: 'Launch' },
      ],
      edges: [],
    },
  };
}

test('a Flow Builder graph with declared ingresses is flow-backed', () => {
  const profile = systemFlowProfile(reconciliationSystem());

  assert.ok(profile);
  assert.equal(profile.nodeCount, 6);
  assert.equal(profile.edgeCount, 3);
  assert.deepEqual(profile.triggers.map((t) => t.kind), ['manual', 'event', 'schedule']);
  assert.deepEqual(profile.skillSlugs, ['po_lines_extract_v1', 'recon_match_v1']);
  assert.equal(profile.steps.length, 6);
  assert.equal(profile.steps[3].label, 'Extract PO lines');
});

test('the System Builder form projection keeps its RAG rendering', () => {
  assert.equal(isFlowBackedSystem(formProjectedSystem()), false);
  assert.equal(systemFlowProfile(formProjectedSystem()), null);
  assert.equal(systemCatalogBadge(formProjectedSystem()), 'OmniRAG');
});

test('the workspace chat System is never described as a graph', () => {
  const chat: SystemFlowSource = {
    id: 'sys-chat',
    flow_definition: {
      variant: 'chat_transverse_v1',
      source: 'system_seed',
      nodes: [
        { id: 'chat.request', kind: 'source', config: { ingress_kind: 'chat' } },
        { id: 'skill.answer', kind: 'task' },
      ],
      edges: [],
    },
    settings: { system_type: 'workspace_chat' },
  };

  assert.equal(isFlowBackedSystem(chat), false);
  assert.equal(systemCatalogBadge(chat), 'Chat');
});

test('variants that already own a bespoke rendering are left alone', () => {
  for (const variant of ['intelligence', 'expert_knowledge_capture', 'translation_suite']) {
    const system = reconciliationSystem();
    (system.flow_definition as Record<string, unknown>)['variant'] = variant;
    assert.equal(isFlowBackedSystem(system), false, variant);
  }
});

test('absent, empty or unauthored graphs fall back to the existing behaviour', () => {
  assert.equal(isFlowBackedSystem(null), false);
  assert.equal(isFlowBackedSystem({ id: 'a' }), false);
  assert.equal(isFlowBackedSystem({ id: 'a', flow_definition: {} }), false);
  assert.equal(isFlowBackedSystem({ id: 'a', flow_definition: { nodes: [] } }), false);
  assert.equal(
    isFlowBackedSystem({
      id: 'a',
      flow_definition: { nodes: [{ id: 'n1', kind: 'task' }], edges: [] },
    }),
    false,
    'nodes alone are not proof of run-engine authorship',
  );
});

test('the server manifest can only narrow the verdict, never open it', () => {
  const system = reconciliationSystem();

  assert.equal(
    isFlowBackedSystem(system, { system_id: 'sys-recon', runtime_surface: 'chat_runtime' }),
    false,
  );
  assert.equal(
    isFlowBackedSystem(system, { system_id: 'sys-recon', runtime_surface: 'run_engine' }),
    true,
  );
  // A manifest belonging to another System is inert.
  assert.equal(
    isFlowBackedSystem(system, { system_id: 'sys-other', runtime_surface: 'chat_runtime' }),
    true,
  );
  assert.equal(
    isFlowBackedSystem(formProjectedSystem(), {
      system_id: 'sys-rag',
      runtime_surface: 'run_engine',
    }),
    false,
  );
});

test('manifest runtime status is projected onto the matching step', () => {
  const profile = systemFlowProfile(reconciliationSystem(), {
    system_id: 'sys-recon',
    runtime_surface: 'run_engine',
    runtime_mode: 'sequential_legacy',
    unit_catalog: [
      { id: 'skill.match', runtime_status: 'bound', operational: true },
      { id: 'skill.extract_po', runtime_status: 'unbound', operational: false },
    ],
  });

  assert.ok(profile);
  assert.equal(profile.runtimeMode, 'sequential_legacy');
  assert.equal(profile.steps[3].runtimeStatus, 'unbound');
  assert.equal(profile.steps[3].operational, false);
  assert.equal(profile.steps[4].runtimeStatus, 'bound');
  assert.equal(profile.steps[4].operational, true);
});

test('publication evidence and scratchpad provenance are surfaced verbatim', () => {
  const profile = systemFlowProfile(
    reconciliationSystem({
      published_flow_version_id: 'ver-7',
      published_at: '2026-08-01T09:30:00',
      published_by: 'ops@nawa',
      settings: { origin: 'scratchpad_promote' },
    }),
  );

  assert.ok(profile);
  assert.equal(profile.publishedVersionId, 'ver-7');
  assert.equal(profile.publishedAt, '2026-08-01T09:30:00');
  assert.equal(profile.publishedBy, 'ops@nawa');
  assert.equal(profile.promotedFromScratchpad, true);
});

test('an unpublished flow-backed System reports the draft badge', () => {
  const profile = systemFlowProfile(reconciliationSystem());

  assert.ok(profile);
  assert.equal(profile.publishedVersionId, null);
  assert.equal(profile.promotedFromScratchpad, false);
  assert.equal(systemCatalogBadge(reconciliationSystem()), 'Flow');
});

test('a source node without config.ingress_kind reports the kind publication derives', () => {
  const seeded: SystemFlowSource = {
    id: 'sys-seed',
    flow_definition: {
      schema_version: 3,
      nodes: [
        { id: 'source.schedule', kind: 'source', type: 'source.schedule', label: 'Nightly' },
        { id: 'source.hook', kind: 'source', type: 'source.webhook', label: 'Webhook' },
        { id: 'source.start', kind: 'source', type: 'input', label: 'Start' },
        { id: 'skill.run', kind: 'task', config: { skill_slug: 'run_v1' } },
      ],
      edges: [],
    },
  };

  const profile = systemFlowProfile(seeded);

  assert.ok(profile, 'a canonical source node is proof enough without source:flow');
  assert.deepEqual(profile.triggers.map((t) => t.kind), ['schedule', 'http', 'manual']);
});

test('a source node declaring an unknown ingress kind is not counted as a trigger', () => {
  const system = reconciliationSystem();
  const nodes = (system.flow_definition as { nodes: Record<string, unknown>[] }).nodes;
  nodes[0]['config'] = { ingress_kind: 'htp' };

  const profile = systemFlowProfile(system);

  assert.ok(profile);
  assert.deepEqual(profile.triggers.map((t) => t.kind), ['event', 'schedule']);
});

test('an explicit rag_mode still wins for systems that are not flow-backed', () => {
  assert.equal(systemCatalogBadge(formProjectedSystem(), 'HAH'), 'HAH');
  assert.equal(systemCatalogBadge(reconciliationSystem(), 'HAH'), 'Flow');
});
