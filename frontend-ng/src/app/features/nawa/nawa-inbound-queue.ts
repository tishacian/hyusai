/**
 * NAWA WE — the requests waiting at the service desk.
 *
 * Pure, framework-free logic, exercised by `nawa-inbound-queue.spec.ts`.
 *
 * A queue row is a ticket, so it is built from the System settings only. The
 * catalogue entry behind it (`label`, `proves`) names a test case and must
 * never reach a row — that vocabulary is what made the page read as a bench.
 *
 * Every settings field is optional and none is ever substituted: a missing
 * arrival time or reference is rendered as nothing at all, because a fabricated
 * one would contradict the reference the run itself reports at closure.
 */
import type { NawaScenario, NawaScenarioPreset } from './nawa-itsd.model';

/** One ticket in the queue, already reduced to what a row shows. */
export interface NawaInboundRequest {
  /** The catalogue entry this ticket runs. Never rendered. */
  entry: NawaScenario;
  preset: NawaScenarioPreset | null;
  ticketRef: string | null;
  receivedAt: string | null;
  channel: string | null;
  requester: string | null;
  subject: string | null;
}

/**
 * Channels the settings author writes as snake_case identifiers. The generic
 * rule below covers anything absent from this map; the entries exist for the
 * spellings that rule gets wrong ("Walk in", "Email").
 */
const CHANNEL_LABELS: Readonly<Record<string, string>> = {
  email: 'E-mail',
  e_mail: 'E-mail',
  phone_call: 'Phone call',
  phone: 'Phone',
  walk_in: 'Walk-in',
  walk_up: 'Walk-up',
  self_service: 'Self-service',
  service_portal: 'Service portal',
};

/** Longest request excerpt standing in for an unauthored subject. */
const SUBJECT_CHARS = 72;

const ISO_CLOCK = /^\d{4}-\d{2}-\d{2}[T ](\d{2}:\d{2})/;

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

export function humanizeChannel(value: unknown): string | null {
  const raw = text(value);
  if (!raw) return null;
  const key = raw.toLowerCase().replace(/[\s-]+/g, '_');
  const known = CHANNEL_LABELS[key];
  if (known) return known;
  const words = key.replace(/_+/g, ' ').trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : null;
}

/**
 * Clock reading of an arrival time. The settings carry `HH:MM` today and an
 * ISO timestamp is just as plausible from a real queue, so both are accepted
 * and anything else is shown as authored rather than reinterpreted.
 */
export function formatClock(value: unknown): string | null {
  const raw = text(value);
  if (!raw) return null;
  const iso = ISO_CLOCK.exec(raw);
  return iso ? iso[1] : raw;
}

function subjectOf(preset: NawaScenarioPreset | null): string | null {
  const subject = text(preset?.subject);
  if (subject) return subject;
  const request = text(preset?.request_text);
  if (!request) return null;
  return request.length <= SUBJECT_CHARS
    ? request
    : `${request.slice(0, SUBJECT_CHARS).trimEnd()}…`;
}

function presetOf(
  presets: Record<string, unknown>,
  key: string,
): NawaScenarioPreset | null {
  const value = presets[key];
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as NawaScenarioPreset)
    : null;
}

/**
 * Build the queue from the offered catalogue entries and the System settings.
 *
 * An entry carrying `bridge_fallback` is not an inbound ticket: it is the
 * remediation an operator applies to an incident that already happened, and the
 * page offers it from the outcome banner (`outcome.replay_input`) once that
 * incident is on screen. Listing it as a waiting request would announce the
 * failure before it occurred.
 */
export function buildInboundQueue(
  entries: readonly NawaScenario[],
  presets: Record<string, unknown>,
): NawaInboundRequest[] {
  return entries
    .filter((entry) => entry.input?.['bridge_fallback'] !== true)
    .map((entry) => {
      const preset = presetOf(presets, entry.scenario);
      return {
        entry,
        preset,
        ticketRef: text(preset?.ticket_ref),
        receivedAt: formatClock(preset?.received_at),
        channel: humanizeChannel(preset?.channel),
        requester: text(preset?.requester_name),
        subject: subjectOf(preset),
      };
    });
}
