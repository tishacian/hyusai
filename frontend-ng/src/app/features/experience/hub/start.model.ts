/**
 * Pure rules of the "where to start" step of Créer (plan lot 4: US03, US07,
 * US08). No Angular here, so the rules are unit-tested without a browser.
 */

export type PrerequisiteId = 'work' | 'model' | 'collection' | 'system' | 'publish';
/** `error`: the read failed, so nobody knows; never shown as `missing`. */
export type PrerequisiteState = 'loading' | 'ok' | 'missing' | 'error';

export const PREREQUISITES: readonly PrerequisiteId[] = ['work', 'model', 'collection', 'system', 'publish'];

/** Why creating a blank automation stopped, from the step that failed. */
export type AutomationFailure = 'no_model' | 'refused' | 'unverifiable' | 'failed';

export function httpStatus(error: unknown): number | null {
  if (typeof error !== 'object' || error === null || !('status' in error)) return null;
  const status = Number((error as { status: unknown }).status);
  return Number.isFinite(status) ? status : null;
}

/**
 * - reading the model catalogue failed: nothing is known, `unverifiable`;
 * - creating was refused (401/403): `refused`, a different message from a
 *   missing model;
 * - no answer (0, 502–504): `unverifiable`, the System may or may not exist;
 * - anything else: `failed`.
 */
export function automationFailure(stage: 'skills' | 'create', error: unknown): AutomationFailure {
  const status = httpStatus(error);
  if (stage === 'skills') return status === 401 || status === 403 ? 'refused' : 'unverifiable';
  if (status === 401 || status === 403) return 'refused';
  if (status === null || status === 0 || status === 502 || status === 503 || status === 504) return 'unverifiable';
  return 'failed';
}

/** A count read: present when at least one, `error` when the read failed. */
export function countState(count: number | null, failed: boolean): PrerequisiteState {
  if (failed) return 'error';
  if (count === null) return 'loading';
  return count > 0 ? 'ok' : 'missing';
}

export type ExampleImportFailure = 'refused' | 'invalid' | 'unverifiable' | 'failed';

export function exampleImportFailure(error: unknown): ExampleImportFailure {
  const status = httpStatus(error);
  if (status === 401 || status === 403) return 'refused';
  if (status === 400 || status === 422) return 'invalid';
  if (status === null || status === 0 || status === 502 || status === 503 || status === 504) return 'unverifiable';
  return 'failed';
}
