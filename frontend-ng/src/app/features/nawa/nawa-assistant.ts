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
  /** The passage the answer leaned on, trimmed of the retrieval prefix. */
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

/**
 * Retrieval hands back passages prefixed with their own framing
 * (`Parent context:\n<heading>\n\n…`). The heading is useful, the label is not.
 *
 * Nothing here rewrites the evidence: the leading lines that are dropped are the
 * document's own identification, and the tail that is dropped is marked with an
 * ellipsis. What remains is verbatim.
 */
export function cleanPassage(snippet: string | null | undefined): string {
  const lines = String(snippet ?? '')
    .replace(/^\s*parent context\s*:\s*/i, '')
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => !!line);

  while (lines.length > 1 && isFrontMatter(lines[0])) lines.shift();

  const text = lines.join(' ').replace(/\s{2,}/g, ' ').trim();
  if (text.length <= PASSAGE_CHARS) return text;
  const cut = text.slice(0, PASSAGE_CHARS);
  const lastSpace = cut.lastIndexOf(' ');
  return `${(lastSpace > PASSAGE_CHARS * 0.6 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
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
      passage: cleanPassage(source.snippet),
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
