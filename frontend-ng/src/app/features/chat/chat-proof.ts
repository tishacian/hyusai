/**
 * L30 — pure helpers behind the overlay's sourced working thread (C2).
 *
 * Kept free of Angular so the rules stay testable without an injector:
 * which steps the work trace shows, which sources count as cited or only
 * read, what the answer's meta line may claim, and which passage sentence the
 * proof highlights. Every value is derived from data the stream really sent;
 * nothing here invents a step or a count.
 */

/** Minimal shape of a streamed `decision_step` the trace needs. */
export interface TraceStepLike {
  type?: string;
  status?: 'pending' | 'active' | 'completed' | 'warning' | 'error';
}

export type TracePhaseKey = 'search' | 'read' | 'compose';
export type TracePhaseStatus = 'done' | 'current' | 'error';

export interface TracePhase {
  key: TracePhaseKey;
  status: TracePhaseStatus;
}

export interface WorkTrace {
  /** Phases that received at least one real event, in pipeline order. */
  phases: TracePhase[];
  /** The phase in progress while streaming, `null` once the answer is done. */
  current: TracePhaseKey | null;
}

const PHASE_ORDER: TracePhaseKey[] = ['search', 'read', 'compose'];

/** Orchestrator step types, grouped into the three phases a reader follows. */
const PHASE_OF_STEP: Record<string, TracePhaseKey> = {
  query_received: 'search',
  query_analysis: 'search',
  query_rewrite: 'search',
  routing: 'search',
  embedding: 'search',
  retrieve: 'search',
  retrieval: 'search',
  context_filtering: 'read',
  rerank: 'read',
  reranking: 'read',
  thought: 'read',
  validation: 'read',
  synthesis: 'compose',
  generation: 'compose',
};

export function tracePhaseOf(stepType: string | undefined | null): TracePhaseKey | null {
  if (!stepType) return null;
  return PHASE_OF_STEP[stepType] ?? null;
}

/**
 * Derive the trace from the real step events. A phase appears only when a
 * step of that phase was emitted (the answer text itself counts for
 * « Rédaction », since tokens are a real event). While streaming, the latest
 * phase is current and the earlier ones are done; once finished, every phase
 * is done unless one of its steps failed.
 */
export function deriveWorkTrace(
  steps: readonly TraceStepLike[] | null | undefined,
  options: { streaming: boolean; textStarted?: boolean },
): WorkTrace {
  const seen = new Set<TracePhaseKey>();
  const failed = new Set<TracePhaseKey>();
  for (const step of steps ?? []) {
    const phase = tracePhaseOf(step.type);
    if (!phase) continue;
    seen.add(phase);
    if (step.status === 'error') failed.add(phase);
  }
  if (options.textStarted) seen.add('compose');
  const present = PHASE_ORDER.filter((key) => seen.has(key));
  const current = options.streaming && present.length ? present[present.length - 1] : null;
  return {
    phases: present.map((key) => ({
      key,
      status: failed.has(key) ? 'error' : key === current ? 'current' : 'done',
    })),
    current,
  };
}

export interface NumberedSource<S> {
  /** 1-based index, the number the answer cites. */
  n: number;
  source: S;
}

export interface ProofGroups<S> {
  cited: NumberedSource<S>[];
  readNotCited: NumberedSource<S>[];
}

/** Split the passages given to the model into cited ones and read-only ones. */
export function classifyProofSources<S>(
  sources: readonly S[] | null | undefined,
  cited: ReadonlySet<number>,
): ProofGroups<S> {
  const groups: ProofGroups<S> = { cited: [], readNotCited: [] };
  (sources ?? []).forEach((source, index) => {
    const entry = { n: index + 1, source };
    (cited.has(index + 1) ? groups.cited : groups.readNotCited).push(entry);
  });
  return groups;
}

/**
 * Counts the answer's meta line may claim. `passages` is the number of
 * passages the model received; `cited` only counts citations that resolve to
 * one of them. Without sources there is nothing to claim: `null`.
 */
export function answerProofCounts(
  sources: readonly unknown[] | null | undefined,
  cited: ReadonlySet<number>,
): { passages: number; cited: number } | null {
  const passages = sources?.length ?? 0;
  if (!passages) return null;
  let count = 0;
  for (const n of cited) if (n >= 1 && n <= passages) count++;
  return { passages, cited: count };
}

/**
 * Builders keep the model and retrieval controls where they are today; every
 * other mode finds them behind « Avancé » in the composer.
 */
export function advancedBehindComposer(threadMode: boolean, workspaceMode: string | null | undefined): boolean {
  return threadMode && workspaceMode !== 'builder';
}

export interface ProofSelection {
  msgId: string;
  hostId: string;
  n: number;
}

export interface ProofRailState {
  selection: ProofSelection | null;
  /** True only when a pointer opened the rail: keyboard actions never animate. */
  animate: boolean;
}

export type ProofRailAction =
  | { kind: 'open'; selection: ProofSelection; byPointer: boolean; valid: boolean }
  | { kind: 'close' };

/** Rail state machine: an invalid citation leaves the rail as it was. */
export function reduceProofRail(state: ProofRailState, action: ProofRailAction): ProofRailState {
  if (action.kind === 'close') return { selection: null, animate: false };
  if (!action.valid) return state;
  // Switching proof inside an open rail never re-animates the panel.
  const animate = action.byPointer && !state.selection;
  return { selection: action.selection, animate };
}

export interface PassageParts {
  before: string;
  mark: string;
  after: string;
}

const WORD = /[\p{L}\p{N}]{4,}/gu;

function contentWords(text: string): Set<string> {
  return new Set((text.toLocaleLowerCase().match(WORD) ?? []).map((word) => word.normalize('NFD').replace(/\p{M}/gu, '')));
}

/** Sentence pieces that join back to the text; `3.2` is not a boundary. */
function splitSentences(text: string): string[] {
  const pieces: string[] = [];
  const boundary = /[.!?;]+(?=\s|$)|\n/g;
  let last = 0;
  for (let match = boundary.exec(text); match; match = boundary.exec(text)) {
    const end = match.index + match[0].length;
    pieces.push(text.slice(last, end));
    last = end;
  }
  if (last < text.length) pieces.push(text.slice(last));
  return pieces;
}

/**
 * Mark the passage sentence that best supports the claim (shared content
 * words). When no sentence clearly wins, the whole passage is marked: the
 * proof never pretends to a precision it does not have.
 */
export function markSupportingSentence(passage: string, claim: string | null | undefined): PassageParts {
  const text = passage.trim();
  const whole = { before: '', mark: text, after: '' };
  if (!text || !claim?.trim()) return whole;
  const sentences = splitSentences(text);
  if (sentences.filter((sentence) => sentence.trim()).length < 2) return whole;
  const wanted = contentWords(claim);
  let best = -1;
  let bestScore = 0;
  let tie = false;
  sentences.forEach((sentence, index) => {
    let score = 0;
    for (const word of contentWords(sentence)) if (wanted.has(word)) score++;
    if (score > bestScore) { best = index; bestScore = score; tie = false; }
    else if (score === bestScore && score > 0) tie = true;
  });
  if (best < 0 || bestScore < 2 || tie) return whole;
  const start = sentences.slice(0, best).join('').length;
  const sentence = sentences[best];
  const from = start + (sentence.length - sentence.trimStart().length);
  const to = start + sentence.trimEnd().length;
  return { before: text.slice(0, from), mark: text.slice(from, to), after: text.slice(to) };
}
