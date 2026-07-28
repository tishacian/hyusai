/**
 * NAWA WE — the handling of a request, read back as the exchange it was.
 *
 * Pure, framework-free logic, exercised against captured traces
 * (`nawa-conversation.spec.ts`).
 *
 * The rule this module exists to enforce: a bubble may state nothing the run
 * did not produce. The requester's words come from the System settings, and
 * every assistant line carries a value read out of `run.output_ref` or out of a
 * checkpoint the walker emitted. Exactly two sentences are authored here — the
 * acknowledgement and the fallback gate line — and neither claims an outcome.
 *
 * No key is read generically, only by name, which is what keeps `diagnostic_*`
 * out by construction: those values name a technical component of our own
 * platform rather than the customer's directory (see `isTraceOnlyOutputKey`),
 * and they belong to the execution journal and the run trace.
 *
 * `output_ref` is written once, when the run settles, so during the run only
 * the lines backed by checkpoints can appear — the requester, the
 * acknowledgement, and the human gate. That is a property of the walker, not a
 * choice made here: claiming a step from a `node_end` alone would be claiming a
 * result the node never reported.
 */
import { formatClock } from './nawa-inbound-queue';
import type { NawaScenarioPreset } from './nawa-itsd.model';
import type { Run } from '@app/core/canonical-api.service';

export type NawaMessageAuthor = 'requester' | 'assistant';

export interface NawaMessage {
  author: NawaMessageAuthor;
  text: string;
  /** Clock reading of the checkpoint that produced the line, when there is one. */
  at?: string;
}

/** The acknowledgement. States that the request is being handled, nothing else. */
export const NAWA_ACK = 'Request received. I’m looking at it now.';

/** Used only when the paused gate carried no prompt of its own. */
export const NAWA_GATE_FALLBACK =
  'This request needs a human decision before anything is changed.';

interface Checkpoint {
  kind?: string;
  t?: string;
  node_id?: string;
  prompt?: string;
  decision_status?: string;
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** `2026-07-28T11:47:13.4` → `11:47`. */
function clockOf(t: string | undefined): string | undefined {
  return t && t.length >= 16 ? t.slice(11, 16) : undefined;
}

function lastOfKind(checkpoints: Checkpoint[], kind: string): Checkpoint | null {
  for (let index = checkpoints.length - 1; index >= 0; index -= 1) {
    if (checkpoints[index].kind === kind) return checkpoints[index];
  }
  return null;
}

/**
 * When the node behind a value reported its end. Substring matching, as in the
 * step projection: the fragments below must never capture a bench node
 * (`task.case_*`) or the timestamps would come from the case injector.
 */
function endedAt(checkpoints: Checkpoint[], fragment: string): string | undefined {
  for (let index = checkpoints.length - 1; index >= 0; index -= 1) {
    const raw = checkpoints[index];
    if (raw.kind === 'node_end' && (raw.node_id || '').includes(fragment)) {
      return clockOf(raw.t);
    }
  }
  return undefined;
}

function ticketLine(id: string | null, state: string | null): string | null {
  if (id && state) return `Ticket ${id} — state: ${state}.`;
  if (id) return `Ticket ${id}.`;
  if (state) return `Ticket state: ${state}.`;
  return null;
}

/**
 * Project a run onto the conversation between the requester and WE.
 *
 * `preset` supplies the requester's own words; everything else comes from the
 * run. Both may be absent — a queue selection with no run yet renders the
 * request alone, and a System installed before the presets were authored
 * renders the assistant side alone.
 */
export function projectConversation(
  run: Run | null,
  preset: NawaScenarioPreset | null,
): NawaMessage[] {
  const output = (run?.output_ref ?? {}) as Record<string, unknown>;
  const checkpoints = (run?.checkpoints ?? []) as Checkpoint[];
  const messages: NawaMessage[] = [];
  const startedAt = clockOf(lastOfKind(checkpoints, 'run_start')?.t);

  const request = text(preset?.request_text) ?? text(output['request_text']);
  if (request) {
    messages.push({
      author: 'requester',
      text: request,
      at: formatClock(preset?.received_at) ?? startedAt,
    });
  }
  if (!run) return messages;

  messages.push({ author: 'assistant', text: NAWA_ACK, at: startedAt });

  const intent = text(output['detected_intent']);
  if (intent) {
    messages.push({
      author: 'assistant',
      text: `Request classified — detected intent: ${intent}.`,
      at: endedAt(checkpoints, 'classify_intent'),
    });
  }

  // The verdict is the assessment's own single line, token first. Quoted as it
  // was produced: a summary of it would be our claim rather than the model's.
  const verdict = text(output['identity_verdict']);
  if (verdict) {
    const filed = output['evidence_on_file'];
    const evidence = typeof filed === 'number' ? ` Evidence items on file: ${filed}.` : '';
    messages.push({
      author: 'assistant',
      text: `Identity check — ${verdict}${evidence}`,
      at: endedAt(checkpoints, 'verify_identity'),
    });
  }

  const pause = lastOfKind(checkpoints, 'hitl_pause');
  if (pause) {
    messages.push({
      author: 'assistant',
      text: text(pause.prompt) ?? NAWA_GATE_FALLBACK,
      at: clockOf(pause.t),
    });
  }

  const resume = lastOfKind(checkpoints, 'hitl_resume');
  if (resume) {
    const status = text(resume.decision_status);
    messages.push({
      author: 'assistant',
      text: status
        ? `Human decision recorded: ${status}. Continuing.`
        : 'Human decision recorded. Continuing.',
      at: clockOf(resume.t),
    });
  }

  const directory = record(output['directory_action']);
  if (directory) {
    const parts = [
      text(directory['operation']),
      text(directory['mode']),
      text(directory['result']),
    ].filter((part): part is string => part !== null);
    if (parts.length) {
      messages.push({
        author: 'assistant',
        text: `Directory action — ${parts.join(' · ')}.`,
        at: endedAt(checkpoints, 'ad_reset'),
      });
    }
  }

  const temporary = text(output['temporary_password_issued']);
  if (temporary) {
    messages.push({
      author: 'assistant',
      text: `Temporary password issued: ${temporary}.`,
      at: endedAt(checkpoints, 'temporary_credential'),
    });
  }

  // The message the model actually drafted for the requester, in EN/AR. It is
  // the one line of the exchange that was written for them, so it is quoted in
  // full and never trimmed.
  const notice = text(output['user_message']);
  if (notice) {
    messages.push({
      author: 'assistant',
      text: notice,
      at: endedAt(checkpoints, 'draft_user_notice'),
    });
  }

  const ticket = record(output['ticket']);
  if (ticket) {
    const id = text(ticket['id']);
    const state = text(ticket['state']);
    const line = ticketLine(id, state);
    if (line) {
      messages.push({ author: 'assistant', text: line, at: endedAt(checkpoints, 'close_ticket') });
    }
  }

  // On the lanes where no message was drafted for the requester — routed
  // elsewhere, directory incident, quality hold — the flow's own outcome
  // wording closes the exchange. It is authored and test-locked backend side.
  const closing = text(record(output['outcome'])?.['message']);
  if (closing && !notice) {
    messages.push({
      author: 'assistant',
      text: closing,
      at: clockOf(lastOfKind(checkpoints, 'run_end')?.t),
    });
  }

  return messages;
}
