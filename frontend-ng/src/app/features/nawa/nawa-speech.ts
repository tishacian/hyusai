/**
 * What the assistant says out loud, which is not what it puts on screen.
 *
 * Reading a screen aloud is the mistake that makes voice assistants sound like
 * machines. A seven-step joiner procedure is useful as a list and unbearable as
 * speech; a citation marker read as "bracket one" is noise; a wall of policy
 * text spoken in full outlasts the listener's patience long before it outlasts
 * the answer. So the spoken form is a shortened, cleaned version, and the screen
 * keeps the whole thing — the listener hears the answer and reads the detail.
 */

/** Roughly two breaths. Past this, listeners stop tracking and start skimming. */
const SPOKEN_LIMIT = 340;

/**
 * Marks that carry meaning to the eye and none to the ear: markdown emphasis,
 * bullets, and the bracketed source numbers the answer uses for citations.
 */
function stripMarks(text: string): string {
  return text
    .replace(/\[\d+(?:\s*,\s*\d+)*\]/g, '')
    .replace(/[*_`#>]/g, '')
    .replace(/^\s*[-•]\s*/gm, '')
    .replace(/\s+/g, ' ')
    // Removing a marker leaves the space that preceded it stranded before the
    // punctuation that followed.
    .replace(/\s+([,.;:!?])/g, '$1')
    .trim();
}

/**
 * The leading whole sentences that fit in the budget. Cutting mid-sentence is
 * worse than saying less: the voice trails off as though it had crashed.
 */
function leadingSentences(text: string, limit = SPOKEN_LIMIT): string {
  if (text.length <= limit) return text;
  const sentences = text.match(/[^.!?]+[.!?]+(?:\s|$)/g) ?? [];
  let spoken = '';
  for (const sentence of sentences) {
    if ((spoken + sentence).trim().length > limit) break;
    spoken += sentence;
  }
  spoken = spoken.trim();
  if (spoken) return spoken;
  // One very long opening sentence: fall back to a whole-word cut.
  const cut = text.slice(0, limit);
  return `${cut.slice(0, cut.lastIndexOf(' '))}…`;
}

/**
 * An answer from the published library. `supported` is false when the assistant
 * could not search — saying the fallback text aloud is right, because silence
 * would read as a failed microphone rather than a missing answer.
 */
export function spokenAnswer(answer: string, citations = 0): string {
  const clean = stripMarks(answer);
  const body = leadingSentences(clean);
  if (!body) return 'I have no answer for that in the published library.';
  // Compare against the cleaned text: stripping markers shortens the string
  // without dropping anything the listener would have heard.
  if (body.length === clean.length) return body;
  if (citations > 0) return `${body} The full answer and its sources are on screen.`;
  return `${body} The rest is on screen.`;
}

/**
 * A service the desk handles by hand today. The procedure is read as a count,
 * never as a list: the steps are on screen, where they can be followed.
 */
export function spokenService(reply: string, steps: number): string {
  const body = leadingSentences(stripMarks(reply));
  if (steps <= 0) return body;
  const plural = steps > 1 ? 's' : '';
  return `${body} I have put the ${steps} step${plural} of the procedure on screen.`;
}

/**
 * A service that runs here, waiting on the person who asked for it.
 *
 * The assistant does not start it, so what is spoken must not sound as though
 * something is under way — and must not sound as though nothing can be done
 * either. It names the button, because a listener who is not looking at the
 * screen has no other way of knowing there is one.
 */
export function spokenAction(reply: string, service: string): string {
  const body = leadingSentences(stripMarks(reply), 260);
  return (
    `${body} Nothing has started yet. On screen there is a button to run ${service}, `
    + 'with a box for your staff number and authenticator code — it starts when you press it.'
  );
}

/**
 * The outcome of a real run. These are already written for a requester to read,
 * so they are spoken nearly whole — only shortened when a diagnostic tail makes
 * them long.
 */
export function spokenOutcome(outcome: string): string {
  return leadingSentences(stripMarks(outcome), 420);
}
