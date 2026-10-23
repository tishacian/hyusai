/** A Run reference shorter than a full id, such as the 8 characters shown in titles. */
export function isShortRunReference(id: string | null | undefined): boolean {
  const value = (id ?? '').trim();
  return value.length >= 8 && value.length < 36 && /^[0-9a-f-]+$/i.test(value);
}

export type ShortReferenceOutcome = { kind: 'open'; runId: string } | { kind: 'ambiguous' } | { kind: 'none' };

/** What to do with the server's matches for a short reference. */
export function shortReferenceOutcome(resolved: { run_ids?: unknown; ambiguous?: unknown } | null | undefined): ShortReferenceOutcome {
  const ids = Array.isArray(resolved?.run_ids) ? resolved!.run_ids.filter((id): id is string => typeof id === 'string') : [];
  if (resolved?.ambiguous === true || ids.length > 1) return { kind: 'ambiguous' };
  return ids.length === 1 ? { kind: 'open', runId: ids[0] } : { kind: 'none' };
}
