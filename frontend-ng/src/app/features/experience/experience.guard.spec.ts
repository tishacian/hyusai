import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  canAccessExperienceStudio,
  canEditExperienceStudio,
  canReleaseExperienceStudio,
} from './experience-access';

test('viewer stays in Work while reviewer can inspect the Studio inventory', () => {
  assert.equal(canAccessExperienceStudio('workspace_viewer'), false);
  assert.equal(canAccessExperienceStudio('workspace_reviewer'), true);
  assert.equal(canEditExperienceStudio('workspace_reviewer'), false);
  assert.equal(canReleaseExperienceStudio('workspace_reviewer'), true);
});

test('contributors and workspace administrators can edit Studio experiences', () => {
  assert.equal(canEditExperienceStudio('workspace_contributor'), true);
  assert.equal(canReleaseExperienceStudio('workspace_contributor'), false);
  assert.equal(canEditExperienceStudio('workspace_admin'), true);
  assert.equal(canEditExperienceStudio(null, 'owner'), true);
});
