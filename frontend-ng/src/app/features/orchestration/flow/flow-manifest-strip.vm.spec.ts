/**
 * Unit tests for `manifestToStripVm` — the manifest → strip projection.
 *
 * Pure logic, no Angular / DI / backend: runs in the `node:test` harness with
 * `@angular/core` aliased to a metadata-only stub. Covers the non-trivial
 * mapping (units / source / effective-config / latest-retrieval-decision) and
 * the scratchpad / no-manifest empty state.
 *
 * Run with `npm run test:unit`.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { FlowRuntimeManifest } from '@app/core/canonical-api.service';
import { manifestToStripVm, type ManifestStripChip } from './flow-manifest-strip.vm';

function chip(vm: NonNullable<ReturnType<typeof manifestToStripVm>>, key: ManifestStripChip['key']): ManifestStripChip {
  const found = vm.chips.find((c) => c.key === key);
  assert.ok(found, `expected a "${key}" chip`);
  return found!;
}

test('scratchpad / no manifest → null (empty state)', () => {
  assert.equal(manifestToStripVm(null), null);
  assert.equal(manifestToStripVm(undefined), null);
});

test('full manifest maps all four facets', () => {
  const manifest: FlowRuntimeManifest = {
    system_id: 'sys-123',
    system_name: 'Compliance Copilot',
    source: 'flow',
    runtime_mode: 'run_engine_dag',
    live_surface: 'run_engine',
    operational_sync: true,
    effective_config: { model: 'gpt-4o', rag_mode: 'chah', top_k: 8 },
    latest_retrieval_decision: {
      run_id: 'run-9f8e7d6c5b4a',
      status: 'completed',
      started_at: '2026-06-24T10:00:00Z',
      trace: { selected_route: 'deep', route_reason: 'ambiguous query' },
    },
    summary: { nodes: 6, operational_units: 4, skill_units: 3 },
  };

  const vm = manifestToStripVm(manifest);
  assert.ok(vm);
  assert.equal(vm!.systemName, 'Compliance Copilot');
  assert.equal(vm!.chips.length, 4);

  assert.equal(chip(vm!, 'units').value, '4/6 live');
  assert.equal(chip(vm!, 'units').tone, 'pos');

  assert.equal(chip(vm!, 'source').value, 'flow · DAG');
  assert.match(chip(vm!, 'source').title, /runtime mode: run_engine_dag/);

  assert.equal(chip(vm!, 'config').value, '3 keys');
  assert.match(chip(vm!, 'config').title, /model = gpt-4o/);

  assert.equal(chip(vm!, 'retrieval').value, 'deep');
  assert.equal(chip(vm!, 'retrieval').tone, 'pos');
});

test('units chip falls back to unit_catalog length and warns when nothing is operational', () => {
  const manifest = {
    system_id: 'sys-x',
    system_name: 'Bare System',
    unit_catalog: [{ id: 'a', label: 'A', kind: 'task' }, { id: 'b', label: 'B', kind: 'task' }],
  } as unknown as FlowRuntimeManifest;

  const vm = manifestToStripVm(manifest);
  const units = chip(vm!, 'units');
  assert.equal(units.value, '0/2 live', 'falls back to unit_catalog count');
  assert.equal(units.tone, 'warn', 'units present but none operational → warn');
});

test('empty effective-config and missing retrieval → neutral fallbacks', () => {
  const manifest: FlowRuntimeManifest = {
    system_id: 'sys-empty',
    system_name: 'Fresh System',
    source: 'form',
  };

  const vm = manifestToStripVm(manifest);
  assert.equal(chip(vm!, 'config').value, '—');
  assert.equal(chip(vm!, 'config').tone, 'neutral');

  const retrieval = chip(vm!, 'retrieval');
  assert.equal(retrieval.value, 'none yet');
  assert.equal(retrieval.tone, 'neutral');

  // Source with no runtime_mode renders just the source token.
  assert.equal(chip(vm!, 'source').value, 'form');
});

test('failed retrieval decision is toned negative', () => {
  const manifest: FlowRuntimeManifest = {
    system_id: 'sys-f',
    system_name: 'Sys',
    latest_retrieval_decision: { status: 'failed', trace: { query_type: 'factual' } },
  };
  const retrieval = chip(manifestToStripVm(manifest)!, 'retrieval');
  assert.equal(retrieval.value, 'factual', 'falls back to query_type when no selected_route');
  assert.equal(retrieval.tone, 'neg');
});
