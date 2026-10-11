import assert from 'node:assert/strict';
import test from 'node:test';
import {
  type WorkspaceBlueprintPlanBinding,
  workspaceBlueprintPlanIsCurrent,
} from './workspace-blueprint-plan';

const binding: WorkspaceBlueprintPlanBinding = {
  planToken: 'signed-plan-token',
  canApply: true,
  workspaceSlug: 'andritz-copy',
  blueprintText: '{"schema_version":2}',
  experiencePolicy: 'merge_missing',
  entitlementPolicy: 'preserve_target',
  activateSystems: false,
};

test('a blueprint dry-run remains applicable only for its exact target and choices', () => {
  assert.equal(workspaceBlueprintPlanIsCurrent(binding, {
    workspaceSlug: 'andritz-copy',
    blueprintText: '{"schema_version":2}',
    experiencePolicy: 'merge_missing',
    entitlementPolicy: 'preserve_target',
    activateSystems: false,
  }), true);

  assert.equal(workspaceBlueprintPlanIsCurrent(binding, {
    workspaceSlug: 'sentinel-copy',
    blueprintText: '{"schema_version":2}',
    experiencePolicy: 'merge_missing',
    entitlementPolicy: 'preserve_target',
    activateSystems: false,
  }), false, 'workspace switches invalidate a plan');
});

test('JSON edits and policy changes invalidate a blueprint plan', () => {
  assert.equal(workspaceBlueprintPlanIsCurrent(binding, {
    workspaceSlug: 'andritz-copy',
    blueprintText: '{"schema_version":2,"edited":true}',
    experiencePolicy: 'merge_missing',
    entitlementPolicy: 'preserve_target',
    activateSystems: false,
  }), false);
  assert.equal(workspaceBlueprintPlanIsCurrent(binding, {
    workspaceSlug: 'andritz-copy',
    blueprintText: '{"schema_version":2}',
    experiencePolicy: 'replace_portable',
    entitlementPolicy: 'preserve_target',
    activateSystems: false,
  }), false);
  assert.equal(workspaceBlueprintPlanIsCurrent({ ...binding, canApply: false }, {
    workspaceSlug: 'andritz-copy',
    blueprintText: '{"schema_version":2}',
    experiencePolicy: 'merge_missing',
    entitlementPolicy: 'preserve_target',
    activateSystems: false,
  }), false, 'a conflict-bearing dry-run cannot be applied');
});
