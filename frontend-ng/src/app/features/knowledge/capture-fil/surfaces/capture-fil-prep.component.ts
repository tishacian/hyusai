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
import { ApiService, type CapturePlanRequest } from '@app/core/api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { CaptureEngine, type CaptureSessionInfo } from '../capture-engine';

type PlanMode = 'ai_plan' | 'free_conversation' | 'plan_build';

interface ModeOption {
  id: PlanMode;
  label: string;
  hint: string;
}

/**
 * Prep surface (Phase 5) — objective / expert profile / duration / plan mode.
 * Reuses {@link ApiService.createCapturePlan}; on success binds the session to
 * the shared {@link CaptureEngine} and asks the shell to advance to the plan
 * surface (or straight to the live session for free conversation).
 */
@Component({
  selector: 'app-capture-fil-prep',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent],
  template: `
    <div style="display:flex; flex-direction:column; gap:18px; max-width:720px;">
      <div>
        <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
          Capture · Préparation
        </span>
        <h2 style="margin:6px 0 4px; font-size:22px; font-weight:680; color:var(--ck-fg-1);">Cadrer la séance</h2>
        <p style="margin:0; font-size:13.5px; color:var(--ck-fg-3); line-height:1.55; max-width:62ch;">
          Décrivez l'objectif de capture. Le plan est généré ensuite ; vous le validez avant de démarrer Le Fil.
        </p>
      </div>

      <div class="ck-surface" style="border-radius:var(--ck-radius-lg); padding:20px; display:flex; flex-direction:column; gap:16px;">
        <label style="display:flex; flex-direction:column; gap:6px;">
          <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">Objectif *</span>
          <textarea
            rows="3"
            [value]="objective()"
            (input)="objective.set($any($event.target).value)"
            placeholder="Ex. Capturer la méthode d'analyse géotechnique d'un lot avant terrassement."
            style="resize:vertical; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); color:var(--ck-fg-1); font-family:var(--ck-font-sans); font-size:14px; line-height:1.5; padding:10px 12px;"
          ></textarea>
        </label>

        <div style="display:grid; grid-template-columns:1fr 1fr; gap:14px;">
          <label style="display:flex; flex-direction:column; gap:6px;">
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">Titre</span>
            <input
              [value]="title()"
              (input)="title.set($any($event.target).value)"
              placeholder="Titre de la séance"
              style="border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); color:var(--ck-fg-1); font-family:var(--ck-font-sans); font-size:14px; padding:9px 12px;"
            />
          </label>
          <label style="display:flex; flex-direction:column; gap:6px;">
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">Profil expert</span>
            <input
              [value]="expertProfile()"
              (input)="expertProfile.set($any($event.target).value)"
              placeholder="Ex. Ingénieur géotechnicien senior"
              style="border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); color:var(--ck-fg-1); font-family:var(--ck-font-sans); font-size:14px; padding:9px 12px;"
            />
          </label>
        </div>

        <label style="display:flex; flex-direction:column; gap:6px; max-width:220px;">
          <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">Durée (min)</span>
          <input
            type="number"
            min="0"
            [value]="duration()"
            (input)="duration.set(toNumber($any($event.target).value))"
            style="border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); color:var(--ck-fg-1); font-family:var(--ck-font-mono); font-size:14px; padding:9px 12px;"
          />
        </label>

        <div style="display:flex; flex-direction:column; gap:8px;">
          <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">Mode</span>
          <div style="display:flex; gap:10px; flex-wrap:wrap;">
            @for (m of modes; track m.id) {
              <button
                type="button"
                (click)="mode.set(m.id)"
                style="flex:1; min-width:180px; text-align:left; padding:12px 14px; border-radius:var(--ck-radius-md); cursor:pointer; background:var(--ck-bg-inset);"
                [style.border]="'1px solid ' + (mode() === m.id ? 'var(--ck-signal-cool)' : 'var(--ck-stroke-2)')"
              >
                <div style="font-size:13px; font-weight:600;" [style.color]="mode() === m.id ? 'var(--ck-signal-cool)' : 'var(--ck-fg-1)'">{{ m.label }}</div>
                <div style="font-size:11.5px; color:var(--ck-fg-4); margin-top:3px; line-height:1.4;">{{ m.hint }}</div>
              </button>
            }
          </div>
        </div>
      </div>

      @if (error()) {
        <div style="display:flex; align-items:center; gap:8px; color:var(--ck-signal-neg); font-size:12.5px;">
          <ck-glyph name="warn" [size]="14" color="currentColor" /> {{ error() }}
        </div>
      }

      <div style="display:flex; align-items:center; gap:14px;">
        <button
          type="button"
          (click)="prepare()"
          [disabled]="!canSubmit() || busy()"
          style="display:inline-flex; align-items:center; gap:7px; padding:11px 18px; border-radius:var(--ck-radius-md); border:none; font-size:14px; font-weight:600; background:color-mix(in oklab, var(--ck-signal-cool) 88%, transparent); color:var(--ck-on-signal);"
          [style.opacity]="!canSubmit() || busy() ? 0.5 : 1"
          [style.cursor]="!canSubmit() || busy() ? 'not-allowed' : 'pointer'"
        >
          <ck-glyph name="arrow-right" [size]="14" color="currentColor" />
          {{ busy() ? 'Préparation…' : 'Préparer la séance' }}
        </button>
      </div>
    </div>
  `,
})
export class CaptureFilPrepComponent {
  protected readonly engine = inject(CaptureEngine);
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** Asks the shell to advance to the next surface once the plan exists. */
  @Output() planReady = new EventEmitter<'plan' | 'session'>();

  protected readonly modes: ModeOption[] = [
    { id: 'ai_plan', label: 'Plan assisté', hint: "L'oracle propose un plan de topics à valider." },
    { id: 'free_conversation', label: 'Conversation libre', hint: 'Pas de plan — on capture au fil de la parole.' },
    { id: 'plan_build', label: 'Plan dialogué', hint: 'Construire le plan en dialogue avant de capturer.' },
  ];

  protected readonly objective = signal('');
  protected readonly title = signal('');
  protected readonly expertProfile = signal('');
  protected readonly duration = signal(20);
  protected readonly mode = signal<PlanMode>('ai_plan');
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly canSubmit = computed(() => this.objective().trim().length > 0);

  protected toNumber(value: string): number {
    const n = Number.parseInt(value, 10);
    return Number.isFinite(n) && n >= 0 ? n : 0;
  }

  protected prepare(): void {
    if (!this.canSubmit() || this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    const body: CapturePlanRequest = {
      objective: this.objective().trim(),
      title: this.title().trim() || this.objective().trim().slice(0, 60),
      expert_profile: this.expertProfile().trim() || null,
      duration_minutes: this.duration(),
      voice_runtime: 'cascade_openai',
      plan_mode: this.mode(),
    };
    this.api
      .createCapturePlan(body)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          const session = payload as Record<string, unknown>;
          const info: CaptureSessionInfo = {
            id: String(session['id'] ?? ''),
            title: (session['title'] as string) ?? this.title(),
            objective: (session['objective'] as string) ?? this.objective(),
            status: (session['status'] as string) ?? 'planning',
            duration_minutes: (session['duration_minutes'] as number) ?? this.duration(),
            plan: (session['plan'] as Record<string, unknown>) ?? null,
          };
          this.engine.setSession(info);
          void this.engine.loadDocuments();
          this.busy.set(false);
          this.planReady.emit(this.mode() === 'free_conversation' ? 'session' : 'plan');
        },
        error: () => {
          this.busy.set(false);
          this.error.set('Préparation impossible. Vérifiez le backend, puis réessayez.');
        },
      });
  }
}
