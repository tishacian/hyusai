/**
 * Validate Work `returnTo` query targets (L14/L15).
 * Only internal absolute paths that look catalogued are accepted.
 */
export function isCataloguedReturnTo(value: string | null | undefined): boolean {
  if (!value) return false;
  const trimmed = value.trim();
  if (!trimmed.startsWith('/') || trimmed.startsWith('//') || trimmed.includes('\\')) return false;
  if (trimmed.includes('://') || trimmed.includes('..')) return false;
  // Work-internal or known Cockpit surfaces.
  return (
    trimmed === '/work'
    || trimmed.startsWith('/work/')
    || trimmed.startsWith('/systems/')
    || trimmed.startsWith('/create/')
    || trimmed.startsWith('/observability')
    || trimmed.startsWith('/runs')
    || trimmed.startsWith('/hypervisor')
    || trimmed.startsWith('/knowledge')
    || trimmed.startsWith('/governance')
    || trimmed.startsWith('/resources')
    || trimmed.startsWith('/connectors')
    || trimmed.startsWith('/data')
    || trimmed.startsWith('/models')
    || trimmed.startsWith('/skills')
    || trimmed.startsWith('/contexts')
    || trimmed.startsWith('/tasks')
    || trimmed.startsWith('/steering')
    || trimmed.startsWith('/intelligence')
  );
}

export function returnToFromParams(raw: string | null): string | null {
  return isCataloguedReturnTo(raw) ? raw!.trim() : null;
}
