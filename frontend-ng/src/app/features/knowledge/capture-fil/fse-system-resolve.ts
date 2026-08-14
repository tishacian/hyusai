/**
 * FSE system pick for `/knowledge/interventions`.
 *
 * Flag off: template_id, then a name heuristic. Flag on: a bound system id
 * wins when it is still in the workspace list.
 */

export const ANDRITZ_FSE_BINDING_KEY = 'andritz.fse';

export interface FseSystemCandidate {
  id: string;
  name?: string | null;
  settings?: Record<string, unknown> | null;
}

export function systemIdFromBindingResolve(
  resolved: { status?: string; binding?: { system_id?: string } } | null | undefined,
): string | null {
  const id = resolved?.status === 'ok' ? resolved.binding?.system_id : undefined;
  return typeof id === 'string' && id ? id : null;
}

export function fseTemplateId(sys: FseSystemCandidate): string | null {
  const settings = sys.settings && typeof sys.settings === 'object' ? sys.settings : null;
  const capture = settings?.['capture'] && typeof settings['capture'] === 'object'
    ? settings['capture'] as Record<string, unknown>
    : null;
  const raw = capture?.['template_id'];
  return typeof raw === 'string' && raw.trim() ? raw.trim() : null;
}

export function pickFseSystem(
  systems: readonly FseSystemCandidate[],
  templateId: string,
  boundId: string | null,
): FseSystemCandidate | undefined {
  if (boundId) {
    const bound = systems.find((sys) => sys.id === boundId);
    if (bound) return bound;
  }
  return systems.find((sys) => fseTemplateId(sys) === templateId)
    || systems.find((sys) => /intervention|fse/i.test(sys.name || ''));
}
