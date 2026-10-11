/**
 * Rejoining the two gateway events that leave the backend in pieces.
 *
 * A LiveKit reliable data packet is capped at 15 KiB, and two outbound events
 * are larger than that on their own: `assistant.answer` carries a whole turn
 * payload (one `list_services` result alone serializes to 13 098 bytes on the
 * shipped catalogue) and `audio.out` carries a base64 MP3. The gateway therefore
 * frames them exactly as a surface frames the context it pushes inbound —
 * `seq` / `total` / a JSON slice — and this is the other end of that.
 *
 * It lives at the transport boundary, used by both lanes (the LiveKit room and
 * the direct backend WebSocket), so **no surface ever sees a frame**: a
 * subscriber receives the same whole event it received before framing existed.
 * That is deliberate. `audio.out` is shared with Knowledge Capture, and asking
 * every consumer to reassemble would be asking each of them to get it right.
 *
 * Both lanes deliver reliably and in order, so rejoining is a plain append and a
 * gap means the push was interrupted — the same reading the gateway applies to
 * an inbound context.
 */
import type { VoiceSessionEvent } from './voice-session.service';

/** The field a frame carries its slice of the payload in. */
export const OUTBOUND_FRAME_FIELD = 'payload_json';

/** The events the gateway frames on the way out. Everything else passes whole. */
export const OUTBOUND_FRAMED_EVENTS: readonly string[] = Object.freeze([
  'assistant.answer',
  'audio.out',
]);

/**
 * Ceiling on what one event may accumulate before it is abandoned.
 *
 * A minute of synthesized speech is a few hundred kilobytes of base64, so this
 * is generous; it exists so a malformed `total` cannot grow a buffer without
 * end on a live call.
 */
const MAX_FRAMED_CHARS = 4 * 1024 * 1024;

interface Partial {
  total: number;
  parts: string[];
  chars: number;
}

/**
 * One connection's reassembly state.
 *
 * Keyed by event type: the gateway sends one framed payload at a time under its
 * own send lock, but keeping the buffers apart means an answer and its audio
 * could never corrupt one another if that ever stopped being true.
 */
export class VoiceEventReassembler {
  private readonly partials = new Map<string, Partial>();

  /**
   * The event to hand to subscribers, or `null` while frames are still missing.
   *
   * A frame that makes no sense is dropped rather than emitted: half a payload
   * would be rendered as an answer, and a `session.error` invented here would be
   * indistinguishable from one the gateway sent.
   */
  accept(event: VoiceSessionEvent): VoiceSessionEvent | null {
    const type = String(event?.type ?? '');
    if (!OUTBOUND_FRAMED_EVENTS.includes(type)) return event;

    const payload = event.payload ?? {};
    const slice = payload[OUTBOUND_FRAME_FIELD];
    // Not framed at all: an older gateway, or a payload that never needed it.
    // Passing it through keeps a mixed deployment readable.
    if (typeof slice !== 'string') return event;

    const seq = Number(payload['seq']);
    const total = Number(payload['total']);
    if (!Number.isInteger(seq) || !Number.isInteger(total) || total < 1 || seq < 0 || seq >= total) {
      this.partials.delete(type);
      return null;
    }

    const held = seq === 0 ? { total, parts: [], chars: 0 } : this.partials.get(type);
    if (!held || held.total !== total || held.parts.length !== seq) {
      this.partials.delete(type);
      return null;
    }
    held.parts.push(slice);
    held.chars += slice.length;
    if (held.chars > MAX_FRAMED_CHARS) {
      this.partials.delete(type);
      return null;
    }
    if (held.parts.length < total) {
      this.partials.set(type, held);
      return null;
    }

    this.partials.delete(type);
    let whole: unknown;
    try {
      whole = JSON.parse(held.parts.join(''));
    } catch {
      return null;
    }
    if (!whole || typeof whole !== 'object' || Array.isArray(whole)) return null;
    return { ...event, payload: whole as Record<string, unknown> };
  }

  /** Forget every partial payload. Called when the connection goes away. */
  reset(): void {
    this.partials.clear();
  }
}
