import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type Capability, type Skill, type System } from '@app/core/canonical-api.service';
import { SettingsService } from '@app/core/settings.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import {
  type CkGlyphName,
  GlyphComponent,
  LiveDotComponent,
  MicroBarComponent,
  StatReadoutComponent,
  TagComponent,
} from '@app/shared/cockpit';
import { SystemsStore } from './systems.store';

interface WizardStep {
  key: 'objective' | 'capability' | 'context' | 'policy' | 'launch';
  title: string;
  description: string;
  glyph: CkGlyphName;
}

const RAG_PIPELINES = [
  { id: 'OmniRAG', label: 'OmniRAG', description: 'Hybrid dense + BM25 + rerank' },
  { id: 'Semantic', label: 'Semantic', description: 'Dense vectors only' },
  { id: 'Hybrid', label: 'Hybrid', description: 'Dense + lexical merge' },
  { id: 'None', label: 'Direct LLM', description: 'No retrieval' },
];

const TIER_TONE: Record<string, 'pos' | 'cool' | 'violet' | 'warn'> = {
  universal: 'pos',
  industry: 'violet',
  client: 'cool',
};

@Component({
  selector: 'app-system-builder',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    IconComponent,
    SectionHeaderComponent,
    EmptyStateComponent,
    GlyphComponent,
    LiveDotComponent,
    MicroBarComponent,
    StatReadoutComponent,
    TagComponent,
  ],
  template: `
    <app-section-header
      breadcrumb="Build"
      title="New system"
      icon="sparkles"
      subtitle="Compose a system: objective → capability → context → policy → launch."
    >
      <a
        routerLink="/systems"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
      >
        <app-icon name="arrow-left" [size]="14" /> Back to systems
      </a>
    </app-section-header>

    <!-- Stepper -->
    <div class="mb-6">
      <div class="flex items-center gap-4 max-w-4xl">
        @for (step of steps; track step.key; let i = $index; let last = $last) {
          <div class="flex items-center flex-1" [class.flex-none]="last">
            <button
              type="button"
              (click)="gotoStep(i)"
              [disabled]="i > furthestReached()"
              class="flex items-center gap-2 group disabled:opacity-60"
              [title]="step.description"
            >
              <div
                class="w-9 h-9 rounded-md flex items-center justify-center transition shrink-0 ck-surface"
                [style.borderColor]="i === currentStep() ? 'var(--ck-stroke-strong)' : 'var(--ck-stroke-soft)'"
                [style.color]="i === currentStep() ? 'var(--ck-signal-cool)' : 'var(--ck-fg-3)'"
                [style.boxShadow]="i === currentStep() ? 'var(--ck-glow-cool)' : 'none'"
              >
                @if (i < currentStep() && isStepValid(i)) {
                  <ck-glyph name="check" [size]="14" />
                } @else {
                  <ck-glyph [name]="step.glyph" [size]="14" />
                }
              </div>
              <div class="hidden md:block text-left">
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
                  {{ ('0' + (i + 1)).slice(-2) }}
                </div>
                <div
                  class="text-sm font-medium"
                  [style.color]="i === currentStep() ? 'var(--ck-fg-1)' : 'var(--ck-fg-3)'"
                >
                  {{ step.title }}
                </div>
              </div>
            </button>
            @if (!last) {
              <div class="h-px flex-1 mx-3"
                [style.backgroundColor]="i < currentStep() ? 'var(--ck-stroke-strong)' : 'var(--ck-stroke-soft)'"
              ></div>
            }
          </div>
        }
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <!-- Main pane -->
      <section class="lg:col-span-2 ck-surface rounded-md" style="padding: 24px;">
        <!-- Step 1: Objective & identity -->
        @if (currentStep() === 0) {
          <div class="space-y-5">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <ck-glyph name="focus" [size]="16" />
                Objective
              </h2>
              <p class="text-xs ck-mono" style="color:var(--ck-fg-3); margin-top:4px; letter-spacing:0.02em;">
                Define what this system should achieve — a single, measurable objective the Hypervisor can track.
              </p>
            </header>
            <div>
              <label class="ck-mono" style="display:block; font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:6px;">
                Name <span style="color:var(--ck-signal-neg);">*</span>
              </label>
              <input
                type="text"
                [(ngModel)]="draft.name"
                name="name"
                required
                class="ck-surface ck-mono w-full"
                style="padding: 10px 12px; border-radius:4px; font-size:14px; background:var(--ck-bg-inset);"
                placeholder="Contract Analyzer"
              />
            </div>
            <div>
              <label class="ck-mono" style="display:block; font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:6px;">
                Objective
              </label>
              <textarea
                [(ngModel)]="draft.objective"
                name="objective"
                rows="3"
                class="ck-surface w-full"
                style="padding: 10px 12px; border-radius:4px; font-size:13px; background:var(--ck-bg-inset); resize: none;"
                placeholder="Flag risky clauses in NDAs with legal rationale and severity."
              ></textarea>
              <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:4px;">
                One sentence. Outcome-oriented. Drives the Hypervisor's value metric for this system.
              </p>
            </div>
          </div>
        }

        <!-- Step 2: Capability -->
        @if (currentStep() === 1) {
          <div class="space-y-4">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <ck-glyph name="cube" [size]="16" />
                Capability
              </h2>
              <p class="text-xs ck-mono" style="color:var(--ck-fg-3); margin-top:4px; letter-spacing:0.02em;">
                Pick the value-producing unit. Skills are bundled automatically.
              </p>
            </header>

            @if (loadingCaps()) {
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                @for (_ of [0, 1, 2, 3]; track $index) {
                  <div class="h-28 rounded-md ck-surface" style="background:var(--ck-bg-inset); animation: pulse 2s ease-in-out infinite;"></div>
                }
              </div>
            } @else if (capabilities().length === 0) {
              <app-empty-state
                icon="database"
                title="No capability"
                description="Seed the catalog by restarting the backend or create one from the Catalog."
              />
            } @else {
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                @for (cap of capabilities(); track cap.id) {
                  <button
                    type="button"
                    (click)="selectCapability(cap)"
                    class="text-left transition ck-surface rounded-md"
                    [style.padding]="'14px 16px'"
                    [style.borderColor]="draft.capability_id === cap.id ? 'var(--ck-stroke-strong)' : 'var(--ck-stroke-soft)'"
                    [style.boxShadow]="draft.capability_id === cap.id ? 'var(--ck-glow-cool)' : 'none'"
                  >
                    <div class="flex items-start justify-between gap-3 mb-2">
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 mb-1">
                          <ck-tag [tone]="tierTone(cap.tier)" variant="soft">{{ cap.tier || 'UNIV' }}</ck-tag>
                          @if (cap.industry) {
                            <ck-tag tone="violet" variant="outline">{{ cap.industry }}</ck-tag>
                          }
                        </div>
                        <div class="text-sm font-medium text-white truncate">{{ cap.name }}</div>
                      </div>
                      @if (draft.capability_id === cap.id) {
                        <ck-live-dot tone="cool" />
                      }
                    </div>
                    <p class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); line-height:1.5; margin-bottom:10px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">
                      {{ cap.description || '—' }}
                    </p>
                    <div class="flex items-center justify-between">
                      <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
                        {{ cap.skill_ids?.length || 0 }} SKILLS · {{ cap.input_unit || '—' }} → {{ cap.output_unit || '—' }}
                      </span>
                      <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2);">
                        {{ formatPrice(cap.pricing?.unit_price) }}
                      </span>
                    </div>
                  </button>
                }
              </div>
            }

            <!-- Bundled skills preview -->
            @if (draft.capability_id && bundledSkills().length > 0) {
              <div class="pt-3" style="border-top: 1px solid var(--ck-hair);">
                <div class="ck-mono flex items-center gap-2 mb-3" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
                  <ck-glyph name="ledger" [size]="12" />
                  BUNDLED SKILLS · {{ bundledSkills().length }}
                </div>
                <ul style="display:flex; flex-direction:column; gap:4px;">
                  @for (sk of bundledSkills(); track sk.id) {
                    <li style="display:grid; grid-template-columns: 1fr auto auto; gap:12px; align-items:center; padding:6px 10px; border-radius:4px; background:var(--ck-bg-inset);">
                      <div style="display:flex; align-items:center; gap:8px; min-width:0;">
                        <ck-tag [tone]="certTone(sk.certification_level)" variant="outline">
                          {{ (sk.certification_level || 'basic').slice(0, 4).toUpperCase() }}
                        </ck-tag>
                        <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                          {{ sk.name }}
                        </span>
                      </div>
                      <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
                        {{ sk.type || '—' }}
                      </span>
                      <span class="ck-mono ck-tnum" style="font-size:10px; color:var(--ck-fg-3); text-align:right;">
                        {{ formatPrice(sk.pricing?.unit_price) }}
                      </span>
                    </li>
                  }
                </ul>
              </div>
            }
          </div>
        }

        <!-- Step 3: Context -->
        @if (currentStep() === 2) {
          <div class="space-y-5">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <ck-glyph name="ledger" [size]="16" />
                Context
              </h2>
              <p class="text-xs ck-mono" style="color:var(--ck-fg-3); margin-top:4px; letter-spacing:0.02em;">
                Knowledge collections and the retrieval pipeline. This becomes the versioned Context attached to every Run.
              </p>
            </header>

            @if (loadingCollections()) {
              <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
                @for (_ of [0, 1, 2, 3]; track $index) {
                  <div class="h-16 rounded-md ck-surface" style="background:var(--ck-bg-inset);"></div>
                }
              </div>
            } @else if (collections().length === 0) {
              <app-empty-state
                icon="database"
                title="No collection yet"
                description="Upload documents in Knowledge to create one."
              >
                <a
                  routerLink="/knowledge"
                  class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium text-white transition"
                  style="background: var(--ck-signal-cool); color: #0a0a0a;"
                >
                  Open Knowledge
                </a>
              </app-empty-state>
            } @else {
              <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
                @for (col of collections(); track col) {
                  <label
                    class="flex items-center gap-3 ck-surface rounded cursor-pointer"
                    style="padding:10px 12px; border-radius:4px;"
                    [style.borderColor]="isCollectionChecked(col) ? 'var(--ck-stroke-strong)' : 'var(--ck-stroke-soft)'"
                  >
                    <input
                      type="checkbox"
                      [checked]="isCollectionChecked(col)"
                      (change)="toggleCollection(col)"
                      class="accent-cyan-400"
                    />
                    <span class="ck-mono" style="font-size:12px; color:var(--ck-fg-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                      {{ col }}
                    </span>
                  </label>
                }
              </div>
            }

            <div style="border-top: 1px solid var(--ck-hair); padding-top:16px;">
              <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                Retrieval pipeline
              </div>
              <div class="grid grid-cols-2 md:grid-cols-4 gap-2">
                @for (mode of ragPipelines; track mode.id) {
                  <button
                    type="button"
                    (click)="draft.rag_mode = mode.id"
                    class="text-left transition ck-surface rounded"
                    style="padding:10px 12px;"
                    [style.borderColor]="draft.rag_mode === mode.id ? 'var(--ck-stroke-strong)' : 'var(--ck-stroke-soft)'"
                  >
                    <div class="text-sm font-medium" [style.color]="draft.rag_mode === mode.id ? 'var(--ck-fg-1)' : 'var(--ck-fg-2)'">
                      {{ mode.label }}
                    </div>
                    <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:2px;">
                      {{ mode.description }}
                    </div>
                  </button>
                }
              </div>
            </div>
          </div>
        }

        <!-- Step 4: Policy -->
        @if (currentStep() === 3) {
          <div class="space-y-5">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <ck-glyph name="sliders" [size]="16" />
                Policy
              </h2>
              <p class="text-xs ck-mono" style="color:var(--ck-fg-3); margin-top:4px; letter-spacing:0.02em;">
                Control guardrails and adaptive levers. Control = hard limits, Adaptive = soft directives.
              </p>
            </header>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div>
                <label class="ck-mono" style="display:flex; align-items:center; justify-content:space-between; font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                  <span>CONTROL · max cost / outcome</span>
                  <span class="ck-tnum" style="color:var(--ck-signal-cool);">\${{ draft.max_cost.toFixed(2) }}</span>
                </label>
                <input type="range" min="0.01" max="5" step="0.01" [(ngModel)]="draft.max_cost" class="w-full accent-cyan-400" />
              </div>
              <div>
                <label class="ck-mono" style="display:flex; align-items:center; justify-content:space-between; font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                  <span>CONTROL · max latency (ms)</span>
                  <span class="ck-tnum" style="color:var(--ck-signal-cool);">{{ draft.max_latency_ms }}</span>
                </label>
                <input type="range" min="500" max="60000" step="500" [(ngModel)]="draft.max_latency_ms" class="w-full accent-cyan-400" />
              </div>
              <div>
                <label class="ck-mono" style="display:flex; align-items:center; justify-content:space-between; font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                  <span>ADAPTIVE · confidence threshold</span>
                  <span class="ck-tnum" style="color:var(--ck-signal-violet);">{{ draft.confidence_threshold.toFixed(2) }}</span>
                </label>
                <input type="range" min="0" max="1" step="0.01" [(ngModel)]="draft.confidence_threshold" class="w-full accent-violet-400" />
                <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:4px;">
                  Below this score → HITL escalation (auto).
                </p>
              </div>
              <div>
                <label class="ck-mono" style="display:flex; align-items:center; justify-content:space-between; font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                  <span>ADAPTIVE · temperature</span>
                  <span class="ck-tnum" style="color:var(--ck-signal-violet);">{{ draft.temperature.toFixed(2) }}</span>
                </label>
                <input type="range" min="0" max="2" step="0.05" [(ngModel)]="draft.temperature" class="w-full accent-violet-400" />
              </div>
            </div>

            <div class="space-y-2" style="border-top: 1px solid var(--ck-hair); padding-top:16px;">
              <label class="flex items-start gap-3 ck-surface cursor-pointer" style="padding:12px 14px; border-radius:4px;">
                <input type="checkbox" [(ngModel)]="draft.require_citations" class="accent-cyan-400 mt-0.5" />
                <div class="flex-1">
                  <div class="text-sm text-white font-medium">Require citations</div>
                  <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
                    Answers without a citation are blocked before returning.
                  </div>
                </div>
              </label>
              <label class="flex items-start gap-3 ck-surface cursor-pointer" style="padding:12px 14px; border-radius:4px;">
                <input type="checkbox" [(ngModel)]="draft.enable_audit" class="accent-cyan-400 mt-0.5" />
                <div class="flex-1">
                  <div class="text-sm text-white font-medium">Audit every run</div>
                  <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
                    Emit a typed audit event per run (required for enterprise tier).
                  </div>
                </div>
              </label>
            </div>
          </div>
        }

        <!-- Step 5: Launch -->
        @if (currentStep() === 4) {
          <div class="space-y-5">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <ck-glyph name="bolt" [size]="16" />
                Launch
              </h2>
              <p class="text-xs ck-mono" style="color:var(--ck-fg-3); margin-top:4px; letter-spacing:0.02em;">
                Final review before creating the System.
              </p>
            </header>

            <!-- ROI projection -->
            <div class="ck-surface rounded" style="padding:16px 18px; background: var(--ck-bg-inset);">
              <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:12px;">
                PROJECTED OUTCOME (PER RUN)
              </div>
              <div style="display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap:18px;">
                <ck-stat-readout label="COST" [value]="formatPrice(selectedCapability()?.pricing?.unit_price)" tone="cool" [size]="16" />
                <ck-stat-readout label="VALUE" [value]="formatPrice(selectedCapability()?.value_per_outcome)" tone="pos" [size]="16" />
                <ck-stat-readout label="MARGIN" [value]="projectedMargin()" tone="pos" [size]="16" />
                <ck-stat-readout label="ROI" [value]="projectedRoi()" tone="violet" [size]="16" />
              </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div class="ck-surface rounded" style="padding:14px 16px;">
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:6px;">OBJECTIVE</div>
                <div class="text-sm font-medium text-white">{{ draft.name || 'Untitled' }}</div>
                <div class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); margin-top:4px; line-height:1.5; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden;">
                  {{ draft.objective || 'No objective set.' }}
                </div>
              </div>
              <div class="ck-surface rounded" style="padding:14px 16px;">
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:6px;">CAPABILITY</div>
                <div class="text-sm font-medium text-white">{{ selectedCapability()?.name || '—' }}</div>
                <div class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); margin-top:4px;">
                  {{ selectedCapability()?.tier || '—' }} · {{ bundledSkills().length }} skills bundled
                </div>
              </div>
              <div class="ck-surface rounded" style="padding:14px 16px;">
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:6px;">CONTEXT</div>
                <div class="text-sm text-white">
                  {{ draft.collections.length }} collection{{ draft.collections.length === 1 ? '' : 's' }}
                </div>
                <div class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); margin-top:4px;">
                  Pipeline: {{ draft.rag_mode }}
                </div>
              </div>
              <div class="ck-surface rounded" style="padding:14px 16px;">
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:6px;">POLICY</div>
                <div class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); line-height:1.7;">
                  MAX COST <span class="ck-tnum" style="color:var(--ck-fg-2);">\${{ draft.max_cost.toFixed(2) }}</span> ·
                  MAX LATENCY <span class="ck-tnum" style="color:var(--ck-fg-2);">{{ draft.max_latency_ms }} ms</span><br />
                  CONFIDENCE ≥ <span class="ck-tnum" style="color:var(--ck-fg-2);">{{ draft.confidence_threshold.toFixed(2) }}</span> ·
                  TEMP <span class="ck-tnum" style="color:var(--ck-fg-2);">{{ draft.temperature.toFixed(2) }}</span>
                </div>
              </div>
            </div>
          </div>
        }
      </section>

      <!-- Live preview pane -->
      <aside class="ck-surface rounded-md self-start sticky top-4" style="padding:20px;">
        <div class="flex items-center gap-3 mb-4 pb-3" style="border-bottom: 1px solid var(--ck-hair);">
          <div class="w-10 h-10 rounded-md flex items-center justify-center ck-surface" style="background:var(--ck-bg-inset); border-color: var(--ck-stroke-soft);">
            <ck-glyph [name]="currentGlyph()" [size]="18" />
          </div>
          <div>
            <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
              LIVE PREVIEW
            </div>
            <div class="text-sm font-medium text-white truncate">{{ draft.name || 'New system' }}</div>
          </div>
        </div>

        <ul class="space-y-3">
          <li class="flex items-center gap-2">
            <ck-glyph name="focus" [size]="12" />
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">OBJECTIVE</span>
            <span class="ml-auto ck-mono" style="font-size:11px; color:var(--ck-fg-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:140px;">
              {{ draft.name || '—' }}
            </span>
          </li>
          <li class="flex items-center gap-2">
            <ck-glyph name="cube" [size]="12" />
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">CAPABILITY</span>
            <span class="ml-auto ck-mono" style="font-size:11px; color:var(--ck-fg-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:140px;">
              {{ selectedCapability()?.name || '—' }}
            </span>
          </li>
          <li class="flex items-center gap-2">
            <ck-glyph name="ledger" [size]="12" />
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">CONTEXT</span>
            <span class="ml-auto ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2);">
              {{ draft.collections.length }} · {{ draft.rag_mode }}
            </span>
          </li>
          <li class="flex items-center gap-2">
            <ck-glyph name="sliders" [size]="12" />
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">POLICY</span>
            <span class="ml-auto ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2);">
              \${{ draft.max_cost.toFixed(2) }} · τ{{ draft.confidence_threshold.toFixed(2) }}
            </span>
          </li>
        </ul>

        <!-- Step progress -->
        <div class="mt-4 pt-4" style="border-top: 1px solid var(--ck-hair);">
          <div class="flex items-center justify-between mb-2">
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">PROGRESS</span>
            <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2);">
              {{ currentStep() + 1 }} / {{ steps.length }}
            </span>
          </div>
          <ck-micro-bar [value]="currentStep() + 1" [max]="steps.length" [width]="220" tone="cool" [glow]="true" />
        </div>

        @if (!isStepValid(currentStep())) {
          <div class="ck-mono mt-4" style="font-size:10px; color:var(--ck-signal-warn); letter-spacing:0.02em;">
            ⚠ {{ validationMessage() }}
          </div>
        }
      </aside>
    </div>

    <!-- Nav -->
    <div class="flex items-center justify-between mt-6 pt-6" style="border-top: 1px solid var(--ck-hair);">
      <button
        type="button"
        (click)="prev()"
        [disabled]="currentStep() === 0"
        class="ck-surface ck-mono inline-flex items-center gap-2"
        style="padding: 8px 14px; border-radius:4px; font-size:11px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-3);"
      >
        <ck-glyph name="arrow-right" [size]="12" style="transform: rotate(180deg); display:inline-block;" /> PREV
      </button>
      <span class="ck-mono" style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
        STEP {{ currentStep() + 1 }} / {{ steps.length }}
      </span>
      @if (currentStep() < steps.length - 1) {
        <button
          type="button"
          (click)="next()"
          [disabled]="!isStepValid(currentStep())"
          class="ck-mono inline-flex items-center gap-2"
          style="padding: 8px 14px; border-radius:4px; font-size:11px; letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-signal-cool); color:#020617; font-weight:600;"
        >
          NEXT <ck-glyph name="arrow-right" [size]="12" />
        </button>
      } @else {
        <button
          type="button"
          (click)="launch()"
          [disabled]="!allStepsValid() || launching()"
          class="ck-mono inline-flex items-center gap-2"
          style="padding: 8px 16px; border-radius:4px; font-size:11px; letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-signal-pos); color:#020617; font-weight:600; box-shadow: var(--ck-glow-pos);"
        >
          <ck-glyph name="bolt" [size]="12" />
          {{ launching() ? 'CREATING…' : 'CREATE SYSTEM' }}
        </button>
      }
    </div>
  `,
})
export class SystemBuilderComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly toast = inject(ToastrService);
  private readonly store = inject(SystemsStore);
  readonly settings = inject(SettingsService);

  readonly ragPipelines = RAG_PIPELINES;

  readonly steps: WizardStep[] = [
    { key: 'objective', title: 'Objective', description: 'Name & outcome', glyph: 'focus' },
    { key: 'capability', title: 'Capability', description: 'Value-producing unit', glyph: 'cube' },
    { key: 'context', title: 'Context', description: 'Knowledge + retrieval', glyph: 'ledger' },
    { key: 'policy', title: 'Policy', description: 'Guardrails + levers', glyph: 'sliders' },
    { key: 'launch', title: 'Launch', description: 'Review & create', glyph: 'bolt' },
  ];

  readonly currentStep = signal(0);
  readonly furthestReached = signal(0);
  readonly launching = signal(false);

  readonly capabilities = signal<Capability[]>([]);
  readonly loadingCaps = signal(false);
  readonly skills = signal<Skill[]>([]);
  readonly collections = signal<string[]>([]);
  readonly loadingCollections = signal(false);

  draft = {
    name: '',
    objective: '',
    capability_id: '' as string | null,
    collections: [] as string[],
    rag_mode: 'OmniRAG',
    temperature: 0.3,
    max_cost: 0.5,
    max_latency_ms: 8000,
    confidence_threshold: 0.6,
    require_citations: true,
    enable_audit: true,
  };

  readonly currentGlyph = computed<CkGlyphName>(() => this.steps[this.currentStep()]?.glyph ?? 'focus');

  readonly selectedCapability = computed<Capability | null>(() => {
    const id = this.draft.capability_id;
    if (!id) return null;
    return this.capabilities().find((c) => c.id === id) ?? null;
  });

  readonly bundledSkills = computed<Skill[]>(() => {
    const cap = this.selectedCapability();
    if (!cap) return [];
    const ids = new Set(cap.skill_ids || []);
    return this.skills().filter((s) => ids.has(s.id));
  });

  readonly projectedMargin = computed(() => {
    const cap = this.selectedCapability();
    if (!cap?.value_per_outcome || cap?.pricing?.unit_price == null) return '—';
    const m = cap.value_per_outcome - cap.pricing.unit_price;
    return `$${m.toFixed(2)}`;
  });

  readonly projectedRoi = computed(() => {
    const cap = this.selectedCapability();
    if (!cap?.value_per_outcome || !cap?.pricing?.unit_price) return '—';
    const roi = (cap.value_per_outcome - cap.pricing.unit_price) / cap.pricing.unit_price;
    return `${(roi * 100).toFixed(0)}%`;
  });

  ngOnInit(): void {
    const q = this.route.snapshot.queryParamMap;
    if (q.get('name')) this.draft.name = q.get('name') ?? '';
    if (q.get('objective')) this.draft.objective = q.get('objective') ?? '';

    this.settings.refresh();
    this.loadingCaps.set(true);
    this.loadingCollections.set(true);
    forkJoin({
      caps: this.canonical.listCapabilities().pipe(catchError(() => of([] as Capability[]))),
      skills: this.canonical.listSkills().pipe(catchError(() => of([] as Skill[]))),
      collections: this.api
        .get<{ collections: string[] }>('/documents/collections')
        .pipe(catchError(() => of({ collections: [] }))),
    }).subscribe(({ caps, skills, collections }) => {
      this.capabilities.set(caps);
      this.skills.set(skills);
      const cols = collections?.collections ?? [];
      this.collections.set(cols);
      if (cols.length && this.draft.collections.length === 0) {
        this.draft.collections = [cols[0]];
      }
      const s = this.settings.settings();
      if (typeof s.temperature === 'number') this.draft.temperature = s.temperature;
      if (typeof s.ragSimilarityThreshold === 'number') {
        this.draft.confidence_threshold = Math.max(0.4, s.ragSimilarityThreshold);
      }
      this.loadingCaps.set(false);
      this.loadingCollections.set(false);
    });
  }

  selectCapability(cap: Capability): void {
    this.draft.capability_id = cap.id;
    if (!this.draft.name) this.draft.name = cap.name;
    if (!this.draft.objective && cap.description) this.draft.objective = cap.description;
    if (cap.confidence_threshold != null) this.draft.confidence_threshold = cap.confidence_threshold;
    if (cap.pricing?.unit_price != null) {
      this.draft.max_cost = Math.max(this.draft.max_cost, cap.pricing.unit_price * 2);
    }
  }

  isCollectionChecked(name: string): boolean {
    return this.draft.collections.includes(name);
  }

  toggleCollection(name: string): void {
    const idx = this.draft.collections.indexOf(name);
    if (idx >= 0) this.draft.collections.splice(idx, 1);
    else this.draft.collections.push(name);
  }

  isStepValid(idx: number): boolean {
    switch (idx) {
      case 0:
        return this.draft.name.trim().length > 0;
      case 1:
        return !!this.draft.capability_id;
      case 2:
      case 3:
        return true;
      case 4:
        return this.draft.name.trim().length > 0 && !!this.draft.capability_id;
      default:
        return true;
    }
  }

  allStepsValid(): boolean {
    return this.steps.every((_, i) => this.isStepValid(i));
  }

  validationMessage(): string {
    switch (this.currentStep()) {
      case 0:
        return 'A name is required.';
      case 1:
        return 'Pick a capability to continue.';
      case 4:
        return 'Fill the name and pick a capability before launching.';
      default:
        return '';
    }
  }

  gotoStep(i: number): void {
    if (i > this.furthestReached()) return;
    this.currentStep.set(i);
  }

  next(): void {
    if (!this.isStepValid(this.currentStep())) return;
    const next = this.currentStep() + 1;
    this.currentStep.set(next);
    if (next > this.furthestReached()) this.furthestReached.set(next);
  }

  prev(): void {
    if (this.currentStep() === 0) return;
    this.currentStep.set(this.currentStep() - 1);
  }

  launch(): void {
    if (!this.allStepsValid() || this.launching()) return;
    this.launching.set(true);
    const cap = this.selectedCapability();
    const body: Partial<System> & { flow_definition?: Record<string, unknown> } = {
      name: this.draft.name.trim(),
      objective: this.draft.objective.trim(),
      capability_id: this.draft.capability_id ?? null,
      skill_ids: cap?.skill_ids ?? [],
      flow_definition: {
        collections: this.draft.collections,
        rag_mode: this.draft.rag_mode,
        policy: {
          max_cost: this.draft.max_cost,
          max_latency_ms: this.draft.max_latency_ms,
          confidence_threshold: this.draft.confidence_threshold,
          temperature: this.draft.temperature,
          require_citations: this.draft.require_citations,
          enable_audit: this.draft.enable_audit,
        },
      },
      status: 'active',
    };
    this.canonical.createSystem(body).subscribe((sys) => {
      this.launching.set(false);
      if (sys) {
        this.toast.success(`"${sys.name}" is live`, 'System created');
        this.router.navigate(['/systems', sys.id]);
        return;
      }
      // Fallback: persist a local draft so the user isn't blocked when the backend
      // write path is offline (e.g. seeded DB but auth disabled).
      const draft = this.store.createDraft({
        name: this.draft.name.trim(),
        description: this.draft.objective.trim(),
        model: 'gpt-4o-mini',
        rag_mode: this.draft.rag_mode,
        skills: cap?.skill_ids ?? [],
        collections: [...this.draft.collections],
      });
      this.toast.warning('Created as local draft (API unreachable)', 'System draft');
      this.router.navigate(['/systems', draft.id]);
    });
  }

  formatPrice(v: number | null | undefined): string {
    if (v == null) return '—';
    if (v < 0.01) return `$${v.toFixed(4)}`;
    if (v < 1) return `$${v.toFixed(3)}`;
    return `$${v.toFixed(2)}`;
  }

  tierTone(tier: string | undefined): 'pos' | 'cool' | 'violet' | 'warn' {
    return TIER_TONE[tier || 'universal'] ?? 'pos';
  }

  certTone(cert: string | undefined): 'pos' | 'cool' | 'violet' | 'warn' {
    if (cert === 'enterprise') return 'violet';
    if (cert === 'production') return 'pos';
    return 'cool';
  }
}
