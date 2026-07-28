/**
 * NAWA WE — projection of one assistant turn.
 *
 * The chat endpoint answers with a body built for the cockpit: reasoning trace,
 * retrieval plan, latency budgets, and a `sources` array whose order is what the
 * `[n]` markers inside the answer refer to. A service desk screen shows almost
 * none of that. This module keeps the arithmetic and the naming out of the
 * component so both can be tested without a browser.
 *
 * Two decisions are worth stating because they are not obvious:
 *
 * - Sources are NOT deduplicated by document. Two passages of the same policy
 *   are two citations, and collapsing them would renumber the list out of step
 *   with the `[n]` markers the model wrote into its own sentence.
 * - An answer with zero sources is a first-class outcome, not an error. It is
 *   what the assistant is supposed to produce for a question the service desk
 *   library does not cover, and the screen says so plainly rather than showing
 *   an empty list.
 */

/** One entry of the chat endpoint's `sources` array, narrowed to what we show. */
export interface AssistantSourcePayload {
  filename?: string | null;
  title?: string | null;
  snippet?: string | null;
  relevance_score?: number | null;
  collection?: string | null;
  /**
   * The published policy this source names, as served from the app's own assets.
   * Filled in by the service after the answer arrives — the chat endpoint sends
   * only a 200-character snippet of the document's opening.
   */
  document_text?: string | null;
}

/** The subset of `POST /chat/completion` this screen reads. */
export interface AssistantAnswerPayload {
  content?: string | null;
  answer?: string | null;
  sources?: AssistantSourcePayload[] | null;
  duration_ms?: number | null;
  retrieval_elapsed_ms?: number | null;
}

export interface AssistantCitation {
  /** 1-based, matching the `[n]` marker in the answer text. */
  index: number;
  /** Document title, readable — not the file name. */
  document: string;
  /**
   * The window of the retrieved passage that carries what the answer asserts —
   * verbatim, with an ellipsis at whichever end was cut.
   */
  passage: string;
}

export interface AssistantTurn {
  question: string;
  answer: string;
  citations: AssistantCitation[];
  /** Wall-clock of the exchange, as the screen phrases it (`3.1 s`, `840 ms`). */
  elapsed: string;
  /** True when nothing in the library supported an answer. */
  unsupported: boolean;
}

/**
 * Questions the desk actually receives, ordered so a demonstration walks from a
 * precise figure to a refusal. The third one matters most: it is the policy the
 * password-reset agent enforces, asked in words, so the assistant and the
 * automation can be seen quoting the same source.
 */
export const SUGGESTED_QUESTIONS: readonly string[] = [
  'How many failed sign-ins lock an account, and how long does it stay locked?',
  'I lost the phone with my authenticator app on it. What happens now?',
  'What identity evidence do you need before you reset a password?',
  'Can my line manager collect my temporary password for me?',
  'What is the response target for a priority 2 ticket?',
  'I am travelling to a restricted country next week. What do I need from IT?',
];

/** `password-and-account-policy.md` → `Password and Account Policy`. */
export function documentTitle(filename: string | null | undefined): string {
  const base = String(filename ?? '')
    .replace(/^.*\//, '')
    .replace(/\.[a-z0-9]+$/i, '')
    .replace(/[-_]+/g, ' ')
    .trim();
  if (!base) return 'Service desk library';
  // Title case, minus the words a title keeps in lower case.
  const small = new Set(['and', 'or', 'of', 'the', 'for', 'to', 'a', 'an', 'in', 'on']);
  return base
    .split(/\s+/)
    .map((word, position) =>
      position > 0 && small.has(word.toLowerCase())
        ? word.toLowerCase()
        : word.charAt(0).toUpperCase() + word.slice(1),
    )
    .join(' ');
}

/** Longest passage shown under an answer before it is cut at a word. */
const PASSAGE_CHARS = 300;

/**
 * A line that identifies the document rather than saying anything: the markdown
 * title, and the `Owner / Version / Effective / Applies to` block every policy
 * in the library carries. The first chunk of a document always opens with them,
 * so a citation of that chunk would otherwise quote a masthead as its evidence.
 */
function isFrontMatter(line: string): boolean {
  return (
    line.startsWith('#') ||
    /^(document owner|owner|version|effective|applies to|sample content)\b/i.test(line)
  );
}

/** Words too common to indicate that two texts are about the same thing. */
const STOP_WORDS = new Set([
  'that', 'this', 'with', 'from', 'they', 'them', 'their', 'have', 'been', 'will',
  'must', 'your', 'you', 'and', 'the', 'for', 'not', 'any', 'are', 'may', 'can',
  'when', 'what', 'which', 'shall', 'should', 'about', 'into', 'other', 'than',
  'then', 'also', 'only', 'each', 'both', 'does', 'done', 'over', 'more', 'most',
]);

function contentWords(text: string): Set<string> {
  const words = String(text ?? '')
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((word) => word.length >= 4 && !STOP_WORDS.has(word));
  return new Set(words);
}

/** Verbatim sentences. Splits after `.`/`?`/`!`, and after a list item's break. */
function sentences(text: string): string[] {
  return text
    .split(/(?<=[.?!])\s+|(?=\s[-•]\s)/)
    .map((part) => part.trim())
    .filter((part) => !!part);
}

function truncateAtWord(text: string): string {
  if (text.length <= PASSAGE_CHARS) return text;
  const cut = text.slice(0, PASSAGE_CHARS);
  const lastSpace = cut.lastIndexOf(' ');
  return `${(lastSpace > PASSAGE_CHARS * 0.6 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}

/**
 * Retrieval hands back passages prefixed with their own framing
 * (`Parent context:\n<heading>\n\n…`). The heading is useful, the label is not.
 *
 * A chunk is far longer than what fits under an answer, and its opening
 * sentences are usually not the ones the answer rests on — a question about who
 * may collect a temporary password retrieves the password policy, whose chunk
 * opens on character-length requirements. Showing that opening as the evidence
 * invites the one objection this screen exists to prevent: your citation does
 * not say that. So when the answer is known, the window shown is the sentence of
 * the passage that shares the most vocabulary with it, plus its neighbours.
 *
 * Nothing here rewrites the evidence. The document's own identification is
 * dropped, and everything elided is marked with an ellipsis, at whichever end it
 * was cut. What remains is verbatim and contiguous, so the reader can check it
 * against the source document.
 */
/**
 * Words a sentence must share with the answer before it counts as the one the
 * answer rests on. One is noise: asked about the canteen closing at four, the
 * password policy matches on "four", from "three of the four following groups",
 * and a window built on that reads as evidence while being a coincidence.
 */
const MIN_OVERLAP = 2;

/**
 * The stretch of `text` that shares the most vocabulary with `answer`: the
 * best-scoring sentence plus as many neighbours as the budget allows, forward
 * first because the sentence that qualifies a rule usually follows it.
 *
 * Returns null when nothing clears `MIN_OVERLAP` — a window picked on noise
 * would be worse than none, and each caller has its own better fallback.
 */
function supportingWindow(text: string, answer: string): string | null {
  const want = contentWords(answer);
  const parts = sentences(text);
  if (!want.size || parts.length < 2) return null;

  let best = -1;
  let bestScore = MIN_OVERLAP - 1;
  parts.forEach((part, position) => {
    let score = 0;
    contentWords(part).forEach((word) => {
      if (want.has(word)) score += 1;
    });
    // Strictly greater: on a tie the earlier sentence wins, so a text whose
    // opening does support the answer is still shown from its opening.
    if (score > bestScore) {
      bestScore = score;
      best = position;
    }
  });
  if (best < 0) return null;

  let first = best;
  let last = best;
  let length = parts[best].length;
  for (let grew = true; grew; ) {
    grew = false;
    if (last + 1 < parts.length && length + parts[last + 1].length + 1 <= PASSAGE_CHARS) {
      length += parts[++last].length + 1;
      grew = true;
    }
    if (first > 0 && length + parts[first - 1].length + 1 <= PASSAGE_CHARS) {
      length += parts[--first].length + 1;
      grew = true;
    }
  }

  const window = truncateAtWord(parts.slice(first, last + 1).join(' '));
  const opened = first > 0 ? `…${window}` : window;
  return last < parts.length - 1 && !opened.endsWith('…') ? `${opened}…` : opened;
}

export function cleanPassage(snippet: string | null | undefined, answer?: string): string {
  const lines = String(snippet ?? '')
    .replace(/^\s*parent context\s*:\s*/i, '')
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => !!line);

  while (lines.length > 1 && isFrontMatter(lines[0])) lines.shift();

  const text = lines.join(' ').replace(/\s{2,}/g, ' ').trim();
  if (text.length <= PASSAGE_CHARS) return text;
  // Nothing in it echoes the answer: no window is better founded than the
  // passage's own beginning, which is at least where the document starts.
  return supportingWindow(text, answer ?? '') ?? truncateAtWord(text);
}

/**
 * The published policy, as prose: markdown headings and the document-control
 * block identify the file rather than saying anything, and a window that opened
 * on either would read as evidence without being any.
 */
function plainText(markdown: string | null | undefined): string {
  return String(markdown ?? '')
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => !!line && !line.startsWith('#') && !isFrontMatter(line))
    .join(' ')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

/**
 * Where in the published policy the answer is supported.
 *
 * The retrieval's own snippet cannot serve here: the platform returns the
 * parent context of the matched chunk, cut at 200 characters server side, so the
 * sentence carrying a rule stated further down the section never arrives. What
 * the retrieval does establish — which document answers the question — is what
 * this uses, then locates the supporting sentence in the policy the front end
 * serves from its own assets. That file IS the file that was indexed, so the
 * excerpt is verbatim from the document the customer can open.
 *
 * Returns an empty string when the policy says nothing the answer echoes: the
 * caller then falls back to the retrieval's snippet rather than to a guess.
 */
export function excerptFromDocument(
  markdown: string | null | undefined,
  answer: string,
): string {
  const text = plainText(markdown);
  if (!text) return '';
  if (text.length <= PASSAGE_CHARS) return text;
  return supportingWindow(text, answer) ?? '';
}

/** `3113` → `3.1 s`; `840` → `840 ms`. Same rule as the run journal. */
export function elapsedLabel(ms: number | null | undefined): string {
  const value = Number(ms);
  if (!Number.isFinite(value) || value <= 0) return '';
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
}

export function projectTurn(
  question: string,
  payload: AssistantAnswerPayload | null,
  fallbackElapsedMs?: number,
): AssistantTurn {
  const answer = String(payload?.content ?? payload?.answer ?? '').trim();
  const citations = (payload?.sources ?? [])
    .filter((source): source is AssistantSourcePayload => !!source)
    .map((source, position) => ({
      index: position + 1,
      document: documentTitle(source.filename ?? source.title),
      passage:
        excerptFromDocument(source.document_text, answer) || cleanPassage(source.snippet, answer),
    }))
    .filter((citation) => !!citation.passage);

  return {
    question,
    answer,
    citations,
    elapsed: elapsedLabel(payload?.duration_ms ?? fallbackElapsedMs),
    unsupported: citations.length === 0,
  };
}
