import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

const SOURCE = readFileSync(
  join(process.cwd(), 'src/app/features/workspace/members.component.ts'),
  'utf8',
);

test('L22: invite offers the five IAM role templates and sends role_template', () => {
  assert.match(SOURCE, /data-testid="workspace-invite-role-template"/);
  assert.match(SOURCE, /workspace_viewer/);
  assert.match(SOURCE, /workspace_contributor/);
  assert.match(SOURCE, /workspace_reviewer/);
  assert.match(SOURCE, /workspace_admin/);
  assert.match(SOURCE, /workspace_owner/);
  assert.match(SOURCE, /inviteable:\s*false/);
  assert.match(SOURCE, /inviteMember\(slug, email, this\.inviteTemplate/);
  assert.doesNotMatch(SOURCE, /inviteRole:\s*'admin' \| 'member'/);
});
