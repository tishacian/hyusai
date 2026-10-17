/** Validation shared by the trigger setup form; the server validates cron and the published schema. */
export function schedulePayload(value: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null;
  } catch {
    return null;
  }
}

export function validScheduleTimezone(value: string): boolean {
  if (!value.trim()) return false;
  try {
    new Intl.DateTimeFormat('en', { timeZone: value.trim() }).format(0);
    return true;
  } catch {
    return false;
  }
}

/** Schedule API instants are UTC even when older responses omit their offset. */
export function scheduleInstant(value: string | null | undefined, locale: string, timezone: string): string {
  if (!value) return '—';
  const utc = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
  const date = new Date(utc);
  if (!Number.isFinite(date.getTime())) return '—';
  return new Intl.DateTimeFormat(locale, {
    timeZone: validScheduleTimezone(timezone) ? timezone.trim() : 'UTC',
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}
