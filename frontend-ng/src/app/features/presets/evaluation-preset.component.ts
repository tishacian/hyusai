import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import {
  CanonicalApiService,
  type EvaluationPresetConfig,
  type EvaluationPresetResponse,
} from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { WriteOutcomeComponent } from '@app/shared/ui/write-outcome.component';
import {
  LOADING,
  STRICT,
  settleRead,
  settleWrite,
  type LoadState,
  type WriteOutcome,
} from '@app/shared/ui/load-state';
import {
  GlyphComponent,
  NavLinkDirective,
  PageFrameComponent,
  TagComponent,
} from '@app/shared/cockpit';

/** Deferred i18n lookup, so a stored validation error re-renders on language flip. */
interface DimensionMinError {
  key: string;
  params?: Record<string, string | number>;
}

/**
 * Presets · Evaluation thresholds — Vague E / E1.
 *
 * Single-page form that edits the workspace-scoped
 * :class:`EvaluationPreset`. Three knobs are surfaced :
 *
 * - **enabled** — master kill-switch. On by default since E1.5.4;
 *   workspace admins can opt out by turning it off.
 * - **composite_min** — 0-100 floor on the LLM judge's composite
 *   score. A run below this number trips `review_required`.
 * - **hallucination_max** — 0-1 ceiling on the unsupported-claim
 *   rate. Above triggers the same review decision.
 *
 * The ``dimension_min`` and ``sample_rate`` knobs are edited as JSON
 * (power-user mode) so we can iterate on the default shape without
 * rebuilding the UI every time.
 */
@Component({
  selector: 'app-evaluation-preset',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    NavLinkDirective,
    PageFrameComponent,
    GlyphComponent,
    TagComponent,
    EmptyStateComponent,
    WriteOutcomeComponent,
  ],
  template: `
    <ck-page-frame
      [eyebrow]="i18n.t('presets.evaluation.eyebrow')"
      [title]="i18n.t('presets.evaluation.title')"
      [description]="i18n.t('presets.evaluation.description')"
    >
      <div class="flex flex-col gap-5" style="max-width:780px;">
        <app-empty-state
          [state]="readState()"
          [title]="i18n.t('presets.evaluation.empty.title')"
          [description]="i18n.t('presets.evaluation.empty.description')"
          icon="crosshair"
          (retry)="load()"
        />
        @if (hasValues()) {
          <!-- Master switch -->
          <section class="ck-surface rounded-md" style="padding:20px 24px;">
            <div class="flex flex-wrap items-start justify-between gap-6">
              <div class="flex-1" style="min-width:min(100%, 240px);">
                <div class="flex items-center gap-2 mb-2">
                  <ck-glyph name="pulse" [size]="14" />
                  <h3
                    class="ck-mono"
                    style="font-size:11px; letter-spacing:0.18em; text-transform:uppercase; color:var(--ck-fg-2);"
                  >
                    {{ i18n.t('presets.evaluation.master.title') }}
                  </h3>
                  <ck-tag [tone]="enabled() ? 'pos' : 'neutral'" variant="soft">
                    {{ enabled() ? i18n.t('presets.state.on') : i18n.t('presets.state.off') }}
                  </ck-tag>
                </div>
                <p class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); line-height:1.6;">
                  {{ i18n.t('presets.evaluation.master.body1') }}
                  <a [navLink]="{ surface: 'review-queue' }" style="color:var(--ck-primary); text-decoration:underline;">{{ i18n.t('presets.evaluation.master.queue') }}</a>{{ i18n.t('presets.evaluation.master.body2') }}
                </p>
              </div>
              <label
                class="flex items-center gap-2 cursor-pointer"
                style="padding:8px 14px; border:1px solid var(--ck-stroke-soft); border-radius:4px; background:var(--ck-bg-inset);"
              >
                <input
                  type="checkbox"
                  [checked]="enabled()"
                  [disabled]="!editable()"
                  (change)="toggleEnabled($event)"
                  class="accent-emerald-400"
                />
                <span
                  class="ck-mono"
                  style="font-size:11px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-1);"
                >
                  {{ i18n.t('presets.evaluation.enable') }}
                </span>
              </label>
            </div>
          </section>

          <!-- Thresholds -->
          <section class="ck-surface rounded-md" style="padding:22px 26px;">
            <div class="flex items-center gap-2 mb-5">
              <ck-glyph name="crosshair" [size]="14" />
              <h3
                class="ck-mono"
                style="font-size:11px; letter-spacing:0.18em; text-transform:uppercase; color:var(--ck-fg-2);"
              >
                {{ i18n.t('presets.evaluation.thresholds.title') }}
              </h3>
            </div>
            @if (!enabled()) {
              <p class="text-xs mb-4" style="color:var(--ck-fg-3);" data-testid="preset-thresholds-off">
                {{ i18n.t('presets.evaluation.thresholds.off') }}
              </p>
            }

            <!-- composite_min -->
            <div class="mb-6">
              <div class="flex items-center justify-between mb-2">
                <label for="preset-composite" class="ck-mono" style="font-size:11px; color:var(--ck-fg-2);">
                  {{ i18n.t('presets.evaluation.composite.label') }}
                </label>
                <span
                  class="ck-mono ck-tnum"
                  style="font-size:13px;"
                  [style.color]="compositeTone()"
                >
                  {{ composite().toFixed(0) }} / 100
                </span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                step="1"
                id="preset-composite"
                aria-describedby="preset-composite-hint"
                [ngModel]="composite()"
                (ngModelChange)="composite.set($event); markDirty()"
                [disabled]="!enabled() || !editable()"
                class="w-full accent-emerald-400"
              />
              <div
                class="flex justify-between ck-mono"
                style="font-size:11px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-3); margin-top:4px;"
              >
                <span>{{ i18n.t('presets.evaluation.scale.permissive') }}</span>
                <span>{{ i18n.t('presets.evaluation.scale.strict') }}</span>
              </div>
              <p id="preset-composite-hint" class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); margin-top:6px;">
                {{ i18n.t('presets.evaluation.composite.hint') }}
              </p>
            </div>

            <!-- hallucination_max -->
            <div class="mb-6">
              <div class="flex items-center justify-between mb-2">
                <label for="preset-hallucination" class="ck-mono" style="font-size:11px; color:var(--ck-fg-2);">
                  {{ i18n.t('presets.evaluation.hallucination.label') }}
                </label>
                <span
                  class="ck-mono ck-tnum"
                  style="font-size:13px;"
                  [style.color]="hallucinationTone()"
                >
                  {{ (hallucination() * 100).toFixed(0) }}%
                </span>
              </div>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                id="preset-hallucination"
                aria-describedby="preset-hallucination-hint"
                [ngModel]="hallucination()"
                (ngModelChange)="hallucination.set($event); markDirty()"
                [disabled]="!enabled() || !editable()"
                class="w-full accent-amber-400"
              />
              <div
                class="flex justify-between ck-mono"
                style="font-size:11px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-3); margin-top:4px;"
              >
                <span>{{ i18n.t('presets.evaluation.hallucination.strict') }}</span>
                <span>{{ i18n.t('presets.evaluation.hallucination.permissive') }}</span>
              </div>
              <p id="preset-hallucination-hint" class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); margin-top:6px;">
                {{ i18n.t('presets.evaluation.hallucination.hint') }}
              </p>
            </div>

            <!-- sample_rate -->
            <div class="mb-6">
              <div class="flex items-center justify-between mb-2">
                <label for="preset-sampling" class="ck-mono" style="font-size:11px; color:var(--ck-fg-2);">
                  {{ i18n.t('presets.evaluation.sampling.label') }}
                </label>
                <span class="ck-mono ck-tnum" style="font-size:13px; color:var(--ck-fg-1);">
                  {{ (sampleRate() * 100).toFixed(0) }}%
                </span>
              </div>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                id="preset-sampling"
                aria-describedby="preset-sampling-hint"
                [ngModel]="sampleRate()"
                (ngModelChange)="sampleRate.set($event); markDirty()"
                [disabled]="!enabled() || !editable()"
                class="w-full accent-cyan-400"
              />
              <p id="preset-sampling-hint" class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); margin-top:6px;">
                {{ i18n.t('presets.evaluation.sampling.hint') }}
              </p>
            </div>

            <!-- Dimension minimums (power user) -->
            <details style="margin-top:16px; padding-top:16px; border-top:1px solid var(--ck-hair);">
              <summary
                class="ck-mono cursor-pointer"
                style="font-size:11px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-3);"
              >
                {{ i18n.t('presets.evaluation.dimensions.title') }}
              </summary>
              <textarea
                [attr.aria-label]="i18n.t('presets.evaluation.dimensions.title')"
                aria-describedby="preset-dimensions-hint"
                [ngModel]="dimensionMinJson()"
                (ngModelChange)="updateDimensionMinJson($event)"
                [disabled]="!enabled() || !editable()"
                rows="6"
                class="w-full ck-mono"
                style="margin-top:10px; padding:10px; background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-soft); border-radius:4px; font-size:11px; color:var(--ck-fg-1); resize:vertical;"
                placeholder='{"safety": 80.0, "hallucination": 50.0}'
              ></textarea>
              @if (dimensionMinError()) {
                <div class="ck-mono" role="alert" style="font-size:11px; color:var(--ck-status-neg-fg); margin-top:4px;">
                  {{ dimensionMinErrorLabel() }}
                </div>
              }
              <p id="preset-dimensions-hint" class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); margin-top:6px;">
                {{ i18n.t('presets.evaluation.dimensions.hint') }}
              </p>
            </details>
          </section>

          <!-- Save bar -->
          <section
            class="ck-surface rounded-md"
            style="padding:14px 22px; display:flex; flex-wrap:wrap; align-items:center; gap:14px;"
          >
            @if (dirty()) {
              <ck-tag tone="warn" variant="soft" data-testid="preset-unsaved">{{ i18n.t('presets.evaluation.tag.unsaved') }}</ck-tag>
            } @else {
              <ck-tag tone="pos" variant="soft" data-testid="preset-synced">{{ i18n.t('presets.evaluation.tag.synced') }}</ck-tag>
            }
            <span class="flex flex-col gap-1">
              <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-3);">
                {{ i18n.t('presets.evaluation.scope.hint') }}
              </span>
              <app-write-outcome
                [outcome]="writeOutcome()"
                [confirmedLabel]="i18n.t('presets.evaluation.save.confirmed')"
                [failedLabel]="i18n.t('presets.evaluation.save.failed')"
                [verifiable]="true"
                (verify)="verify()"
              />
            </span>
            <span class="ml-auto flex flex-wrap items-center gap-2">
              <a
                [navLink]="{ surface: 'review-queue' }"
                class="ck-btn ck-btn-quiet"
              >
                {{ i18n.t('presets.evaluation.queue.cta') }}
              </a>
              <button
                type="button"
                (click)="save()"
                [disabled]="!canSave()"
                data-testid="preset-save"
                class="ck-btn ck-cta"
              >
                {{ saving() ? i18n.t('presets.saving') : i18n.t('presets.evaluation.save.cta') }}
              </button>
            </span>
          </section>
        }
      </div>
    </ck-page-frame>
  `,
})
export class EvaluationPresetComponent implements OnInit {
  private readonly canonical = inject(CanonicalApiService);
  private readonly destroyRef = inject(DestroyRef);
  readonly i18n = inject(I18nService);

  /** What the server said about the preset. The form only ever shows its values. */
  readonly readState = signal<LoadState<EvaluationPresetResponse>>(LOADING);
  /** Outcome of the last save; nothing is "saved" before the server confirms it. */
  readonly writeOutcome = signal<WriteOutcome | null>(null);
  readonly saving = computed(() => this.writeOutcome()?.s === 'sent');
  readonly dirty = signal(false);

  /** The form is shown from server values only: never after a read that failed first. */
  readonly hasValues = computed(() => {
    const state = this.readState();
    return state.s === 'ready' || (state.s === 'error' && !!state.last);
  });
  /** Editing needs a fresh read: after a failed refresh the last values stay visible, read-only. */
  readonly editable = computed(() => this.readState().s === 'ready');
  readonly canSave = computed(() =>
    this.editable()
    && this.dirty()
    && !this.saving()
    && !this.dimensionMinError()
    && this.writeOutcome()?.s !== 'unknown');

  readonly enabled = signal(false);
  readonly composite = signal(0);
  readonly hallucination = signal(0);
  readonly sampleRate = signal(0);
  readonly dimensionMinJson = signal('{}');
  readonly dimensionMinError = signal<DimensionMinError | null>(null);

  readonly dimensionMinErrorLabel = computed(() => {
    const error = this.dimensionMinError();
    return error ? this.i18n.t(error.key, error.params) : '';
  });

  readonly compositeTone = computed(() => {
    const v = this.composite();
    if (v < 40) return 'var(--ck-status-neg-fg)';
    if (v < 60) return 'var(--ck-status-warn-fg)';
    return 'var(--ck-status-ok-fg)';
  });

  readonly hallucinationTone = computed(() => {
    const v = this.hallucination();
    if (v > 0.5) return 'var(--ck-status-neg-fg)';
    if (v > 0.3) return 'var(--ck-status-warn-fg)';
    return 'var(--ck-status-ok-fg)';
  });

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    settleRead(this.canonical.getEvaluationPresets({}, STRICT), {
      previous: this.readState(),
      isEmpty: (response) => !response.effective,
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((state) => {
        this.readState.set(state);
        if (state.s === 'ready') {
          this.apply(state.value.effective);
          this.dirty.set(false);
          this.writeOutcome.set(null);
        }
      });
  }

  /** Shows the values the server holds; a missing field stays empty rather than invented. */
  private apply(effective: Partial<EvaluationPresetConfig>): void {
    this.enabled.set(!!effective.enabled);
    this.composite.set(effective.composite_min ?? 0);
    this.hallucination.set(effective.hallucination_max ?? 0);
    this.sampleRate.set(effective.sample_rate ?? 0);
    this.dimensionMinJson.set(JSON.stringify(effective.dimension_min ?? {}, null, 2));
    this.dimensionMinError.set(null);
  }

  markDirty(): void {
    this.dirty.set(true);
    if (this.writeOutcome()?.s === 'confirmed') this.writeOutcome.set(null);
  }

  toggleEnabled(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.enabled.set(input.checked);
    this.markDirty();
  }

  updateDimensionMinJson(value: string): void {
    this.dimensionMinJson.set(value);
    this.markDirty();
    try {
      const parsed = JSON.parse(value || '{}');
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        this.dimensionMinError.set({ key: 'presets.evaluation.dimensions.error.object' });
        return;
      }
      for (const [k, v] of Object.entries(parsed)) {
        if (typeof v !== 'number') {
          this.dimensionMinError.set({
            key: 'presets.evaluation.dimensions.error.number',
            params: { key: k },
          });
          return;
        }
      }
      this.dimensionMinError.set(null);
    } catch (e) {
      this.dimensionMinError.set({
        key: 'presets.evaluation.dimensions.error.json',
        params: { message: (e as Error).message },
      });
    }
  }

  save(): void {
    if (!this.canSave()) return;
    const body = this.body();
    if (!body) return;
    settleWrite(this.canonical.updateEvaluationPreset(body, STRICT))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((outcome) => {
        this.writeOutcome.set(outcome);
        if (outcome.s === 'confirmed' && outcome.value) {
          // Show what the server stored, not what was sent.
          this.apply(outcome.value.config);
          this.dirty.set(false);
        }
      });
  }

  /**
   * The answer to a save never came: read the preset back and compare it with
   * what was sent, instead of sending it again.
   */
  verify(): void {
    const body = this.body();
    if (!body) return;
    settleRead(this.canonical.getEvaluationPresets({}, STRICT))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((state) => {
        if (state.s === 'loading') {
          this.writeOutcome.set({ s: 'sent' });
          return;
        }
        if (state.s !== 'ready') {
          this.writeOutcome.set({ s: 'unknown', status: null, code: 'verify_failed' });
          return;
        }
        if (sameConfig(state.value.effective, body)) {
          this.writeOutcome.set({ s: 'confirmed', value: state.value, at: state.at });
          this.readState.set(state);
          this.dirty.set(false);
        } else {
          this.writeOutcome.set({ s: 'failed', status: null, code: 'not_applied', detail: null });
        }
      });
  }

  private body(): (Partial<EvaluationPresetConfig> & { name?: string }) | null {
    let dimension_min: Record<string, number> = {};
    try {
      dimension_min = JSON.parse(this.dimensionMinJson() || '{}');
    } catch {
      return null;
    }
    return {
      enabled: this.enabled(),
      composite_min: this.composite(),
      hallucination_max: this.hallucination(),
      sample_rate: this.sampleRate(),
      dimension_min,
    };
  }
}

function sameConfig(stored: Partial<EvaluationPresetConfig>, sent: Partial<EvaluationPresetConfig>): boolean {
  return !!stored.enabled === !!sent.enabled
    && stored.composite_min === sent.composite_min
    && stored.hallucination_max === sent.hallucination_max
    && stored.sample_rate === sent.sample_rate
    && JSON.stringify(stored.dimension_min ?? {}) === JSON.stringify(sent.dimension_min ?? {});
}
