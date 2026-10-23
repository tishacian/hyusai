/**
 * One way to show an instant across Agentium: in the reader's locale and
 * time zone, with the zone named, never as raw ISO. Engine timestamps without
 * an offset are UTC; they are read as such so two screens never disagree by
 * the reader's offset.
 */
export function parseInstant(value: string | null | undefined): number | null {
  if (!value) return null;
  const normalized = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(value) ? `${value}Z` : value;
  const time = Date.parse(normalized);
  return Number.isFinite(time) ? time : null;
}

export interface FormatInstantOptions {
  /** Include seconds, for evidence where order within a minute matters. */
  seconds?: boolean;
  /** IANA zone to render in; defaults to the reader's. */
  timeZone?: string;
}

export function formatInstant(
  value: string | null | undefined,
  locale: string,
  options: FormatInstantOptions = {},
): string | null {
  const time = parseInstant(value);
  if (time === null) return null;
  // dateStyle/timeStyle cannot be combined with timeZoneName: spell the parts.
  return new Date(time).toLocaleString(locale, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', ...(options.seconds ? { second: '2-digit' } : {}),
    timeZoneName: 'short', ...(options.timeZone ? { timeZone: options.timeZone } : {}),
  });
}
