import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { CaptureEngine, type CaptureSessionInfo } from '../capture-engine';

interface PlanTopic {
  id?: string;
  title?: string;
  objective?: string;
  prompt?: string;
}

interface PlanNotice {
  tone: 'success' | 'error' | 'info';
  text: string;
}

/**
 * Launch surface — builds the plan (with-plan mode) and owns the single,
 * explicit Start. Restores the v0 plan-creation capabilities that the first
 * cockpit rewrite dropped: **editable topics**, a **dialogue assistant**
 * (typed instruction → `planDialogueTurn`), **document import** (extract → same
 * instruction path), and **dictation** (record → `transcribeAudio` → text).
 *
 * Pieces shown by the expert are uploaded **in-session** (La Scène), not here:
 * this surface is about framing/launching, not about session artefacts.
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
        <!-- Editable plan topics -->
        <div class="ck-surface" style="border-radius:var(--ck-radius-lg); padding:18px; display:flex; flex-direction:column; gap:12px;">
          <div style="display:flex; align-items:center; gap:10px;">
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">
              Sujets du plan · {{ topics().length }}
            </span>
            <button
              type="button"
              (click)="addTopic()"
              style="margin-left:auto; display:inline-flex; align-items:center; gap:6px; padding:6px 12px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); cursor:pointer; font-size:12px; color:var(--ck-fg-2); background:transparent;"
            >
              <ck-glyph name="bolt" [size]="13" color="currentColor" /> Ajouter un sujet
            </button>
          </div>

          @if (topics().length === 0) {
            <div style="font-size:12.5px; color:var(--ck-fg-4); font-style:italic;">
              Aucun sujet pour l'instant. Décrivez les points à couvrir ci-dessous (texte, dictée ou import de
              document) pour générer le plan — ou ajoutez les sujets à la main.
            </div>
          }

          @for (t of topics(); track $index) {
            <div style="display:flex; gap:10px; align-items:flex-start; padding:10px 12px; border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-2);">
              <span class="ck-mono" style="font-size:11px; color:var(--ck-signal-cool); padding-top:9px;">{{ $index + 1 }}</span>
              <div style="flex:1; min-width:0; display:flex; flex-direction:column; gap:6px;">
                <input
                  [value]="t.title || ''"
                  (input)="updateTopic($index, 'title', $any($event.target).value)"
                  placeholder="Titre du sujet"
                  style="border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-sm); background:var(--ck-bg-base); color:var(--ck-fg-1); font-family:var(--ck-font-sans); font-size:13.5px; font-weight:600; padding:7px 10px;"
                />
                <input
                  [value]="t.objective || t.prompt || ''"
                  (input)="updateTopic($index, 'objective', $any($event.target).value)"
                  placeholder="Objectif / question directrice (optionnel)"
                  style="border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-sm); background:var(--ck-bg-base); color:var(--ck-fg-2); font-family:var(--ck-font-sans); font-size:12px; padding:6px 10px;"
                />
              </div>
              <button
                type="button"
                (click)="removeTopic($index)"
                title="Retirer ce sujet"
                style="flex:none; display:inline-flex; align-items:center; justify-content:center; width:28px; height:28px; border-radius:var(--ck-radius-sm); border:1px solid var(--ck-stroke-2); background:transparent; color:var(--ck-fg-4); cursor:pointer;"
              >
                <ck-glyph name="x" [size]="13" color="currentColor" />
              </button>
            </div>
          }
        </div>

        <!-- Dialogue assistant: instruction (typed / dictated / imported) -->
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
            placeholder="Décrivez un sujet ou donnez une instruction (« ajoute un sujet sur… », « reformule… »). L'assistant met à jour le plan."
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
              [title]="'Importer un document (notes, plan) : son contenu est appliqué comme instruction de plan.'"
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
              {{ dialogueLoading() ? 'Envoi…' : 'Envoyer' }}
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

  /** Emitted once the realtime leg is connecting — shell shows the session. */
  @Output() started = new EventEmitter<void>();

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

  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];

  constructor() {
    this.topics.set(this.topicsFromSession());
    this.destroyRef.onDestroy(() => this.abortRecorder());
  }

  // ---- plan topics -------------------------------------------------------

  private topicsFromSession(): PlanTopic[] {
    const plan = this.engine.session()?.plan ?? null;
    const topics = (plan as { topics?: PlanTopic[] } | null)?.topics;
    return Array.isArray(topics) ? topics.map((t) => ({ ...t })) : [];
  }

  protected addTopic(): void {
    this.topics.update((list) => [...list, { title: '', objective: '' }]);
  }

  protected removeTopic(index: number): void {
    this.topics.update((list) => list.filter((_, i) => i !== index));
  }

  protected updateTopic(index: number, field: 'title' | 'objective', value: string): void {
    this.topics.update((list) =>
      list.map((t, i) => (i === index ? { ...t, [field]: value } : t)),
    );
  }

  private async persistTopics(): Promise<void> {
    const sessionId = this.engine.sessionId();
    const topics = this.topics().filter((t) => (t.title || '').trim() || (t.objective || '').trim());
    if (!sessionId || !topics.length) return;
    await firstValueFrom(
      this.api
        .updateCapturePlanTopics(sessionId, topics as unknown as Record<string, unknown>[])
        .pipe(takeUntilDestroyed(this.destroyRef)),
    );
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
      // Persist current topic edits first (mirrors v0): the backend iterates the
      // plan from the current topics + the new instruction.
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
        this.topics.set(this.topicsFromSession());
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
