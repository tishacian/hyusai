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
import { ApiService } from '@app/core/api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { CaptureEngine } from '../capture-engine';

interface PlanTopic {
  id?: string;
  title?: string;
  objective?: string;
  prompt?: string;
}

/**
 * Plan surface (Phase 5) — review the generated plan topics, attach documents
 * (reuses {@link ApiService.uploadCaptureDocuments}), then start the live
 * session ({@link ApiService.startCaptureSession} + {@link CaptureEngine.connect}).
 */
@Component({
  selector: 'app-capture-fil-plan',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent],
  template: `
    <div style="display:flex; flex-direction:column; gap:18px; max-width:820px;">
      <div>
        <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
          Capture · Plan
        </span>
        <h2 style="margin:6px 0 4px; font-size:22px; font-weight:680; color:var(--ck-fg-1);">{{ title() }}</h2>
        <p style="margin:0; font-size:13.5px; color:var(--ck-fg-3); line-height:1.55; max-width:64ch;">
          {{ objective() }}
        </p>
      </div>

      <div class="ck-surface" style="border-radius:var(--ck-radius-lg); padding:18px; display:flex; flex-direction:column; gap:12px;">
        <div class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">
          Topics du plan · {{ topics().length }}
        </div>
        @if (topics().length === 0) {
          <div style="font-size:13px; color:var(--ck-fg-4); font-style:italic;">
            Plan libre — aucune liste de topics. Vous capturerez au fil de la conversation.
          </div>
        }
        @for (t of topics(); track $index) {
          <div style="display:flex; gap:12px; align-items:flex-start; padding:10px 12px; border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-2);">
            <span class="ck-mono" style="font-size:11px; color:var(--ck-signal-cool); padding-top:2px;">{{ $index + 1 }}</span>
            <div style="min-width:0;">
              <div style="font-size:13.5px; font-weight:600; color:var(--ck-fg-1);">{{ t.title || 'Topic' }}</div>
              @if (t.objective || t.prompt) {
                <div style="font-size:12px; color:var(--ck-fg-4); margin-top:2px; line-height:1.45;">{{ t.objective || t.prompt }}</div>
              }
            </div>
          </div>
        }
      </div>

      <div class="ck-surface" style="border-radius:var(--ck-radius-lg); padding:18px; display:flex; flex-direction:column; gap:12px;">
        <div style="display:flex; align-items:center; gap:10px;">
          <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">
            Documents · {{ engine.documents().length }}
          </span>
          <label
            style="margin-left:auto; display:inline-flex; align-items:center; gap:6px; padding:6px 12px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); cursor:pointer; font-size:12px; color:var(--ck-fg-2);"
          >
            <ck-glyph name="layers" [size]="13" color="currentColor" />
            {{ uploading() ? 'Téléversement…' : 'Ajouter des pièces' }}
            <input type="file" multiple (change)="onUpload($event)" style="display:none;" />
          </label>
        </div>
        @for (d of engine.documents(); track d.document_id || d.filename || $index) {
          <div style="display:flex; align-items:center; gap:10px; padding:8px 10px; border-radius:var(--ck-radius-sm); background:var(--ck-bg-inset);">
            <ck-glyph name="ledger" [size]="14" color="var(--ck-fg-3)" />
            <span class="ck-mono" style="font-size:12px; color:var(--ck-fg-2);">{{ d.filename || d.title || 'document' }}</span>
          </div>
        }
        @if (engine.documents().length === 0) {
          <div style="font-size:12.5px; color:var(--ck-fg-4); font-style:italic;">
            Optionnel : ajoutez les pièces que l'expert montrera (plans, coupes, clichés).
          </div>
        }
      </div>

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
          {{ busy() ? 'Démarrage…' : 'Démarrer la capture' }}
        </button>
      </div>
    </div>
  `,
})
export class CaptureFilPlanComponent {
  protected readonly engine = inject(CaptureEngine);
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** Emitted once the realtime leg is connecting — shell shows Le Fil. */
  @Output() started = new EventEmitter<void>();

  protected readonly busy = signal(false);
  protected readonly uploading = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly sessionId = this.engine.sessionId;
  protected readonly title = computed(() => this.engine.session()?.title ?? 'Plan de capture');
  protected readonly objective = computed(() => this.engine.session()?.objective ?? '');
  protected readonly topics = computed<PlanTopic[]>(() => {
    const plan = this.engine.session()?.plan ?? null;
    const topics = (plan as { topics?: PlanTopic[] } | null)?.topics;
    return Array.isArray(topics) ? topics : [];
  });

  protected onUpload(event: Event): void {
    const input = event.target as HTMLInputElement;
    const files = input.files;
    const sessionId = this.engine.sessionId();
    if (!files || !files.length || !sessionId) return;
    this.uploading.set(true);
    this.api
      .uploadCaptureDocuments(sessionId, files)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.uploading.set(false);
          void this.engine.loadDocuments();
          input.value = '';
        },
        error: () => {
          this.uploading.set(false);
          this.error.set('Téléversement impossible.');
        },
      });
  }

  protected start(): void {
    const sessionId = this.engine.sessionId();
    if (!sessionId || this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    this.api
      .startCaptureSession(sessionId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          void this.engine.connect(sessionId);
          this.busy.set(false);
          this.started.emit();
        },
        error: () => {
          this.busy.set(false);
          this.error.set('Démarrage impossible.');
        },
      });
  }
}
