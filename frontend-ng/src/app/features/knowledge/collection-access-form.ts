/**
 * L35 · the « Accès » form of a knowledge collection, as a pure model.
 *
 * The backend policy (`KnowledgeCollection.access`) is `null` for an open
 * collection, else `{ read?, write? }` where a missing action keeps its open
 * default and a list names who may do it (`role:`, `group:`, `user:`). An
 * empty list leaves the action to workspace admins, who always keep access.
 * Adding documents also needs reading, and viewers never add documents.
 */

export type AccessAction = 'read' | 'write';
export type AccessMode = 'all' | 'selected';

export interface CollectionAccessPolicy {
  read?: string[] | null;
  write?: string[] | null;
}

export interface AccessRule {
  mode: AccessMode;
  principals: string[];
}

export interface CollectionAccessForm {
  read: AccessRule;
  write: AccessRule;
}

export interface AccessFormError {
  code: 'write_needs_read';
  principals: string[];
}

/** Roles offered as grants; admins and owners always have access. */
export const ACCESS_ROLE_TEMPLATES = ['workspace_viewer', 'workspace_contributor', 'workspace_reviewer'] as const;

const VIEWER = 'role:workspace_viewer';

function rule(principals: string[] | null | undefined): AccessRule {
  return Array.isArray(principals)
    ? { mode: 'selected', principals: [...new Set(principals)] }
    : { mode: 'all', principals: [] };
}

export function formFromPolicy(policy: CollectionAccessPolicy | null | undefined): CollectionAccessForm {
  return { read: rule(policy?.read), write: rule(policy?.write) };
}

/** The policy to PATCH: `null` when both actions stay open to every member. */
export function policyFromForm(form: CollectionAccessForm): CollectionAccessPolicy | null {
  const policy: CollectionAccessPolicy = {};
  if (form.read.mode === 'selected') policy.read = [...form.read.principals];
  if (form.write.mode === 'selected') {
    policy.write = form.write.principals.filter((principal) => canGrant('write', principal));
  }
  return policy.read === undefined && policy.write === undefined ? null : policy;
}

/** Viewers never add documents: the write grant is not offered to them. */
export function canGrant(action: AccessAction, principal: string): boolean {
  return action === 'read' || principal !== VIEWER;
}

export function setMode(form: CollectionAccessForm, action: AccessAction, mode: AccessMode): CollectionAccessForm {
  return { ...form, [action]: { ...form[action], mode } };
}

export function togglePrincipal(
  form: CollectionAccessForm,
  action: AccessAction,
  principal: string,
  granted: boolean,
): CollectionAccessForm {
  if (!canGrant(action, principal)) return form;
  const current = form[action].principals.filter((item) => item !== principal);
  const principals = granted ? [...current, principal] : current;
  return { ...form, [action]: { mode: 'selected', principals } };
}

export function isGranted(form: CollectionAccessForm, action: AccessAction, principal: string): boolean {
  return form[action].mode === 'selected' && form[action].principals.includes(principal);
}

/** Who may add documents must also be able to read them. */
export function accessFormErrors(form: CollectionAccessForm): AccessFormError[] {
  if (form.read.mode === 'all' || form.write.mode === 'all') return [];
  const missing = form.write.principals.filter(
    (principal) => canGrant('write', principal) && !form.read.principals.includes(principal),
  );
  return missing.length ? [{ code: 'write_needs_read', principals: missing }] : [];
}

export function samePolicy(a: CollectionAccessPolicy | null, b: CollectionAccessPolicy | null): boolean {
  const norm = (value: CollectionAccessPolicy | null) =>
    JSON.stringify({
      read: value?.read ? [...value.read].sort() : null,
      write: value?.write ? [...value.write].sort() : null,
    });
  return norm(a) === norm(b);
}
