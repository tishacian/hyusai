/**
 * Address of the creation wizard (plan lot 4): the step and the application
 * being created live in the URL, so a reload, a bookmark or a return from
 * publishing a System lands on the same step. Pure, unit-tested.
 */

export const WIZARD_PATH = '/create/apps/new';
export const WIZARD_STEP_NAMES = ['identity', 'bind', 'access'] as const;
export type WizardStepName = (typeof WIZARD_STEP_NAMES)[number];

export function wizardStepFromParam(value: string | null | undefined): number | null {
  const index = WIZARD_STEP_NAMES.indexOf(value as WizardStepName);
  return index === -1 ? null : index + 1;
}

export function wizardStepParam(step: number): WizardStepName {
  return WIZARD_STEP_NAMES[Math.min(Math.max(step, 1), 3) - 1]!;
}

export function wizardQueryParams(draftId: string | null, step: number): Record<string, string> {
  return draftId ? { draft: draftId, step: wizardStepParam(step) } : { step: wizardStepParam(step) };
}

export function wizardUrl(draftId: string, step: number): string {
  const params = new URLSearchParams(wizardQueryParams(draftId, step));
  return `${WIZARD_PATH}?${params.toString()}`;
}

/**
 * The step to open when resuming: the one the server kept, unless the URL
 * asks for an earlier one. Never a later step than the author reached.
 */
export function resumeStep(saved: number | null | undefined, requested: number | null): number {
  const reached = saved && saved >= 1 && saved <= 3 ? saved : 1;
  return requested && requested <= reached ? requested : reached;
}

/** Only a wizard address is a valid way back from creating a System. */
export function wizardReturnTo(value: string | null | undefined): string | null {
  if (!value || value.includes('\\') || value.length > 500) return null;
  return value.startsWith(`${WIZARD_PATH}?`) ? value : null;
}

export type SlugProblem = 'invalid' | 'taken' | 'immutable';

const SLUG_RE = /^[a-z][a-z0-9-]{0,119}$/;

/** Same rule as the server (`SLUG_RE` in services/experience/lifecycle.py). */
export function slugProblem(slug: string, taken: readonly string[] = []): SlugProblem | null {
  if (!SLUG_RE.test(slug)) return 'invalid';
  return taken.includes(slug) ? 'taken' : null;
}

export function slugProblemFromCode(code: string | null | undefined): SlugProblem | null {
  if (code === 'EXPERIENCE_SLUG_INVALID') return 'invalid';
  if (code === 'EXPERIENCE_SLUG_EXISTS') return 'taken';
  if (code === 'EXPERIENCE_DEPLOYED_SLUG_IMMUTABLE') return 'immutable';
  return null;
}
