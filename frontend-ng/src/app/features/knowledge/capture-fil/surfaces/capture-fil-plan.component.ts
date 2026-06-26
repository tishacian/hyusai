import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  EventEmitter,
  Output,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { CaptureEngine, type CaptureSessionInfo } from '../capture-engine';

interface PlanSubtopic {
  id?: string;
  title?: string;
  objective?: string;
  prompt?: string;
  status?: string;
}

interface PlanTopic {
  id?: string;
  title?: string;
  objective?: string;
  prompt?: string;
  status?: string;
  knowledge_refs?: unknown[];
  subtopics?: PlanSubtopic[];
}

interface PlanNotice {
  tone: 'success' | 'error' | 'info';
  text: string;
}

type OutlineAction = 'indent' | 'outdent' | 'renumber' | 'move_up' | 'move_down';

/**
 * Launch surface — builds the plan (with-plan mode) and owns the single,
 * explicit Start. Restores the **v0 hierarchical outline**: topics and
 * subtopics edited as an indented outline (`1.` / `   1.1.`) with indent /
 * outdent / renumber / move controls, plus a **dialogue assistant** that keeps
 * the existing plan as its base ("ajoute telle section" mutates n-1, never
 * restarts from scratch — the current topics are persisted first, then the
 * instruction is applied server-side). Dictation and document import feed the
 * same instruction path.
 *
 * Pieces shown by the expert are uploaded **in-session** (La Scène), not here.
 */
@Component({
  selector: 'app-capture-fil-plan',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent],
  template: `
    <div style="display:flex; flex-direction:column; gap:18px; max-width:840px;">
      <div>
        <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
          Capture · {{ isFree() ? 'Lancement' : 'Plan' }}
        </span>
        <h2 style="margin:6px 0 4px; font-size:22px; font-weight:680; color:var(--ck-fg-1);">{{ title() }}</h2>
        <p style="margin:0; font-size:13.5px; color:var(--ck-fg-3); line-height:1.55; max-width:64ch;">
          {{ objective() }}
        </p>
      </div>

      @if (isFree()) {
        <div class="ck-surface" style="border-radius:var(--ck-radius-lg); padding:18px; display:flex; gap:12px; align-items:flex-start;">
          <ck-glyph name="pulse" [size]="18" color="var(--ck-signal-cool)" />
          <div>
            <div style="font-size:14px; font-weight:600; color:var(--ck-fg-1);">Conversation libre — sans plan</div>
            <div style="font-size:12.5px; color:var(--ck-fg-4); margin-top:3px; line-height:1.5;">
              Aucun plan de sujets. Vous capturerez directement au fil de la parole ; l'oracle structurera les
              éléments utiles. Les pièces s'ajoutent pendant la séance.
            </div>
          </div>
        </div>
      } @else {
        <!-- Hierarchical outline editor (topics + subtopics) -->
        <div class="ck-surface" style="border-radius:var(--ck-radius-lg); padding:18px; display:flex; flex-direction:column; gap:12px;">
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">
              Plan · {{ topics().length }} sujet{{ topics().length > 1 ? 's' : '' }}
            </span>
            <div style="margin-left:auto; display:inline-flex; align-items:center; gap:6px;">
              <button type="button" (click)="applyFormat('outdent')" title="Désindenter (Maj+Tab)" [style]="iconBtn"><ck-glyph name="zoom-out" [size]="13" color="currentColor" /></button>
              <button type="button" (click)="applyFormat('indent')" title="Indenter (Tab) — créer un sous-sujet" [style]="iconBtn"><ck-glyph name="zoom-in" [size]="13" color="currentColor" /></button>
              <button type="button" (click)="applyFormat('renumber')" title="Renuméroter" [style]="iconBtn"><ck-glyph name="ledger" [size]="13" color="currentColor" /></button>
              <button type="button" (click)="applyFormat('move_up')" title="Monter" [style]="iconBtn"><ck-glyph name="arrow-up" [size]="13" color="currentColor" /></button>
              <button type="button" (click)="applyFormat('move_down')" title="Descendre" [style]="iconBtn"><ck-glyph name="arrow-down" [size]="13" color="currentColor" /></button>
            </div>
          </div>

          <textarea
            #outlineEditor
            rows="10"
            [value]="outlineText()"
            (input)="onOutlineInput($any($event.target).value)"
            (keydown)="onOutlineKeydown($event)"
            spellcheck="false"
            placeholder="1. Premier sujet&#10;   1.1. Sous-sujet&#10;2. Deuxième sujet"
            style="resize:vertical; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); color:var(--ck-fg-1); font-family:var(--ck-font-mono); font-size:13px; line-height:1.6; padding:12px 14px; min-height:200px;"
          ></textarea>
          <div class="ck-mono" style="font-size:10.5px; color:var(--ck-fg-5);">
            Tab pour créer un sous-sujet, Maj+Tab pour remonter d'un niveau. La numérotation se met à jour automatiquement.
          </div>
        </div>

        <!-- Dialogue assistant: keeps the current plan as base (n-1) -->
        <div class="ck-surface" style="border-radius:var(--ck-radius-lg); padding:18px; display:flex; flex-direction:column; gap:10px;">
          <div style="display:flex; align-items:center; gap:8px;">
            <ck-glyph name="pulse" [size]="15" color="var(--ck-signal-violet)" />
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">
              Assistant de plan
            </span>
          </div>

          @if (nextPrompt(); as prompt) {
            <div style="font-size:12.5px; color:var(--ck-fg-3); line-height:1.5; padding:8px 12px; border-radius:var(--ck-radius-sm); background:var(--ck-tint-faint); border-left:2px solid var(--ck-signal-violet);">
              {{ prompt }}
            </div>
          }

          <textarea
            rows="3"
            [value]="instruction()"
            (input)="instruction.set($any($event.target).value)"
            [disabled]="dialogueLoading()"
            placeholder="Donnez une instruction (« ajoute une section sur… », « ajoute un sous-sujet à 2 », « reformule… »). Le plan ci-dessus est conservé comme base."
            style="resize:vertical; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); color:var(--ck-fg-1); font-family:var(--ck-font-sans); font-size:14px; line-height:1.5; padding:10px 12px;"
          ></textarea>

          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
            <button
              type="button"
              (click)="toggleDictation()"
              [disabled]="dialogueLoading() || transcribing()"
              [title]="recording() ? 'Arrêter et transcrire la dictée' : 'Dicter une instruction'"
              style="display:inline-flex; align-items:center; gap:7px; padding:8px 12px; border-radius:var(--ck-radius-md); cursor:pointer; font-size:12.5px; background:var(--ck-bg-inset);"
              [style.border]="'1px solid ' + (recording() ? 'var(--ck-signal-neg)' : 'var(--ck-stroke-2)')"
              [style.color]="recording() ? 'var(--ck-signal-neg)' : 'var(--ck-fg-2)'"
            >
              <ck-glyph [name]="recording() ? 'pause' : 'pulse'" [size]="14" color="currentColor" />
              {{ recording() ? 'Arrêter la dictée' : transcribing() ? 'Transcription…' : 'Dicter' }}
            </button>

            <label
              style="display:inline-flex; align-items:center; gap:7px; padding:8px 12px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); cursor:pointer; font-size:12.5px; color:var(--ck-fg-2);"
              [style.opacity]="dialogueLoading() || extracting() ? 0.5 : 1"
              [title]="'Importer un document (notes, plan) : son contenu est appliqué comme instruction, le plan actuel reste la base.'"
            >
              <ck-glyph name="layers" [size]="14" color="currentColor" />
              {{ extracting() ? 'Extraction…' : 'Importer un document' }}
              <input type="file" (change)="onImportInstruction($event)" [disabled]="dialogueLoading() || extracting()" style="display:none;" />
            </label>

            <button
              type="button"
              (click)="submitInstruction()"
              [disabled]="dialogueLoading() || !instruction().trim()"
              style="margin-left:auto; display:inline-flex; align-items:center; gap:7px; padding:8px 14px; border-radius:var(--ck-radius-md); border:none; cursor:pointer; font-size:13px; font-weight:600; background:color-mix(in oklab, var(--ck-signal-violet) 88%, transparent); color:var(--ck-on-signal);"
              [style.opacity]="dialogueLoading() || !instruction().trim() ? 0.5 : 1"
            >
              <ck-glyph name="arrow-right" [size]="13" color="currentColor" />
              {{ dialogueLoading() ? 'Envoi…' : 'Appliquer' }}
            </button>
          </div>

          @if (notice(); as n) {
            <div
              style="font-size:12px; display:flex; align-items:center; gap:7px;"
              [style.color]="n.tone === 'error' ? 'var(--ck-signal-neg)' : n.tone === 'success' ? 'var(--ck-signal-pos)' : 'var(--ck-fg-4)'"
            >
              <ck-glyph [name]="n.tone === 'error' ? 'warn' : 'pulse'" [size]="13" color="currentColor" /> {{ n.text }}
            </div>
          }
        </div>
      }

      @if (error()) {
        <div style="display:flex; align-items:center; gap:8px; color:var(--ck-signal-neg); font-size:12.5px;">
          <ck-glyph name="warn" [size]="14" color="currentColor" /> {{ error() }}
        </div>
      }

      <div>
        <button
          type="button"
          (click)="start()"
          [disabled]="busy() || !sessionId()"
          style="display:inline-flex; align-items:center; gap:7px; padding:11px 18px; border-radius:var(--ck-radius-md); border:none; font-size:14px; font-weight:600; background:color-mix(in oklab, var(--ck-signal-pos) 88%, transparent); color:var(--ck-on-signal);"
          [style.opacity]="busy() || !sessionId() ? 0.5 : 1"
          [style.cursor]="busy() || !sessionId() ? 'not-allowed' : 'pointer'"
        >
          <ck-glyph name="play" [size]="14" color="currentColor" />
          {{ busy() ? (isLive() ? 'Reprise…' : 'Démarrage…') : isLive() ? 'Reprendre la capture' : 'Démarrer la capture' }}
        </button>
      </div>
    </div>
  `,
})
export class CaptureFilPlanComponent {
  protected readonly engine = inject(CaptureEngine);
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);

  @ViewChild('outlineEditor') private outlineEditor?: ElementRef<HTMLTextAreaElement>;

  /** Emitted once the realtime leg is connecting — shell shows the session. */
  @Output() started = new EventEmitter<void>();

  protected readonly iconBtn =
    'display:inline-flex; align-items:center; justify-content:center; width:30px; height:30px; border-radius:var(--ck-radius-sm); border:1px solid var(--ck-stroke-2); background:transparent; color:var(--ck-fg-3); cursor:pointer;';

  protected readonly busy = signal(false);
  protected readonly dialogueLoading = signal(false);
  protected readonly extracting = signal(false);
  protected readonly recording = signal(false);
  protected readonly transcribing = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly notice = signal<PlanNotice | null>(null);
  protected readonly instruction = signal('');
  protected readonly nextPrompt = signal<string | null>(null);
  protected readonly topics = signal<PlanTopic[]>([]);
  /** Free-text editing buffer; null means "serialize from topics()". */
  protected readonly outlineDraft = signal<string | null>(null);

  protected readonly sessionId = this.engine.sessionId;
  protected readonly title = computed(() => this.engine.session()?.title ?? 'Plan de capture');
  protected readonly objective = computed(() => this.engine.session()?.objective ?? '');
  protected readonly isFree = computed(
    () => (this.engine.session()?.plan_mode ?? '') === 'free_conversation',
  );
  /** Session already started (resume path) — the button reconnects, no re-start. */
  protected readonly isLive = computed(() => {
    const status = (this.engine.session()?.status ?? '').toLowerCase();
    return (
      !!status &&
      !['draft', 'planning', 'plan_ready', 'completed', 'published', 'archived'].includes(status)
    );
  });

  protected readonly outlineText = computed(
    () => this.outlineDraft() ?? this.serializeOutline(this.topics()),
  );

  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];

  constructor() {
    this.topics.set(this.topicsFromSession());
    this.destroyRef.onDestroy(() => this.abortRecorder());
  }

  // ---- plan topics (hierarchical) ----------------------------------------

  private topicsFromSession(): PlanTopic[] {
    const plan = this.engine.session()?.plan ?? null;
    const topics = (plan as { topics?: PlanTopic[] } | null)?.topics;
    return Array.isArray(topics) ? topics.map((t) => this.cloneTopic(t)) : [];
  }

  private cloneTopic(t: PlanTopic): PlanTopic {
    return {
      ...t,
      subtopics: Array.isArray(t.subtopics) ? t.subtopics.map((s) => ({ ...s })) : [],
    };
  }

  /** Reflect the textarea edit into the structured topics (preserving n-1 base). */
  protected onOutlineInput(text: string): void {
    this.outlineDraft.set(text);
    this.topics.set(this.parseOutline(text, this.topics()));
  }

  private async persistTopics(): Promise<void> {
    const sessionId = this.engine.sessionId();
    const topics = this.topics().filter((t) => (t.title || '').trim() || (t.subtopics || []).length);
    if (!sessionId || !topics.length) return;
    await firstValueFrom(
      this.api
        .updateCapturePlanTopics(sessionId, topics as unknown as Record<string, unknown>[])
        .pipe(takeUntilDestroyed(this.destroyRef)),
    );
  }

  // ---- outline serialize / parse (ported from v0) ------------------------

  private serializeOutline(topics: PlanTopic[]): string {
    return topics
      .map((topic, topicIndex) => {
        const lines = [`${topicIndex + 1}. ${topic.title ?? ''}`];
        const subtopics = topic.subtopics || [];
        const visible = subtopics.filter((s) => {
          const title = (s.title || '').trim();
          return title && !(subtopics.length === 1 && title === topic.title && !s.objective);
        });
        visible.forEach((s, i) => lines.push(`   ${topicIndex + 1}.${i + 1}. ${s.title}`));
        return lines.join('\n');
      })
      .join('\n');
  }

  private parseOutline(text: string, fallbackTopics: PlanTopic[]): PlanTopic[] {
    const topics: PlanTopic[] = [];
    let current: PlanTopic | null = null;
    const addTopic = (title: string): PlanTopic => {
      const index = topics.length;
      const fallback = fallbackTopics[index];
      const topic: PlanTopic = {
        id: fallback?.id || `t-${String(index + 1).padStart(2, '0')}`,
        title: title.trim() || `Sujet ${index + 1}`,
        objective: fallback?.objective || '',
        prompt: fallback?.prompt,
        status: fallback?.status,
        knowledge_refs: fallback?.knowledge_refs || [],
        subtopics: [],
      };
      topics.push(topic);
      current = topic;
      return topic;
    };
    const addSubtopic = (title: string): void => {
      const topic = current || addTopic('Plan');
      const subtopics = topic.subtopics || [];
      const fallback = fallbackTopics[topics.length - 1]?.subtopics?.[subtopics.length];
      subtopics.push({
        id: fallback?.id || `${topic.id}-sub-${String(subtopics.length + 1).padStart(2, '0')}`,
        title: title.trim() || `Sous-sujet ${subtopics.length + 1}`,
        objective: fallback?.objective || '',
        prompt: fallback?.prompt,
        status: fallback?.status || 'pending',
      });
      topic.subtopics = subtopics;
    };

    for (const rawLine of text.split(/\r?\n/)) {
      if (!rawLine.trim()) continue;
      const indent = rawLine.length - rawLine.trimStart().length;
      const line = rawLine.trim();
      const heading = /^(#{1,6})\s+(.+)$/.exec(line);
      if (heading) {
        if (heading[1].length === 1) addTopic(heading[2]);
        else addSubtopic(heading[2]);
        continue;
      }
      const dotted = /^(\d+(?:\.\d+)+)[.)]?\s+(.+)$/.exec(line);
      if (dotted) {
        if (dotted[1].includes('.')) addSubtopic(dotted[2]);
        else addTopic(dotted[2]);
        continue;
      }
      const numbered = /^\d+[.)]\s+(.+)$/.exec(line);
      if (numbered) {
        addTopic(numbered[1]);
        continue;
      }
      const alpha = /^[a-zA-Z][.)]\s+(.+)$/.exec(line);
      if (alpha) {
        addSubtopic(alpha[1]);
        continue;
      }
      const bullet = /^[-*•·▪◦]\s+(.+)$/.exec(line);
      if (bullet) {
        if (!current) addTopic(bullet[1]);
        else addSubtopic(bullet[1]);
        continue;
      }
      if (!current || indent === 0) addTopic(line);
      else addSubtopic(line);
    }
    return topics;
  }

  // ---- outline formatting (toolbar + keyboard) ---------------------------

  protected applyFormat(action: OutlineAction): void {
    const textarea = this.outlineEditor?.nativeElement;
    if (!textarea) return;
    const original = textarea.value || this.outlineText();
    const lines = original.split('\n');
    const range = this.selectedLines(original, textarea.selectionStart || 0, textarea.selectionEnd || 0);
    let nextLines = [...lines];
    let nextStart = range.startLine;
    let nextEnd = range.endLine;
    const count = range.endLine - range.startLine + 1;

    if (action === 'renumber') {
      nextLines = this.renumberLines(nextLines);
    } else if (action === 'move_up') {
      if (range.startLine === 0) return;
      const selected = nextLines.splice(range.startLine, count);
      nextLines.splice(range.startLine - 1, 0, ...selected);
      nextStart -= 1;
      nextEnd -= 1;
    } else if (action === 'move_down') {
      if (range.endLine >= nextLines.length - 1) return;
      const selected = nextLines.splice(range.startLine, count);
      nextLines.splice(range.startLine + 1, 0, ...selected);
      nextStart += 1;
      nextEnd += 1;
    } else {
      nextLines = nextLines.map((line, index) =>
        index < range.startLine || index > range.endLine ? line : this.formatLine(line, action),
      );
      nextLines = this.renumberLines(nextLines);
    }

    const nextText = nextLines.join('\n');
    textarea.value = nextText;
    this.onOutlineInput(nextText);
    const selStart = this.lineOffset(nextLines, nextStart);
    const selEnd = this.lineOffset(nextLines, nextEnd) + (nextLines[nextEnd]?.length || 0);
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(Math.max(0, selStart), Math.max(0, selEnd));
    });
  }

  protected onOutlineKeydown(event: KeyboardEvent): void {
    const textarea = event.target as HTMLTextAreaElement | null;
    if (!textarea) return;
    if (event.key === 'Tab') {
      event.preventDefault();
      this.applyIndentShortcut(textarea, event.shiftKey ? 'outdent' : 'indent');
    }
  }

  private applyIndentShortcut(textarea: HTMLTextAreaElement, action: 'indent' | 'outdent'): void {
    const original = textarea.value || this.outlineText();
    const start = textarea.selectionStart || 0;
    const end = textarea.selectionEnd || start;
    const range = this.selectedLines(original, start, end);
    const lines = original.split('\n');
    for (let index = range.startLine; index <= range.endLine; index += 1) {
      lines[index] = this.formatLine(lines[index] || '', action);
    }
    const nextLines = this.renumberLines(lines);
    const nextText = nextLines.join('\n');
    textarea.value = nextText;
    this.onOutlineInput(nextText);
    const selStart = this.lineOffset(nextLines, range.startLine);
    const selEnd = this.lineOffset(nextLines, range.endLine) + (nextLines[range.endLine]?.length || 0);
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(Math.max(0, selStart), Math.max(0, selEnd));
    });
  }

  private selectedLines(text: string, start: number, end: number): { startLine: number; endLine: number } {
    const safeStart = Math.max(0, Math.min(start, text.length));
    const rawEnd = Math.max(safeStart, Math.min(end, text.length));
    const safeEnd = rawEnd > safeStart && text[rawEnd - 1] === '\n' ? rawEnd - 1 : rawEnd;
    return {
      startLine: text.slice(0, safeStart).split('\n').length - 1,
      endLine: text.slice(0, safeEnd).split('\n').length - 1,
    };
  }

  private lineOffset(lines: string[], lineIndex: number): number {
    let offset = 0;
    for (let index = 0; index < lineIndex; index += 1) offset += (lines[index] || '').length + 1;
    return offset;
  }

  private formatLine(line: string, action: 'indent' | 'outdent'): string {
    if (action === 'indent') return `   ${line}`;
    return line.replace(/^( {1,3}|\t)/, '');
  }

  private renumberLines(lines: string[]): string[] {
    const counters: number[] = [];
    let previousLevel = 0;
    return lines.map((line) => {
      if (!line.trim()) return line;
      const requestedLevel = this.indentLevel(line);
      const level = counters.length ? Math.min(requestedLevel, previousLevel + 1) : 0;
      for (let index = 0; index < level; index += 1) counters[index] = counters[index] || 1;
      counters[level] = (counters[level] || 0) + 1;
      counters.length = level + 1;
      previousLevel = level;
      const body = this.stripMarker(line.trim()) || 'Point à préciser';
      return `${'   '.repeat(level)}${counters.slice(0, level + 1).join('.')}. ${body}`;
    });
  }

  private indentLevel(line: string): number {
    const prefix = line.match(/^\s*/)?.[0] || '';
    const width = Array.from(prefix).reduce((sum, ch) => sum + (ch === '\t' ? 3 : 1), 0);
    if (width <= 0) return 0;
    return Math.max(1, Math.round(width / 3));
  }

  private stripMarker(value: string): string {
    return value
      .replace(/^(?:#{1,6}\s+|\d+(?:\.\d+)*[.)]?\s+|[a-zA-Z][.)]\s+|[-*•·▪◦]\s+)/, '')
      .trim();
  }

  // ---- dialogue assistant (typed / dictated / imported) ------------------

  protected submitInstruction(): void {
    const text = this.instruction().trim();
    if (!text || this.dialogueLoading()) return;
    void this.runDialogueTurn(text);
  }

  private async runDialogueTurn(text: string): Promise<void> {
    const sessionId = this.engine.sessionId();
    if (!sessionId) return;
    this.dialogueLoading.set(true);
    this.notice.set(null);
    try {
      // Persist the CURRENT plan first so the backend mutates from it (n-1 base):
      // "ajoute telle section" augments the existing plan instead of restarting.
      await this.persistTopics();
      const payload = await firstValueFrom(
        this.api.planDialogueTurn(sessionId, { text }).pipe(takeUntilDestroyed(this.destroyRef)),
      );
      const body = payload as {
        session?: Record<string, unknown>;
        next_prompt?: string | null;
      };
      if (body.session) {
        const info = this.toSessionInfo(body.session);
        this.engine.setSession(info);
        // Re-sync from the freshly returned plan and drop the editing buffer.
        this.topics.set(this.topicsFromSession());
        this.outlineDraft.set(null);
      }
      this.nextPrompt.set(body.next_prompt ?? null);
      this.instruction.set('');
      this.notice.set({ tone: 'success', text: 'Plan mis à jour.' });
    } catch {
      this.notice.set({ tone: 'error', text: "Impossible d'appliquer cette instruction. Réessayez." });
    } finally {
      this.dialogueLoading.set(false);
    }
  }

  protected onImportInstruction(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    input.value = '';
    this.extracting.set(true);
    this.notice.set({ tone: 'info', text: 'Extraction du document…' });
    this.api
      .extractCapturePlanSource(file)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          this.extracting.set(false);
          const text = String(payload.text || '').slice(0, 20000).trim();
          if (!text) {
            this.notice.set({ tone: 'error', text: 'Document vide ou illisible.' });
            return;
          }
          void this.runDialogueTurn(`Voici un document de référence à intégrer au plan :\n\n${text}`);
        },
        error: () => {
          this.extracting.set(false);
          this.notice.set({ tone: 'error', text: "Import du document impossible." });
        },
      });
  }

  // ---- dictation (lean: record → transcribeAudio → text) -----------------

  protected async toggleDictation(): Promise<void> {
    if (this.recording()) {
      this.stopDictation();
      return;
    }
    const media = navigator.mediaDevices;
    if (!media?.getUserMedia || typeof MediaRecorder === 'undefined') {
      this.notice.set({ tone: 'error', text: 'Micro indisponible dans ce navigateur.' });
      return;
    }
    let stream: MediaStream;
    try {
      stream = await media.getUserMedia({ audio: true });
    } catch {
      this.notice.set({ tone: 'error', text: 'Accès au micro refusé.' });
      return;
    }
    this.chunks = [];
    const recorder = new MediaRecorder(stream);
    this.recorder = recorder;
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size) this.chunks.push(e.data);
    };
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      this.finalizeDictation();
    };
    recorder.start();
    this.recording.set(true);
    this.notice.set({ tone: 'info', text: 'Dictée en cours — parlez, puis arrêtez pour transcrire.' });
  }

  private stopDictation(): void {
    const recorder = this.recorder;
    if (recorder && recorder.state !== 'inactive') {
      try {
        recorder.stop();
      } catch {
        /* best-effort */
      }
    }
    this.recording.set(false);
  }

  private finalizeDictation(): void {
    this.recorder = null;
    const blob = new Blob(this.chunks, { type: 'audio/webm' });
    this.chunks = [];
    if (!blob.size) {
      this.notice.set(null);
      return;
    }
    this.transcribing.set(true);
    this.api
      .transcribeAudio(blob)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.transcribing.set(false);
          const text = (res.text || '').trim();
          if (text) {
            this.instruction.update((v) => (v.trim() ? `${v} ${text}` : text));
            this.notice.set(null);
          } else {
            this.notice.set({ tone: 'info', text: 'Rien transcrit. Réessayez.' });
          }
        },
        error: () => {
          this.transcribing.set(false);
          this.notice.set({ tone: 'error', text: 'Transcription impossible.' });
        },
      });
  }

  private abortRecorder(): void {
    const recorder = this.recorder;
    this.recorder = null;
    if (recorder && recorder.state !== 'inactive') {
      try {
        recorder.stop();
      } catch {
        /* best-effort */
      }
    }
  }

  // ---- start -------------------------------------------------------------

  protected start(): void {
    const sessionId = this.engine.sessionId();
    if (!sessionId || this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    const connect = () => {
      void this.engine.connect(sessionId);
      this.busy.set(false);
      this.started.emit();
    };
    // Resume: an already-started session must NOT be re-started (idempotency /
    // wrong-state guard) — just reconnect the realtime leg.
    if (this.isLive()) {
      connect();
      return;
    }
    const launch = () =>
      this.api
        .startCaptureSession(sessionId)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: connect,
          error: () => {
            this.busy.set(false);
            this.error.set('Démarrage impossible.');
          },
        });
    // Persist topic edits before launching (with-plan only); never block start.
    if (!this.isFree()) {
      this.persistTopics().then(launch, launch);
    } else {
      launch();
    }
  }

  private toSessionInfo(payload: Record<string, unknown>): CaptureSessionInfo {
    const prev = this.engine.session();
    return {
      id: String(payload['id'] ?? prev?.id ?? ''),
      title: (payload['title'] as string) ?? prev?.title ?? null,
      objective: (payload['objective'] as string) ?? prev?.objective ?? null,
      status: (payload['status'] as string) ?? prev?.status ?? null,
      duration_minutes: (payload['duration_minutes'] as number) ?? prev?.duration_minutes ?? null,
      plan: (payload['plan'] as Record<string, unknown>) ?? prev?.plan ?? null,
      plan_mode: (payload['plan_mode'] as string) ?? prev?.plan_mode ?? null,
      system_id: (payload['system_id'] as string | null) ?? prev?.system_id ?? null,
    };
  }
}
