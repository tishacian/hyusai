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
import {
  composeTemplateSessionTitle,
  planSeedToProvidedText,
} from '../capture-templates';

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
 *
 * When a CaptureTemplate is active (e.g. FSE), the free title/mode picker is
 * replaced by the template's required header fields; free conversation is
 * hidden when `ui.hide_free_mode`.
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
        <h2 style="margin:6px 0 4px; font-size:22px; font-weight:680; color:var(--ck-fg-1);">
          {{ template() ? 'Identifier l’intervention' : 'Cadrer la séance' }}
        </h2>
        <p style="margin:0; font-size:13.5px; color:var(--ck-fg-3); line-height:1.55; max-width:62ch;">
          @if (template(); as tpl) {
            Renseignez les champs d’en-tête du {{ tpl.label }}. Le plan type sera pré-appliqué ;
            la capture reste guidée (Fil + Scène + oracle).
          } @else {
            Un titre suffit pour démarrer. Avec un plan, vous le construisez ensuite (dictée, assistant, import de
            document) avant de lancer la capture.
          }
        </p>
      </div>

      <div class="ck-surface" style="border-radius:var(--ck-radius-lg); padding:20px; display:flex; flex-direction:column; gap:16px;">
        @if (template(); as tpl) {
          @for (field of tpl.required_fields; track field.key) {
            <label style="display:flex; flex-direction:column; gap:6px;">
              <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">
                {{ field.label }}{{ field.required ? ' *' : '' }}
              </span>
              <input
                [type]="field.kind === 'date' ? 'date' : 'text'"
                [value]="headerField(field.key)"
                (input)="setHeaderField(field.key, $any($event.target).value)"
                [placeholder]="field.label"
                style="border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); color:var(--ck-fg-1); font-family:var(--ck-font-sans); font-size:14px; padding:9px 12px;"
              />
            </label>
          }
        } @else {
          <label style="display:flex; flex-direction:column; gap:6px;">
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">Titre de la séance *</span>
            <input
              [value]="title()"
              (input)="title.set($any($event.target).value)"
              placeholder="Ex. Méthode d'analyse géotechnique avant terrassement"
              style="border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); color:var(--ck-fg-1); font-family:var(--ck-font-sans); font-size:14px; padding:9px 12px;"
            />
          </label>
        }

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

        @if (!hideFreeMode()) {
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
        } @else if (template()) {
          <div style="display:flex; gap:10px; align-items:flex-start; padding:10px 12px; border-radius:var(--ck-radius-md); background:var(--ck-tint-faint); border:1px solid var(--ck-stroke-2);">
            <ck-glyph name="ledger" [size]="15" color="var(--ck-signal-cool)" />
            <div style="font-size:12.5px; color:var(--ck-fg-3); line-height:1.5;">
              Mode plan type — conversation libre désactivée pour ce rapport.
            </div>
          </div>
        }
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
  protected readonly headerValues = signal<Record<string, string>>({});

  protected readonly template = this.engine.template;
  protected readonly hideFreeMode = computed(
    () => Boolean(this.template()?.ui.hide_free_mode),
  );

  protected readonly canSubmit = computed(() => {
    const tpl = this.template();
    if (!tpl) return this.title().trim().length > 0;
    const values = this.headerValues();
    return tpl.required_fields
      .filter((f) => f.required)
      .every((f) => (values[f.key] || '').trim().length > 0);
  });

  protected headerField(key: string): string {
    return this.headerValues()[key] ?? '';
  }

  protected setHeaderField(key: string, value: string): void {
    this.headerValues.update((prev) => ({ ...prev, [key]: value }));
  }

  protected toNumber(value: string): number {
    const n = Number.parseInt(value, 10);
    return Number.isFinite(n) && n >= 0 ? n : 0;
  }

  /** Derive the objective from the title (v0 `captureObjectiveForPlan`). */
  private objectiveFor(title: string): string {
    return `Capturer les savoirs métier et retours d'expérience liés à : ${title}.`;
  }

  private objectiveForTemplate(fields: Record<string, string>, label: string): string {
    const title = composeTemplateSessionTitle(fields, label);
    return `Produire le ${label} pour : ${title}.`;
  }

  protected prepare(): void {
    if (!this.canSubmit() || this.busy()) return;
    this.busy.set(true);
    this.error.set(null);

    const tpl = this.template();
    const headerFields = { ...this.headerValues() };
    const title = tpl
      ? composeTemplateSessionTitle(headerFields, tpl.label)
      : this.title().trim();
    const planMode: string = tpl
      ? 'provided_plan'
      : this.mode();

    const body: CapturePlanRequest = {
      objective: tpl
        ? this.objectiveForTemplate(headerFields, tpl.label)
        : this.objectiveFor(title),
      title,
      duration_minutes: this.duration(),
      voice_runtime: 'cascade_openai',
      plan_mode: planMode,
      system_id: this.engine.systemId(),
    };

    if (tpl) {
      body.template_id = tpl.id;
      body.header_fields = headerFields;
      body.provided_plan_text = planSeedToProvidedText(tpl);
      body.plan_source_kind = 'manual';
      body.plan_source_replaces_existing_plan = true;
      this.engine.setHeaderFields(headerFields);
    }

    this.api
      .createCapturePlan(body)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          const session = payload as Record<string, unknown>;
          const info: CaptureSessionInfo = {
            id: String(session['id'] ?? ''),
            title: (session['title'] as string) ?? title,
            objective: (session['objective'] as string)
              ?? (tpl
                ? this.objectiveForTemplate(headerFields, tpl.label)
                : this.objectiveFor(title)),
            status: (session['status'] as string) ?? 'planning',
            duration_minutes: (session['duration_minutes'] as number) ?? this.duration(),
            plan: (session['plan'] as Record<string, unknown>) ?? null,
            metrics: (session['metrics'] as Record<string, unknown>) ?? null,
            plan_mode: planMode,
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
