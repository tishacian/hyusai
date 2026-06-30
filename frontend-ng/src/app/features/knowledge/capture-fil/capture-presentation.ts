import type {
  CaptureIndexStatus,
  CapturePinnedView,
  CaptureProposal,
  CaptureReportSource,
  CaptureReportStructureNode,
  CaptureShareLevel,
  CaptureSessionDocument,
  CaptureViewReference,
  ProposalFact,
  ProposalOpenQuestion,
} from '@app/core/api.service';

/**
 * Shared, framework-free presentation helpers for the cockpit "Le Fil" capture
 * experience (Phases 2-6). Keeps tints / labels / clock formatting consistent
 * across the session, scene, anchors, triage and report surfaces so the disjoint
 * components never drift. No Angular here — pure functions only.
 */

/** The five piece tints the hifi design assigns per document (D3/D5). */
export type CaptureTone = 'cool' | 'violet' | 'warn' | 'pos' | 'neg';

const TONE_ORDER: CaptureTone[] = ['cool', 'violet', 'pos', 'warn', 'neg'];

/** Resolve a tone to its cockpit signal CSS variable. */
export function toneVar(tone: CaptureTone): string {
  return `var(--ck-signal-${tone})`;
}

/** A stable, document-scoped tint so the same piece always reads the same colour. */
export function toneFor(seed: string | null | undefined): CaptureTone {
  const key = (seed ?? '').trim();
  if (!key) return 'cool';
  let hash = 0;
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) | 0;
  return TONE_ORDER[Math.abs(hash) % TONE_ORDER.length];
}

/** Stable identity for a view reference / pinned piece (doc + page/slide/image). */
export function refKey(ref: CaptureViewReference | CapturePinnedView): string {
  const doc = ('document_id' in ref ? ref.document_id : null) ?? ref.filename ?? ref.title ?? 'view';
  const loc = ref.page ?? ref.slide ?? ref.image_index ?? '';
  return `${doc}#${loc}`;
}

/** Deterministic tint for a view reference / pinned piece. */
export function viewTone(ref: CaptureViewReference | CapturePinnedView): CaptureTone {
  return toneFor(ref.document_id ?? ref.filename ?? ref.title ?? null);
}

/** Human label for a piece — prefers the captured statement, else the doc title. */
export function viewLabel(ref: CaptureViewReference | CapturePinnedView): string {
  if ('statement' in ref && ref.statement) return ref.statement;
  if ('trigger_phrase' in ref && ref.trigger_phrase) return ref.trigger_phrase;
  return ref.title ?? cleanFilename(ref.filename) ?? 'Pièce';
}

/** Short title used as the piece caption (always the document side, not the phrase). */
export function viewTitle(ref: CaptureViewReference | CapturePinnedView): string {
  return ref.title ?? cleanFilename(ref.filename) ?? 'Pièce';
}

/** Locator badge: `p.12`, `cliché 3`, `slide 4` or `IMG`. */
export function viewLocation(ref: CaptureViewReference | CapturePinnedView): string {
  if (ref.page != null) return `p.${ref.page}`;
  if (ref.slide != null) return `slide ${ref.slide}`;
  if (ref.image_index != null) return `cliché ${ref.image_index}`;
  return 'IMG';
}

/** Strip the extension off a document filename for compact display. */
export function cleanFilename(filename: string | null | undefined): string | null {
  if (!filename) return null;
  return filename.replace(/\.(pdf|zip|docx?|pptx?|xlsx?|png|jpe?g|gif|webp)$/i, '');
}

/** `HH:MM:SS` from an epoch millisecond timestamp (tabular clock in Le Fil). */
export function clockLabel(tsMs: number | null | undefined): string {
  const d = new Date(tsMs ?? Date.now());
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** Map a journaled anchor (view reference) into a pinnable scene piece. */
export function refToPinnedView(ref: CaptureViewReference): CapturePinnedView {
  return {
    key: refKey(ref),
    document_id: ref.document_id ?? null,
    collection: null,
    filename: ref.filename ?? null,
    title: ref.title ?? null,
    page: ref.page ?? null,
    slide: ref.slide ?? null,
    image_index: ref.image_index ?? null,
    association_mode: 'active_view',
  };
}

/** Build a session document into a scene piece (used when pinning from the doc list). */
export function documentToPinnedView(doc: CaptureSessionDocument, page?: number | null): CapturePinnedView {
  return {
    key: `${doc.document_id ?? doc.filename ?? 'doc'}#${page ?? ''}`,
    document_id: doc.document_id ?? null,
    collection: doc.collection ?? doc.collection_name ?? null,
    filename: doc.filename ?? null,
    title: doc.title ?? doc.filename ?? null,
    page: page ?? null,
    slide: null,
    image_index: null,
    association_mode: 'active_view',
  };
}

/** Background-index lifecycle display (D5 / §5.4). */
export const INDEX_STATE_DISPLAY: Record<
  CaptureIndexStatus,
  { label: string; tone: CaptureTone | 'neutral' }
> = {
  not_indexed: { label: 'Non indexé', tone: 'neutral' },
  referenced: { label: 'Référencé', tone: 'cool' },
  queued: { label: 'En file', tone: 'warn' },
  indexed: { label: 'Indexé', tone: 'pos' },
  failed: { label: 'Échec', tone: 'neg' },
};

/** Normalise any raw index status to the known lifecycle enum. */
export function indexStatusOf(doc: CaptureSessionDocument): CaptureIndexStatus {
  const raw = String(doc.index_status ?? '').trim();
  if (raw === 'referenced' || raw === 'queued' || raw === 'indexed' || raw === 'failed') return raw;
  return 'not_indexed';
}

/** Share-level triage display (D5 / §5.3). */
export const SHARE_LEVEL_DISPLAY: Record<CaptureShareLevel, { label: string; tone: CaptureTone | 'neutral' }> = {
  full: { label: 'Entier', tone: 'pos' },
  excerpt: { label: 'Extrait', tone: 'cool' },
  none: { label: 'Aucun', tone: 'neutral' },
};

/** Tone (incl. neutral) → CSS colour, with `--ck-fg-4` for neutral. */
export function paletteVar(tone: CaptureTone | 'neutral'): string {
  return tone === 'neutral' ? 'var(--ck-fg-4)' : `var(--ck-signal-${tone})`;
}

// ---------------------------------------------------------------------------
// Structured report fiche (P0 #2) — ported from the v0 monolith
// (knowledge-capture.component.ts buildReportFiche / parseReportBlocks). The
// fiche renders the FINAL proposal's plan_structure (topics → sous-sujets →
// synthèses/faits) so the review surface mirrors the rich v0 rendering while
// markdown stays the canonical storage format. Framework-free, pure functions.
// ---------------------------------------------------------------------------

/** A leaf in a parsed bullet list (supports nested children). */
export interface ReportListItem {
  text: string;
  children: ReportListItem[];
}

/** A parsed block of a section synthesis (markdown stored, structured render). */
export interface ReportBlock {
  kind: 'paragraph' | 'list' | 'heading';
  text?: string;
  items?: ReportListItem[];
}

/** A rendered fiche node (topic or sous-sujet). Keeps full facts so the UI can
 * wire inline provenance markers against journaled anchors. */
export interface ReportSubsectionCard {
  key: string;
  title: string;
  blocks: ReportBlock[];
  facts: ProposalFact[];
  sources: CaptureReportSource[];
  openQuestions: string[];
}

/** A top-level fiche section (topic) with optional sous-sujets. */
export interface ReportSectionCard extends ReportSubsectionCard {
  index: number;
  subsections: ReportSubsectionCard[];
}

/** Plain text of a fact, preferring its amended text then statement. */
export function reportFactText(fact: ProposalFact): string {
  return String(fact.text || fact.statement || '').trim();
}

/** Build the structured fiche from a proposal's `plan_structure`. */
export function buildReportFiche(proposal: CaptureProposal | null): ReportSectionCard[] {
  const topics = proposal?.proposal?.plan_structure?.topics || [];
  const cards: ReportSectionCard[] = [];
  for (const topic of topics) {
    const subsections: ReportSubsectionCard[] = [];
    for (const subtopic of topic.subtopics || []) {
      const sub = buildReportNode(
        `${topic.topic_id || cards.length}:${subtopic.subtopic_id || subsections.length}`,
        subtopic,
      );
      if (sub.blocks.length || sub.facts.length || sub.sources.length || sub.openQuestions.length) {
        subsections.push(sub);
      }
    }
    const node = buildReportNode(String(topic.topic_id || cards.length), topic);
    if (!node.blocks.length && !node.facts.length && !subsections.length) continue;
    cards.push({ ...node, index: cards.length + 1, subsections });
  }
  return cards;
}

function buildReportNode(key: string, node: CaptureReportStructureNode): ReportSubsectionCard {
  const synthesis = String(node.synthesis || '').trim();
  // When a synthesis exists it already weaves the facts in prose; otherwise we
  // surface the raw captured facts as bullets.
  const facts = synthesis ? [] : (node.facts || []).filter((f) => Boolean(reportFactText(f)));
  return {
    key,
    title: String(node.title || 'Section').trim(),
    blocks: parseReportBlocks(synthesis),
    facts,
    sources: (node.sources || []).filter((src) => Boolean(src)),
    openQuestions: reportOpenQuestionLabels(node.open_questions || []),
  };
}

function reportOpenQuestionLabels(questions: ProposalOpenQuestion[]): string[] {
  return questions
    .filter((q) => !['answered', 'invalid', 'dismissed'].includes(String(q.status || 'open').toLowerCase()))
    .map((q) =>
      String(
        (q as Record<string, unknown>)['text'] || q.follow_up || q.reason || '',
      ).trim(),
    )
    .filter((text) => Boolean(text));
}

/** Facts captured outside any plan topic (rendered in a trailing "Hors plan"). */
export function reportUnassignedFacts(proposal: CaptureProposal | null): string[] {
  return (proposal?.proposal?.plan_structure?.unassigned || [])
    .map(reportFactText)
    .filter((text) => Boolean(text));
}

/** Compact label for a section-level KB source (title · page/slide). */
export function reportSourceLabel(src: CaptureReportSource): string {
  const base = String(src.title || src.filename || src.source || src.document_id || 'Source').trim();
  const slide = coercePage(src.slide);
  if (slide) return `${base} · slide ${slide}`;
  const page = coercePage(src.page ?? src.page_number);
  return page ? `${base} · page ${page}` : base;
}

function coercePage(value: number | string | null | undefined): number | null {
  if (value == null) return null;
  const n = typeof value === 'number' ? value : parseInt(String(value), 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/**
 * Minimal, safe markdown-to-blocks parser for the section syntheses (markdown
 * stays the storage format; rendering is structured). Supports paragraphs,
 * (nested) bullet lists and headings.
 */
export function parseReportBlocks(markdown: string): ReportBlock[] {
  const blocks: ReportBlock[] = [];
  if (!markdown) return blocks;
  let bulletBuffer: Array<{ level: number; text: string }> = [];
  let paragraph: string[] = [];
  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push({ kind: 'paragraph', text: stripInlineMarkdown(paragraph.join(' ')) });
      paragraph = [];
    }
  };
  const flushList = () => {
    if (bulletBuffer.length) {
      blocks.push({ kind: 'list', items: buildReportListTree(bulletBuffer) });
      bulletBuffer = [];
    }
  };
  for (const rawLine of markdown.split('\n')) {
    if (!rawLine.trim()) {
      flushList();
      flushParagraph();
      continue;
    }
    const bullet = parseReportBulletLine(rawLine);
    if (bullet) {
      flushParagraph();
      bulletBuffer.push(bullet);
      continue;
    }
    flushList();
    const trimmed = rawLine.trim();
    const heading = trimmed.match(/^#{1,6}\s+(.*)$/);
    if (heading) {
      flushParagraph();
      blocks.push({ kind: 'heading', text: stripInlineMarkdown(heading[1]) });
      continue;
    }
    if (isReportSubheading(trimmed)) {
      flushParagraph();
      blocks.push({ kind: 'heading', text: stripInlineMarkdown(normalizeReportSubheading(trimmed)) });
      continue;
    }
    paragraph.push(trimmed);
  }
  flushList();
  flushParagraph();
  return blocks;
}

function parseReportBulletLine(rawLine: string): { level: number; text: string } | null {
  const match = rawLine.match(/^([\t ]*)([-*•]|\d+[.)])\s+(.*)$/);
  if (!match) return null;
  const indent = match[1].replace(/\t/g, '  ').length;
  return { level: Math.floor(indent / 2), text: stripInlineMarkdown(match[3]) };
}

function buildReportListTree(flat: Array<{ level: number; text: string }>): ReportListItem[] {
  const root: ReportListItem[] = [];
  const stack: Array<{ level: number; item: ReportListItem }> = [];
  for (const entry of flat) {
    const node: ReportListItem = { text: entry.text, children: [] };
    while (stack.length && stack[stack.length - 1].level >= entry.level) {
      stack.pop();
    }
    if (!stack.length) {
      root.push(node);
    } else {
      stack[stack.length - 1].item.children.push(node);
    }
    stack.push({ level: entry.level, item: node });
  }
  return root;
}

function isReportSubheading(line: string): boolean {
  if (/^\*\*.+\*\*:?\s*$/.test(line)) return true;
  return line.length <= 100 && /:\s*$/.test(line) && !/^https?:\/\//i.test(line);
}

function normalizeReportSubheading(line: string): string {
  const bold = line.match(/^\*\*(.+)\*\*:?\s*$/);
  if (bold) return bold[1].trim();
  return line.replace(/:\s*$/, '').trim();
}

function stripInlineMarkdown(text: string): string {
  return text
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .trim();
}

/** Flatten a (nested) parsed bullet list into depth-tagged rows for rendering
 * without recursive templates. */
export function flattenReportList(
  items: ReportListItem[],
  depth = 0,
): Array<{ text: string; depth: number }> {
  const out: Array<{ text: string; depth: number }> = [];
  for (const item of items) {
    out.push({ text: item.text, depth });
    if (item.children?.length) out.push(...flattenReportList(item.children, depth + 1));
  }
  return out;
}
