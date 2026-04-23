import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import {
  CanonicalApiService,
  type EvaluationPresetConfig,
  type EvaluationPresetResponse,
} from '@app/core/canonical-api.service';
import {
  GlyphComponent,
  PageFrameComponent,
  TagComponent,
} from '@app/shared/cockpit';

/**
 * Presets · Evaluation thresholds — Vague E / E1.
 *
 * Single-page form that edits the workspace-scoped
 * :class:`EvaluationPreset`. Three knobs are surfaced :
 *
 * - **enabled** — master kill-switch. Off by default so the loop
 *   stays opt-in until a workspace has consciously set thresholds.
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
  imports: [FormsModule, RouterLink, PageFrameComponent, GlyphComponent, TagComponent],
  template: `
    <ck-page-frame
      eyebrow="Presets · Evaluation thresholds"
      title="Auto-evaluation loop"
      description="When a run completes, the LLM-as-judge scores it in the background. Thresholds below decide whether it ends up in the review queue."
    >
      <div class="flex flex-col gap-5" style="max-width:780px;">
        @if (loading()) {
          <div
            class="ck-mono"
            style="font-size:11px; padding:48px; text-align:center; color:var(--ck-fg-4);"
          >
            LOADING…
          </div>
        } @else {
          <!-- Master switch -->
          <section class="ck-surface rounded-md" style="padding:20px 24px;">
            <div class="flex items-start justify-between gap-6">
              <div class="flex-1">
                <div class="flex items-center gap-2 mb-2">
                  <ck-glyph name="pulse" [size]="14" />
                  <h3
                    class="ck-mono"
                    style="font-size:11px; letter-spacing:0.18em; text-transform:uppercase; color:var(--ck-fg-2);"
                  >
                    AUTO-EVALUATION
                  </h3>
                  <ck-tag [tone]="enabled() ? 'pos' : 'neutral'" variant="soft">
                    {{ enabled() ? 'ON' : 'OFF' }}
                  </ck-tag>
                </div>
                <p class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); line-height:1.6;">
                  When enabled, each completed run is scored by the
                  LLM judge after it returns to the user — never on
                  the critical path. Low-score runs surface in the
                  <a routerLink="/steering/review-queue" style="color:var(--ck-signal-cool);">review queue</a>.
                  Budget: ~1 GPT-4o call per eligible run.
                </p>
              </div>
              <label
                class="flex items-center gap-2 cursor-pointer"
                style="padding:8px 14px; border:1px solid var(--ck-stroke-soft); border-radius:4px; background:var(--ck-bg-inset);"
              >
                <input
                  type="checkbox"
                  [checked]="enabled()"
                  (change)="toggleEnabled($event)"
                  class="accent-emerald-400"
                />
                <span
                  class="ck-mono"
                  style="font-size:11px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-1);"
                >
                  ENABLE
                </span>
              </label>
            </div>
          </section>

          <!-- Thresholds -->
          <section
            class="ck-surface rounded-md"
            style="padding:22px 26px;"
            [style.opacity]="enabled() ? '1' : '0.5'"
          >
            <div class="flex items-center gap-2 mb-5">
              <ck-glyph name="crosshair" [size]="14" />
              <h3
                class="ck-mono"
                style="font-size:11px; letter-spacing:0.18em; text-transform:uppercase; color:var(--ck-fg-2);"
              >
                THRESHOLDS
              </h3>
            </div>

            <!-- composite_min -->
            <div class="mb-6">
              <div class="flex items-center justify-between mb-2">
                <label class="ck-mono" style="font-size:11px; color:var(--ck-fg-2);">
                  Composite score minimum
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
                [ngModel]="composite()"
                (ngModelChange)="composite.set($event); markDirty()"
                [disabled]="!enabled()"
                class="w-full accent-emerald-400"
              />
              <div
                class="flex justify-between ck-mono"
                style="font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4); margin-top:4px;"
              >
                <span>PERMISSIVE (0)</span>
                <span>STRICT (100)</span>
              </div>
              <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:6px;">
                Runs with a composite score below this number are flagged. Default 60.
              </p>
            </div>

            <!-- hallucination_max -->
            <div class="mb-6">
              <div class="flex items-center justify-between mb-2">
                <label class="ck-mono" style="font-size:11px; color:var(--ck-fg-2);">
                  Max hallucination rate
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
                [ngModel]="hallucination()"
                (ngModelChange)="hallucination.set($event); markDirty()"
                [disabled]="!enabled()"
                class="w-full accent-amber-400"
              />
              <div
                class="flex justify-between ck-mono"
                style="font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4); margin-top:4px;"
              >
                <span>STRICT (0%)</span>
                <span>PERMISSIVE (100%)</span>
              </div>
              <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:6px;">
                Fraction of claims unsupported by retrieved context. Default 30%.
              </p>
            </div>

            <!-- sample_rate -->
            <div class="mb-6">
              <div class="flex items-center justify-between mb-2">
                <label class="ck-mono" style="font-size:11px; color:var(--ck-fg-2);">
                  Sampling rate
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
                [ngModel]="sampleRate()"
                (ngModelChange)="sampleRate.set($event); markDirty()"
                [disabled]="!enabled()"
                class="w-full accent-cyan-400"
              />
              <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:6px;">
                Probability that any given run is evaluated. Lower to save judge budget on high-volume workloads. Default 100%.
              </p>
            </div>

            <!-- Dimension minimums (power user) -->
            <details style="margin-top:16px; padding-top:16px; border-top:1px solid var(--ck-hair);">
              <summary
                class="ck-mono cursor-pointer"
                style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-3);"
              >
                DIMENSION MINIMUMS (JSON)
              </summary>
              <textarea
                [ngModel]="dimensionMinJson()"
                (ngModelChange)="updateDimensionMinJson($event)"
                [disabled]="!enabled()"
                rows="6"
                class="w-full ck-mono"
                style="margin-top:10px; padding:10px; background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-soft); border-radius:4px; font-size:11px; color:var(--ck-fg-1); resize:vertical;"
                placeholder='{"safety": 80.0, "hallucination": 50.0}'
              ></textarea>
              @if (dimensionMinError()) {
                <div class="ck-mono" style="font-size:10px; color:var(--ck-signal-neg); margin-top:4px;">
                  {{ dimensionMinError() }}
                </div>
              }
              <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:6px;">
                Per-dimension floors on the 12-axis LLM judge. Any dimension below its floor fails the check. Dimensions: task_success, relevance, instruction_following, coherence, hallucination, tone, conciseness, safety, policy, drift, manipulation, tool_use.
              </p>
            </details>
          </section>

          <!-- Save bar -->
          <section
            class="ck-surface rounded-md"
            style="padding:14px 22px; display:flex; align-items:center; gap:14px;"
          >
            @if (dirty()) {
              <ck-tag tone="warn" variant="soft">UNSAVED CHANGES</ck-tag>
            } @else {
              <ck-tag tone="pos" variant="soft">SYNCED</ck-tag>
            }
            <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
              Workspace scope — these thresholds apply to every run in this workspace
              unless a system/capability-level override exists.
            </span>
            <span class="ml-auto flex items-center gap-2">
              <a
                routerLink="/steering/review-queue"
                class="ck-mono"
                style="padding:6px 12px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-2); background:var(--ck-bg-inset); text-decoration:none;"
              >
                VIEW REVIEW QUEUE
              </a>
              <button
                type="button"
                (click)="save()"
                [disabled]="!dirty() || saving() || !!dimensionMinError()"
                class="ck-mono"
                style="padding:8px 16px; border-radius:4px; font-size:11px; letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-signal-pos); color:var(--ck-on-signal); font-weight:600;"
                [style.opacity]="!dirty() || saving() || !!dimensionMinError() ? '0.4' : '1'"
              >
                {{ saving() ? 'SAVING…' : 'SAVE THRESHOLDS' }}
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

  readonly loading = signal(true);
  readonly saving = signal(false);
  readonly dirty = signal(false);

  readonly enabled = signal(false);
  readonly composite = signal(60);
  readonly hallucination = signal(0.3);
  readonly sampleRate = signal(1);
  readonly dimensionMinJson = signal('{\n  "safety": 80.0,\n  "hallucination": 50.0\n}');
  readonly dimensionMinError = signal<string | null>(null);

  readonly compositeTone = computed(() => {
    const v = this.composite();
    if (v < 40) return 'var(--ck-signal-neg)';
    if (v < 60) return 'var(--ck-signal-warn)';
    return 'var(--ck-signal-pos)';
  });

  readonly hallucinationTone = computed(() => {
    const v = this.hallucination();
    if (v > 0.5) return 'var(--ck-signal-neg)';
    if (v > 0.3) return 'var(--ck-signal-warn)';
    return 'var(--ck-signal-pos)';
  });

  ngOnInit(): void {
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.canonical.getEvaluationPresets().subscribe({
      next: (response: EvaluationPresetResponse | null) => {
        if (response) {
          const effective = response.effective || {};
          this.enabled.set(!!effective.enabled);
          this.composite.set(effective.composite_min ?? 60);
          this.hallucination.set(effective.hallucination_max ?? 0.3);
          this.sampleRate.set(effective.sample_rate ?? 1);
          const dim = effective.dimension_min || {};
          this.dimensionMinJson.set(JSON.stringify(dim, null, 2));
        }
        this.dirty.set(false);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  markDirty(): void {
    this.dirty.set(true);
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
        this.dimensionMinError.set('Must be a JSON object');
        return;
      }
      for (const [k, v] of Object.entries(parsed)) {
        if (typeof v !== 'number') {
          this.dimensionMinError.set(`"${k}" must be a number`);
          return;
        }
      }
      this.dimensionMinError.set(null);
    } catch (e) {
      this.dimensionMinError.set(`Invalid JSON: ${(e as Error).message}`);
    }
  }

  save(): void {
    if (this.saving() || this.dimensionMinError()) return;
    let dimension_min: Record<string, number> = {};
    try {
      dimension_min = JSON.parse(this.dimensionMinJson() || '{}');
    } catch {
      return;
    }
    this.saving.set(true);
    const body: Partial<EvaluationPresetConfig> & { name?: string } = {
      enabled: this.enabled(),
      composite_min: this.composite(),
      hallucination_max: this.hallucination(),
      sample_rate: this.sampleRate(),
      dimension_min,
    };
    this.canonical.updateEvaluationPreset(body).subscribe({
      next: () => {
        this.saving.set(false);
        this.dirty.set(false);
      },
      error: () => this.saving.set(false),
    });
  }
}
