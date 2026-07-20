import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Output,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ApiService, type CapturePlanRequest } from '@app/core/api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { CaptureEngine, type CaptureSessionInfo } from '../capture-engine';
import {
  applicableTemplateFields,
  asCheckboxGroup,
  asStringArray,
  captureTemplateSystemReady,
  composeTemplateSessionTitle,
  headerValueAsDisplay,
  isHeaderFieldFilled,
  planSeedToProvidedText,
  resolveInterventionType,
  seedHeaderDefaults,
  templateWithInterventionType,
  toCheckboxGroupPayload,
  weekLabelFromIsoDate,
  type CaptureHeaderValue,
  type CaptureTemplateField,
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

/** Fields filled during finalize (progress table is voice-driven). */
const PREP_DEFERRED_KINDS = new Set(['equipment_progress']);

/**
 * Prep surface — frames the session before capture. Mirrors the v0 semantics
 * (mandatory **title** + indicative **duration** + 2 modes); the objective is
 * derived from the title server-side intent, never a required field. On submit
 * it creates the plan, binds the session to the shared {@link CaptureEngine} and
 * advances to the launch surface (where the plan is built and the capture is
 * explicitly started).
 *
 * When a CaptureTemplate is active (e.g. FSE), the free title/mode picker is
 * replaced by intervention-type cards + required header fields; free conversation
 * is hidden when `ui.hide_free_mode`.
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
            Choisissez le type de rapport (trame EX70), puis renseignez l’en-tête du {{ tpl.label }}.
            Le plan type suit le type choisi ; la capture reste guidée (Fil + Scène + oracle).
          } @else {
            Un titre suffit pour démarrer. Avec un plan, vous le construisez ensuite (dictée, assistant, import de
            document) avant de lancer la capture.
          }
        </p>
      </div>

      @if (previousReportOpenCount() > 0) {
        <div style="display:flex; gap:10px; align-items:flex-start; padding:12px 14px; border-radius:var(--ck-radius-md); background:color-mix(in oklab, var(--ck-signal-warn) 10%, transparent); border:1px solid color-mix(in oklab, var(--ck-signal-warn) 35%, transparent);">
          <ck-glyph name="warn" [size]="15" color="var(--ck-signal-warn)" />
          <div style="font-size:13px; color:var(--ck-fg-2); line-height:1.5;">
            {{ previousReportOpenCount() }} point{{ previousReportOpenCount() > 1 ? 's' : '' }} ouvert{{ previousReportOpenCount() > 1 ? 's' : '' }}
            repris du rapport N-1 — à traiter ou clôturer pendant la séance.
          </div>
        </div>
      }

      <div class="ck-surface" style="border-radius:var(--ck-radius-lg); padding:20px; display:flex; flex-direction:column; gap:16px;">
        @if (template(); as tpl) {
          @if (interventionTypes().length) {
            <div style="display:flex; flex-direction:column; gap:8px;">
              <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">
                Type d’intervention *
              </span>
              <div style="display:flex; gap:10px; flex-wrap:wrap;">
                @for (t of interventionTypes(); track t.id) {
                  <button
                    type="button"
                    (click)="selectInterventionType(t.id)"
                    style="flex:1; min-width:180px; text-align:left; padding:12px 14px; border-radius:var(--ck-radius-md); cursor:pointer; background:var(--ck-bg-inset);"
                    [style.border]="'1px solid ' + (interventionTypeId() === t.id ? 'var(--ck-signal-cool)' : 'var(--ck-stroke-2)')"
                  >
                    <div style="font-size:13px; font-weight:600;" [style.color]="interventionTypeId() === t.id ? 'var(--ck-signal-cool)' : 'var(--ck-fg-1)'">
                      {{ t.label }}
                    </div>
                    <div class="ck-mono" style="font-size:10.5px; color:var(--ck-fg-4); margin-top:4px; letter-spacing:0.04em;">
                      {{ t.doc_ref }}
                    </div>
                  </button>
                }
              </div>
            </div>
          }

          @for (field of prepFields(); track field.key) {
            <div style="display:flex; flex-direction:column; gap:6px;">
              <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">
                {{ field.label }}{{ field.required ? ' *' : '' }}
              </span>
              @if (field.kind === 'select_multi') {
                <div style="display:flex; flex-direction:column; gap:6px; padding:10px 12px; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset);">
                  @for (opt of field.options || []; track opt.value) {
                    <label style="display:flex; align-items:center; gap:8px; font-size:13px; color:var(--ck-fg-2); cursor:pointer;">
                      <input
                        type="checkbox"
                        [checked]="isMultiSelected(field.key, opt.value)"
                        (change)="toggleMulti(field.key, opt.value, $any($event.target).checked)"
                      />
                      {{ opt.label }}
                    </label>
                  }
                </div>
              } @else if (field.kind === 'checkbox_group') {
                <div style="display:flex; flex-direction:column; gap:6px; padding:10px 12px; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset);">
                  @for (opt of field.options || []; track opt.value) {
                    <label style="display:flex; align-items:center; gap:8px; font-size:13px; color:var(--ck-fg-2); cursor:pointer;">
                      <input
                        type="checkbox"
                        [checked]="isCheckboxSelected(field.key, opt.value)"
                        (change)="toggleCheckbox(field.key, opt.value, $any($event.target).checked)"
                      />
                      {{ opt.label }}
                    </label>
                  }
                  @if (needsCheckboxDescription(field.key)) {
                    <input
                      [value]="checkboxDescription(field.key)"
                      (input)="setCheckboxDescription(field.key, $any($event.target).value)"
                      placeholder="Description des modifications *"
                      style="margin-top:4px; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-base); color:var(--ck-fg-1); font-size:13px; padding:8px 10px;"
                    />
                  }
                </div>
              } @else {
                <input
                  [type]="field.kind === 'date' ? 'date' : 'text'"
                  [value]="headerFieldText(field.key)"
                  (input)="setHeaderField(field.key, $any($event.target).value)"
                  [placeholder]="
                    field.key === 'hse_safety'
                      ? 'None / rien à signaler'
                      : field.key === 'week'
                        ? 'W28'
                        : field.key === 'issued_by'
                          ? 'Superviseur / auteur'
                          : field.label
                  "
                  style="border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-md); background:var(--ck-bg-inset); color:var(--ck-fg-1); font-family:var(--ck-font-sans); font-size:14px; padding:9px 12px;"
                />
              }
            </div>
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
              Mode plan type
              @if (activeIntervention(); as it) {
                · {{ it.label }} ({{ it.doc_ref }})
              }
              — conversation libre désactivée pour ce rapport.
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
          {{ waitingForSystem() ? 'Connexion au système FSE…' : (busy() ? 'Préparation…' : 'Préparer la séance') }}
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
  protected readonly headerValues = signal<Record<string, CaptureHeaderValue>>({});
  protected readonly interventionTypeId = signal<string | null>(null);
  private seededForTemplateId: string | null = null;

  protected readonly template = this.engine.template;
  protected readonly previousReportOpenCount = this.engine.previousReportOpenCount;
  protected readonly hideFreeMode = computed(
    () => Boolean(this.template()?.ui.hide_free_mode),
  );
  protected readonly waitingForSystem = computed(
    () => !captureTemplateSystemReady(this.template(), this.engine.systemId()),
  );
  protected readonly interventionTypes = computed(
    () => this.template()?.intervention_types ?? [],
  );
  protected readonly activeIntervention = computed(() =>
    resolveInterventionType(this.template(), this.interventionTypeId()),
  );
  protected readonly prepFields = computed(() => {
    const tpl = this.template();
    if (!tpl) return [] as CaptureTemplateField[];
    return applicableTemplateFields(tpl, this.interventionTypeId()).filter(
      (f) => !PREP_DEFERRED_KINDS.has(f.kind),
    );
  });

  protected readonly canSubmit = computed(() => {
    const tpl = this.template();
    if (!tpl) return this.title().trim().length > 0;
    if (!captureTemplateSystemReady(tpl, this.engine.systemId())) return false;
    if (tpl.intervention_types?.length && !this.interventionTypeId()) return false;
    const values = this.headerValues();
    return this.prepFields()
      .filter((f) => f.required)
      .every((f) => isHeaderFieldFilled(f, values[f.key]));
  });

  constructor() {
    effect(() => {
      const tpl = this.template();
      if (!tpl) {
        this.seededForTemplateId = null;
        return;
      }
      if (this.seededForTemplateId === tpl.id) return;
      this.seededForTemplateId = tpl.id;
      const typeId =
        this.engine.interventionTypeId()
        || resolveInterventionType(tpl, null)?.id
        || null;
      this.interventionTypeId.set(typeId);
      this.engine.setInterventionTypeId(typeId);
      const defaults = seedHeaderDefaults(tpl, typeId);
      const existing = this.engine.headerFields();
      this.headerValues.set({ ...defaults, ...existing });
    });
  }

  protected selectInterventionType(typeId: string): void {
    const tpl = this.template();
    if (!tpl) return;
    this.interventionTypeId.set(typeId);
    this.engine.setInterventionTypeId(typeId);
    const defaults = seedHeaderDefaults(tpl, typeId);
    this.headerValues.update((prev) => {
      const next = { ...defaults };
      for (const [key, value] of Object.entries(prev)) {
        const display = headerValueAsDisplay(value);
        const isEmptyDefault =
          !display
          || (typeof defaults[key] === 'string' && display === headerValueAsDisplay(defaults[key]));
        // Keep operator-entered cartouche values across type switches.
        if (key in defaults && !isCartoucheKey(key) && isEmptyDefault) continue;
        if (value !== undefined && value !== '') next[key] = value;
      }
      // Re-apply type-specific defaults when the previous value was still the old default.
      for (const field of applicableTemplateFields(tpl, typeId)) {
        if (field.default === undefined) continue;
        if (!(field.key in prev) || headerValueAsDisplay(prev[field.key]) === '') {
          next[field.key] = field.default;
        }
      }
      return next;
    });
  }

  protected headerFieldText(key: string): string {
    return headerValueAsDisplay(this.headerValues()[key]);
  }

  protected setHeaderField(key: string, value: string): void {
    this.headerValues.update((prev) => {
      const next: Record<string, CaptureHeaderValue> = { ...prev, [key]: value };
      // Auto-suggest ISO week when the intervention date changes and week is empty
      // or still matches the previous date-derived label.
      if (key === 'intervention_date') {
        const suggested = weekLabelFromIsoDate(value);
        const prevWeek = headerValueAsDisplay(prev['week']);
        const prevDateWeek = weekLabelFromIsoDate(headerValueAsDisplay(prev['intervention_date']));
        if (suggested && (!prevWeek || prevWeek === prevDateWeek)) {
          next['week'] = suggested;
        }
      }
      return next;
    });
  }

  protected isMultiSelected(key: string, option: string): boolean {
    return asStringArray(this.headerValues()[key]).includes(option);
  }

  protected toggleMulti(key: string, option: string, checked: boolean): void {
    this.headerValues.update((prev) => {
      const current = asStringArray(prev[key]);
      const next = checked
        ? (current.includes(option) ? current : [...current, option])
        : current.filter((v) => v !== option);
      return { ...prev, [key]: next };
    });
  }

  protected isCheckboxSelected(key: string, option: string): boolean {
    return asCheckboxGroup(this.headerValues()[key]).values.includes(option);
  }

  protected checkboxDescription(key: string): string {
    return asCheckboxGroup(this.headerValues()[key]).description;
  }

  protected needsCheckboxDescription(key: string): boolean {
    return asCheckboxGroup(this.headerValues()[key]).values.some((v) => v !== 'none');
  }

  protected toggleCheckbox(key: string, option: string, checked: boolean): void {
    this.headerValues.update((prev) => {
      const group = asCheckboxGroup(prev[key]);
      let values = [...group.values];
      if (option === 'none' && checked) {
        values = ['none'];
      } else if (checked) {
        values = values.filter((v) => v !== 'none');
        if (!values.includes(option)) values.push(option);
      } else {
        values = values.filter((v) => v !== option);
      }
      return { ...prev, [key]: toCheckboxGroupPayload(values, group.description) };
    });
  }

  protected setCheckboxDescription(key: string, description: string): void {
    this.headerValues.update((prev) => {
      const group = asCheckboxGroup(prev[key]);
      return { ...prev, [key]: toCheckboxGroupPayload(group.values, description) };
    });
  }

  protected toNumber(value: string): number {
    const n = Number.parseInt(value, 10);
    return Number.isFinite(n) && n >= 0 ? n : 0;
  }

  /** Derive the objective from the title (v0 `captureObjectiveForPlan`). */
  private objectiveFor(title: string): string {
    return `Capturer les savoirs métier et retours d'expérience liés à : ${title}.`;
  }

  private objectiveForTemplate(fields: Record<string, CaptureHeaderValue>, label: string): string {
    const title = composeTemplateSessionTitle(fields, label);
    return `Produire le ${label} pour : ${title}.`;
  }

  protected prepare(): void {
    if (!this.canSubmit() || this.busy()) return;
    this.busy.set(true);
    this.error.set(null);

    const tpl = this.template();
    const typeId = this.interventionTypeId();
    const activeTpl = tpl && typeId ? templateWithInterventionType(tpl, typeId) : tpl;
    const headerFields = { ...this.headerValues() };
    // Ensure deferred structured defaults travel with the session create.
    if (tpl) {
      const defaults = seedHeaderDefaults(tpl, typeId);
      for (const [key, value] of Object.entries(defaults)) {
        if (headerFields[key] === undefined) headerFields[key] = value;
      }
    }
    const title = activeTpl
      ? composeTemplateSessionTitle(headerFields, activeTpl.label)
      : this.title().trim();
    const planMode: string = activeTpl
      ? 'provided_plan'
      : this.mode();

    const body: CapturePlanRequest = {
      objective: activeTpl
        ? this.objectiveForTemplate(headerFields, activeTpl.label)
        : this.objectiveFor(title),
      title,
      duration_minutes: this.duration(),
      voice_runtime: 'cascade_openai',
      plan_mode: planMode,
      system_id: this.engine.systemId(),
    };

    if (activeTpl) {
      if (typeId) headerFields['intervention_type'] = typeId;
      body.template_id = activeTpl.id;
      body.header_fields = headerFields;
      body.intervention_type = typeId;
      body.provided_plan_text = planSeedToProvidedText(activeTpl);
      body.plan_source_kind = 'manual';
      body.plan_source_replaces_existing_plan = true;
      this.engine.setHeaderFields(headerFields);
      this.engine.setInterventionTypeId(typeId);
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
              ?? (activeTpl
                ? this.objectiveForTemplate(headerFields, activeTpl.label)
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

function isCartoucheKey(key: string): boolean {
  return [
    'customer',
    'country',
    'site_or_machine',
    'reference',
    'participants',
    'issued_by',
    'intervention_date',
    'week',
  ].includes(key);
}
