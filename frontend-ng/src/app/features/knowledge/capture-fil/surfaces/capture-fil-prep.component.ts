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

/**
 * Capture plan modes — aligned 1:1 with the v0 monolith (`with plan` /
 * `without plan`). The 3rd "ai_plan" mode was an out-of-scope addition; ADR 0001
 * only mandated re-skinning the v0 prep, not redesigning it.
 */
type PlanMode = 'plan_build' | 'free_conversation';

interface ModeOption {
  id: PlanMode;
  label: string;
  hint: string;
}

/**
 * Prep surface — frames the session before capture. Mirrors the v0 semantics
 * (mandatory **title** + indicative **duration** + 2 modes); the objective is
 * derived from the title server-side intent, never a required field. On submit
 * it creates the plan, binds the session to the shared {@link CaptureEngine} and
 * advances to the launch surface (where the plan is built and the capture is
 * explicitly started).
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
          Un titre suffit pour démarrer. Avec un plan, vous le construisez ensuite (dictée, assistant, import de
          document) avant de lancer la capture.
        </p>
      </div>

      <div class="ck-surface" style="border-radius:var(--ck-radius-lg); padding:20px; display:flex; flex-direction:column; gap:16px;">
        <label style="display:flex; flex-direction:column; gap:6px;">
          <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">Titre de la séance *</span>
          <input
            [value]="title()"
            (input)="title.set($any($event.target).value)"
            placeholder="Ex. Méthode d'analyse géotechnique avant terrassement"
            style="border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); color:var(--ck-fg-1); font-family:var(--ck-font-sans); font-size:14px; padding:9px 12px;"
          />
        </label>

        <label style="display:flex; flex-direction:column; gap:6px; max-width:220px;">
          <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">Durée indicative (min)</span>
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
                style="flex:1; min-width:220px; text-align:left; padding:12px 14px; border-radius:var(--ck-radius-md); cursor:pointer; background:var(--ck-bg-inset);"
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

  /** Asks the shell to advance to the launch surface once the plan exists. */
  @Output() planReady = new EventEmitter<'plan' | 'session'>();

  protected readonly modes: ModeOption[] = [
    {
      id: 'plan_build',
      label: 'Avec plan',
      hint: 'Construire un plan de sujets en amont (dictée, assistant, import de document), puis capturer.',
    },
    {
      id: 'free_conversation',
      label: 'Sans plan',
      hint: 'Capturer directement au fil de la conversation, sans plan préalable.',
    },
  ];

  protected readonly title = signal('');
  protected readonly duration = signal(20);
  protected readonly mode = signal<PlanMode>('plan_build');
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly canSubmit = computed(() => this.title().trim().length > 0);

  protected toNumber(value: string): number {
    const n = Number.parseInt(value, 10);
    return Number.isFinite(n) && n >= 0 ? n : 0;
  }

  /** Derive the objective from the title (v0 `captureObjectiveForPlan`). */
  private objectiveFor(title: string): string {
    return `Capturer les savoirs métier et retours d'expérience liés à : ${title}.`;
  }

  protected prepare(): void {
    if (!this.canSubmit() || this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    const title = this.title().trim();
    const body: CapturePlanRequest = {
      objective: this.objectiveFor(title),
      title,
      duration_minutes: this.duration(),
      voice_runtime: 'cascade_openai',
      plan_mode: this.mode(),
      system_id: this.engine.systemId(),
    };
    this.api
      .createCapturePlan(body)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          const session = payload as Record<string, unknown>;
          const info: CaptureSessionInfo = {
            id: String(session['id'] ?? ''),
            title: (session['title'] as string) ?? title,
            objective: (session['objective'] as string) ?? this.objectiveFor(title),
            status: (session['status'] as string) ?? 'planning',
            duration_minutes: (session['duration_minutes'] as number) ?? this.duration(),
            plan: (session['plan'] as Record<string, unknown>) ?? null,
            plan_mode: this.mode(),
            system_id: (session['system_id'] as string | null) ?? this.engine.systemId(),
          };
          this.engine.setSession(info);
          void this.engine.loadDocuments();
          this.busy.set(false);
          // Both modes route to the launch surface: it builds the plan (with
          // plan) or simply confirms (free), and owns the single explicit Start.
          this.planReady.emit('plan');
        },
        error: () => {
          this.busy.set(false);
          this.error.set('Préparation impossible. Vérifiez le backend, puis réessayez.');
        },
      });
  }
}
