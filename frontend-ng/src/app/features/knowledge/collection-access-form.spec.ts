import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  accessFormErrors,
  canGrant,
  formFromPolicy,
  isGranted,
  policyFromForm,
  samePolicy,
  setMode,
  togglePrincipal,
} from './collection-access-form';

test('L35 an open collection reads as « all members » for both actions and saves as null', () => {
  const form = formFromPolicy(null);
  assert.deepEqual(form, { read: { mode: 'all', principals: [] }, write: { mode: 'all', principals: [] } });
  assert.equal(policyFromForm(form), null);
});

test('L35 each action is restricted on its own; a missing action stays open', () => {
  const form = formFromPolicy({ write: ['user:u-1'] });
  assert.equal(form.read.mode, 'all');
  assert.deepEqual(form.write, { mode: 'selected', principals: ['user:u-1'] });
  assert.deepEqual(policyFromForm(form), { write: ['user:u-1'] });
});

test('L35 choosing « selected » with nobody leaves the action to admins (empty list)', () => {
  const form = setMode(formFromPolicy(null), 'read', 'selected');
  assert.deepEqual(policyFromForm(form), { read: [] });
});

test('L35 toggling grants selects the action and keeps principals unique', () => {
  let form = formFromPolicy(null);
  form = togglePrincipal(form, 'read', 'role:workspace_reviewer', true);
  form = togglePrincipal(form, 'read', 'group:legal', true);
  form = togglePrincipal(form, 'read', 'group:legal', true);
  assert.equal(form.read.mode, 'selected');
  assert.deepEqual(form.read.principals, ['role:workspace_reviewer', 'group:legal']);
  assert.ok(isGranted(form, 'read', 'group:legal'));
  form = togglePrincipal(form, 'read', 'group:legal', false);
  assert.deepEqual(form.read.principals, ['role:workspace_reviewer']);
});

test('L35 viewers are never offered the write grant', () => {
  assert.equal(canGrant('write', 'role:workspace_viewer'), false);
  assert.equal(canGrant('read', 'role:workspace_viewer'), true);
  const form = togglePrincipal(formFromPolicy(null), 'write', 'role:workspace_viewer', true);
  assert.equal(form.write.mode, 'all');
  assert.deepEqual(policyFromForm(formFromPolicy({ write: ['role:workspace_viewer', 'user:u'] })), {
    write: ['user:u'],
  });
});

test('L35 who adds documents must also read them', () => {
  let form = formFromPolicy({ read: ['group:legal'], write: ['group:legal', 'user:u-2'] });
  assert.deepEqual(accessFormErrors(form), [{ code: 'write_needs_read', principals: ['user:u-2'] }]);
  form = togglePrincipal(form, 'read', 'user:u-2', true);
  assert.deepEqual(accessFormErrors(form), []);
  // Reading open to every member: any writer can read.
  assert.deepEqual(accessFormErrors(formFromPolicy({ write: ['user:u-3'] })), []);
});

test('L35 policies compare without caring about order', () => {
  assert.ok(samePolicy({ read: ['a', 'b'] }, { read: ['b', 'a'] }));
  assert.ok(!samePolicy({ read: ['a'] }, null));
  assert.ok(samePolicy(null, {}));
});
