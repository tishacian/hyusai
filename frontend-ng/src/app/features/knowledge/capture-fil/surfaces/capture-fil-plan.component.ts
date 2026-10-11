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
import { I18nService } from '@app/core/i18n.service';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { CaptureEngine, type CaptureSessionInfo } from '../capture-engine';
import { lockedPlanTopicTitles } from '../capture-templates';

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
          {{ isFree() ? i18n.t('capture.plan.eyebrow_free') : i18n.t('capture.plan.eyebrow') }}
        </span>
        <h2 style="margin:6px 0 4px; font-size:22px; font-weight:680; color:var(--ck-fg-1);">{{ title() }}</h2>
        <p style="margin:0; font-size:13.5px; color:var(--ck-fg-3); line-height:1.55; max-width:64ch;">
          {{ objective() }}
        </p>
        @if (planLocked()) {
          <div style="margin-top:10px; display:flex; gap:8px; align-items:flex-start; font-size:12.5px; color:var(--ck-fg-3); line-height:1.5;">
            <ck-glyph name="ledger" [size]="14" color="var(--ck-signal-cool)" />
            <span>{{ i18n.t('capture.plan.locked') }}</span>
          </div>
        }
      </div>

      @if (previousReportOpenCount() > 0) {
        <div style="display:flex; gap:10px; align-items:flex-start; padding:12px 14px; border-radius:var(--ck-radius-md); background:color-mix(in oklab, var(--ck-signal-warn) 10%, transparent); border:1px solid color-mix(in oklab, var(--ck-signal-warn) 35%, transparent);">
          <ck-glyph name="warn" [size]="15" color="var(--ck-signal-warn)" />
          <div style="font-size:13px; color:var(--ck-fg-2); line-height:1.5;">
            {{ i18n.t('capture.plan.carried_open_points', { count: previousReportOpenCount() }) }}
          </div>
        </div>
      }

      @if (isFree()) {
        <div class="ck-surface" style="border-radius:var(--ck-radius-lg); padding:18px; display:flex; gap:12px; align-items:flex-start;">
          <ck-glyph name="pulse" [size]="18" color="var(--ck-signal-cool)" />
          <div>
            <div style="font-size:14px; font-weight:600; color:var(--ck-fg-1);">{{ i18n.t('capture.plan.free_title') }}</div>
            <div style="font-size:12.5px; color:var(--ck-fg-4); margin-top:3px; line-height:1.5;">
              {{ i18n.t('capture.plan.free_hint') }}
            </div>
          </div>
        </div>
      } @else {
        <!-- Hierarchical outline editor (topics + subtopics) -->
        <div class="ck-surface" style="border-radius:var(--ck-radius-lg); padding:18px; display:flex; flex-direction:column; gap:12px;">
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">
              {{ i18n.t('capture.plan.topics_count', { count: topics().length }) }}
            </span>
            <div style="margin-left:auto; display:inline-flex; align-items:center; gap:6px;">
              <button type="button" (click)="applyFormat('outdent')" [title]="i18n.t('capture.plan.outdent')" [style]="iconBtn"><ck-glyph name="zoom-out" [size]="13" color="currentColor" /></button>
              <button type="button" (click)="applyFormat('indent')" [title]="i18n.t('capture.plan.indent')" [style]="iconBtn"><ck-glyph name="zoom-in" [size]="13" color="currentColor" /></button>
              <button type="button" (click)="applyFormat('renumber')" [title]="i18n.t('capture.plan.renumber')" [style]="iconBtn"><ck-glyph name="ledger" [size]="13" color="currentColor" /></button>
              <button type="button" (click)="applyFormat('move_up')" [title]="i18n.t('capture.plan.move_up')" [style]="iconBtn"><ck-glyph name="arrow-up" [size]="13" color="currentColor" /></button>
              <button type="button" (click)="applyFormat('move_down')" [title]="i18n.t('capture.plan.move_down')" [style]="iconBtn"><ck-glyph name="arrow-down" [size]="13" color="currentColor" /></button>
            </div>
          </div>

          <textarea
            #outlineEditor
            rows="10"
            [value]="outlineText()"
            (input)="onOutlineInput($any($event.target).value)"
            (keydown)="onOutlineKeydown($event)"
            spellcheck="false"
            [placeholder]="i18n.t('capture.plan.outline_placeholder')"
            style="resize:vertical; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); color:var(--ck-fg-1); font-family:var(--ck-font-mono); font-size:13px; line-height:1.6; padding:12px 14px; min-height:200px;"
          ></textarea>
          <div class="ck-mono" style="font-size:10.5px; color:var(--ck-fg-5);">
            {{ i18n.t('capture.plan.outline_hint') }}
          </div>
        </div>

        <!-- Dialogue assistant: keeps the current plan as base (n-1) -->
        <div class="ck-surface" style="border-radius:var(--ck-radius-lg); padding:18px; display:flex; flex-direction:column; gap:10px;">
          <div style="display:flex; align-items:center; gap:8px;">
            <ck-glyph name="pulse" [size]="15" color="var(--ck-signal-violet)" />
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">
              {{ i18n.t('capture.plan.assistant') }}
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
            [placeholder]="i18n.t('capture.plan.instruction_placeholder')"
            style="resize:vertical; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); color:var(--ck-fg-1); font-family:var(--ck-font-sans); font-size:14px; line-height:1.5; padding:10px 12px;"
          ></textarea>

          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
            <button
              type="button"
              (click)="toggleDictation()"
              [disabled]="dialogueLoading() || transcribing()"
              [title]="recording() ? i18n.t('capture.plan.dictation_stop_hint') : i18n.t('capture.plan.dictation_start_hint')"
              style="display:inline-flex; align-items:center; gap:7px; padding:8px 12px; border-radius:var(--ck-radius-md); cursor:pointer; font-size:12.5px; background:var(--ck-bg-inset);"
              [style.border]="'1px solid ' + (recording() ? 'var(--ck-signal-neg)' : 'var(--ck-stroke-2)')"
              [style.color]="recording() ? 'var(--ck-signal-neg)' : 'var(--ck-fg-2)'"
            >
              <ck-glyph [name]="recording() ? 'pause' : 'pulse'" [size]="14" color="currentColor" />
              {{
                recording()
                  ? i18n.t('capture.plan.dictation_stop')
                  : transcribing()
                    ? i18n.t('capture.plan.transcribing')
                    : i18n.t('capture.plan.dictate')
              }}
            </button>

            <label
              style="display:inline-flex; align-items:center; gap:7px; padding:8px 12px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); cursor:pointer; font-size:12.5px; color:var(--ck-fg-2);"
              [style.opacity]="dialogueLoading() || extracting() ? 0.5 : 1"
              [title]="i18n.t('capture.plan.import_hint')"
            >
              <ck-glyph name="layers" [size]="14" color="currentColor" />
              {{ extracting() ? i18n.t('capture.plan.extracting') : i18n.t('capture.plan.import') }}
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
              {{ dialogueLoading() ? i18n.t('capture.plan.sending') : i18n.t('capture.plan.apply') }}
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
          {{
            busy()
              ? isLive()
                ? i18n.t('capture.plan.resuming')
                : i18n.t('capture.plan.starting')
              : isLive()
                ? i18n.t('capture.plan.resume')
                : i18n.t('capture.plan.start')
          }}
        </button>
      </div>
    </div>
  `,
})
export class CaptureFilPlanComponent {
  readonly i18n = inject(I18nService);

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
  protected readonly previousReportOpenCount = this.engine.previousReportOpenCount;
  protected readonly title = computed(() => this.engine.session()?.title ?? 'Plan de capture');
  protected readonly objective = computed(() => this.engine.session()?.objective ?? '');
  protected readonly planLocked = computed(
    () => Boolean(this.engine.template()?.ui.lock_plan),
  );
  /**
   * No-plan (free conversation) mode. Delegates to the engine so the detection
   * is robust on resume: the list/get serializer omits the top-level `plan_mode`,
   * so the engine falls back to `plan.mode` / schema / "no topics". Otherwise a
   * plan-less session wrongly rendered the plan-configuration outline editor.
   */
  protected readonly isFree = this.engine.isFreeConversation;
  /**
   * Session already started (resume path) — the button reconnects instead of
   * issuing a fresh Start. A cyan-new session is created as "planned" (never
   * started: the backend only flips it to "active" once `started_at` is set), so
   * it must show "Démarrer la capture". Uses the engine's POSITIVE allowlist of
   * genuinely in-progress / resumable statuses (plus an already-live engine
   * connection) — a blocklist wrongly treated every unknown/pre-start status
   * (incl. "planned") as in-progress and showed "Reprendre" for fresh sessions.
   */
  protected readonly isLive = computed(() => this.engine.connected() || this.engine.isResumable());

  protected readonly outlineText = computed(
    () => this.outlineDraft() ?? this.serializeOutline(this.topics()),
  );

  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  /** Text already in the field when dictation started — partials replace from here. */
  private dictationBase = '';
  private partialInFlight = false;
  private lastPartialAt = 0;
  private partialRequestId = 0;

  constructor() {
    this.topics.set(this.ensureLockedSeedTopics(this.topicsFromSession()));
    this.destroyRef.onDestroy(() => this.abortRecorder());
  }

  // ---- plan topics (hierarchical) ----------------------------------------

  private topicsFromSession(): PlanTopic[] {
    const plan = this.engine.session()?.plan ?? null;
    const topics = (plan as { topics?: PlanTopic[] } | null)?.topics;
    return Array.isArray(topics) ? topics.map((t) => this.cloneTopic(t)) : [];
  }

  /** When lock_plan, re-inject any missing type-section titles from the seed. */
  private ensureLockedSeedTopics(topics: PlanTopic[]): PlanTopic[] {
    const tpl = this.engine.template();
    if (!tpl?.ui.lock_plan) return topics;
    const required = lockedPlanTopicTitles(tpl);
    if (!required.length) return topics;
    const present = new Set(
      topics.map((t) => (t.title || '').trim().toLowerCase()).filter(Boolean),
    );
    const next = topics.map((t) => this.cloneTopic(t));
    required.forEach((title, index) => {
      if (present.has(title.toLowerCase())) return;
      next.splice(Math.min(index, next.length), 0, {
        id: `seed-t-${String(index + 1).padStart(2, '0')}`,
        title,
        objective: '',
        subtopics: [],
      });
    });
    return next;
  }

  private cloneTopic(t: PlanTopic): PlanTopic {
    return {
      ...t,
      subtopics: Array.isArray(t.subtopics) ? t.subtopics.map((s) => ({ ...s })) : [],
    };
  }

  /** Reflect the textarea edit into the structured topics (preserving n-1 base). */
  protected onOutlineInput(text: string): void {
    const parsed = this.parseOutline(text, this.topics());
    const locked = this.ensureLockedSeedTopics(parsed);
    const restored = this.planLocked() && locked.length !== parsed.length;
    this.outlineDraft.set(restored ? this.serializeOutline(locked) : text);
    this.topics.set(locked);
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
        title: title.trim() || this.i18n.t('capture.plan.topic_default', { index: index + 1 }),
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
        title:
          title.trim()
          || this.i18n.t('capture.plan.subtopic_default', { index: subtopics.length + 1 }),
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
      const body = this.stripMarker(line.trim()) || this.i18n.t('capture.plan.point_to_clarify');
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
      this.notice.set({ tone: 'success', text: this.i18n.t('capture.plan.updated') });
    } catch {
      this.notice.set({ tone: 'error', text: this.i18n.t('capture.plan.instruction_failed') });
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
    this.notice.set({ tone: 'info', text: this.i18n.t('capture.plan.extracting_document') });
    this.api
      .extractCapturePlanSource(file)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          this.extracting.set(false);
          const text = String(payload.text || '').slice(0, 20000).trim();
          if (!text) {
            this.notice.set({ tone: 'error', text: this.i18n.t('capture.plan.document_empty') });
            return;
          }
          void this.runDialogueTurn(this.i18n.t('capture.plan.import_prompt', { text }));
        },
        error: () => {
          this.extracting.set(false);
          this.notice.set({ tone: 'error', text: this.i18n.t('capture.plan.import_error') });
        },
      });
  }

  // ---- dictation (live: record → streamed partial transcripts → text) -----
  // Ported from the v0 monolith: a timeslice recorder emits chunks while the
  // user speaks; each (throttled) chunk re-transcribes the cumulative audio so
  // the text streams into the field LIVE. The full audio is re-transcribed once
  // on stop to finalise. Whisper transcribes the whole blob each time, so each
  // result REPLACES the dictated segment (we keep any pre-existing text as base).

  protected async toggleDictation(): Promise<void> {
    if (this.recording()) {
      this.stopDictation();
      return;
    }
    const media = navigator.mediaDevices;
    if (!media?.getUserMedia || typeof MediaRecorder === 'undefined') {
      this.notice.set({ tone: 'error', text: this.i18n.t('capture.plan.mic_unavailable') });
      return;
    }
    let stream: MediaStream;
    try {
      stream = await media.getUserMedia({ audio: true });
    } catch {
      this.notice.set({ tone: 'error', text: this.i18n.t('capture.plan.mic_denied') });
      return;
    }
    this.chunks = [];
    this.dictationBase = this.instruction().trim();
    this.partialInFlight = false;
    this.lastPartialAt = 0;
    const recorder = new MediaRecorder(stream);
    this.recorder = recorder;
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size) {
        this.chunks.push(e.data);
        this.transcribePartial();
      }
    };
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      this.finalizeDictation();
    };
    // Timeslice → periodic ondataavailable so partials stream during speech.
    recorder.start(1500);
    this.recording.set(true);
    this.notice.set({ tone: 'info', text: this.i18n.t('capture.plan.dictation_live') });
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

  /** Re-transcribe the cumulative audio (throttled, single in-flight) and stream
   *  the partial into the instruction field while speaking. */
  private transcribePartial(): void {
    if (this.partialInFlight || this.chunks.length < 2) return;
    const now = Date.now();
    if (this.lastPartialAt && now - this.lastPartialAt < 1200) return;
    this.partialInFlight = true;
    this.lastPartialAt = now;
    const blob = new Blob(this.chunks, { type: 'audio/webm' });
    const requestId = ++this.partialRequestId;
    this.api
      .transcribeAudio(blob, 'partial.webm')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.partialInFlight = false;
          // Drop stale/late partials (a newer request landed, or dictation ended).
          if (requestId !== this.partialRequestId || !this.recording()) return;
          const text = (res.text || '').trim();
          if (text) this.applyDictation(text);
        },
        error: () => {
          this.partialInFlight = false;
        },
      });
  }

  private applyDictation(text: string): void {
    this.instruction.set(this.dictationBase ? `${this.dictationBase} ${text}` : text);
  }

  private finalizeDictation(): void {
    this.recorder = null;
    // Invalidate any in-flight partial so it can't overwrite the final text.
    this.partialRequestId += 1;
    const blob = new Blob(this.chunks, { type: 'audio/webm' });
    this.chunks = [];
    if (!blob.size) {
      this.transcribing.set(false);
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
            this.applyDictation(text);
            this.notice.set(null);
          } else {
            this.notice.set({ tone: 'info', text: this.i18n.t('capture.plan.nothing_transcribed') });
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
            this.error.set(this.i18n.t('capture.plan.start_failed'));
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
      metrics: (payload['metrics'] as Record<string, unknown>) ?? prev?.metrics ?? null,
      plan_mode: (payload['plan_mode'] as string) ?? prev?.plan_mode ?? null,
      system_id: (payload['system_id'] as string | null) ?? prev?.system_id ?? null,
    };
  }
}
