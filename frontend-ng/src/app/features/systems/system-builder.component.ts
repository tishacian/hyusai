import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NgClass } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { SettingsService } from '@app/core/settings.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { SystemsStore } from './systems.store';

interface Template {
  id: string;
  label: string;
  icon: string;
  description: string;
  prompt: string;
}

interface ModelInfo {
  id: string;
  name?: string;
  provider?: string;
  description?: string;
  context_length?: number;
}

interface WizardStep {
  key: 'identity' | 'knowledge' | 'model' | 'guardrails' | 'launch';
  title: string;
  description: string;
  icon: string;
}

const TEMPLATES: Template[] = [
  { id: 'contract', label: 'Contract Analysis', icon: 'file-text', description: 'Flag risky clauses in contracts', prompt: 'Analyze the following contract and flag risk clauses with severity and rationale.' },
  { id: 'support', label: 'Customer Support', icon: 'message-square', description: 'Answer questions from your docs', prompt: 'Answer customer questions strictly from the provided knowledge base. Cite sources.' },
  { id: 'code', label: 'Code Review', icon: 'code-2', description: 'Review PRs for bugs and style', prompt: 'Review this code change for bugs, security risks and style. Suggest concrete fixes.' },
  { id: 'research', label: 'Market Research', icon: 'microscope', description: 'Synthesize competitor intel', prompt: 'Synthesize competitor intelligence from the provided corpus. Highlight moves, risks and opportunities.' },
  { id: 'onboarding', label: 'HR Onboarding', icon: 'user-plus', description: 'Guide new hires in the first weeks', prompt: 'Act as an HR onboarding buddy. Guide a new hire through their first weeks using the company knowledge base.' },
  { id: 'insights', label: 'Data Insights', icon: 'bar-chart-3', description: 'Extract KPIs from CSVs', prompt: 'Extract KPIs from the provided reports. Produce a concise executive summary with supporting numbers.' },
];

@Component({
  selector: 'app-system-builder',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    NgClass,
    RouterLink,
    IconComponent,
    SectionHeaderComponent,
    EmptyStateComponent,
  ],
  template: `
    <app-section-header
      breadcrumb="Build"
      title="New system"
      icon="sparkles"
      subtitle="Compose an intelligent system from an objective, a corpus and a policy."
    >
      <a
        routerLink="/systems"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
      >
        <app-icon name="arrow-left" [size]="14" /> Back to systems
      </a>
    </app-section-header>

    <!-- Stepper -->
    <div class="mb-8">
      <div class="flex items-center justify-between max-w-3xl">
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
                class="w-9 h-9 rounded-full flex items-center justify-center ring-2 transition shrink-0"
                [ngClass]="{
                  'bg-brand-500 ring-brand-500 text-white shadow-glow-sm': i === currentStep(),
                  'bg-emerald-500/15 ring-emerald-500/40 text-emerald-400': i < currentStep() || (i < furthestReached() && isStepValid(i)),
                  'bg-white/5 ring-white/10 text-gray-500': i > currentStep() && !(i < furthestReached() && isStepValid(i))
                }"
              >
                @if (i < currentStep() && isStepValid(i)) {
                  <app-icon name="check" [size]="14" />
                } @else {
                  <app-icon [name]="step.icon" [size]="14" />
                }
              </div>
              <div class="hidden md:block text-left">
                <div class="text-[10px] uppercase tracking-wider font-semibold text-gray-500">
                  Step {{ i + 1 }}
                </div>
                <div
                  class="text-sm font-medium"
                  [class.text-white]="i === currentStep()"
                  [class.text-gray-400]="i !== currentStep()"
                >
                  {{ step.title }}
                </div>
              </div>
            </button>
            @if (!last) {
              <div class="h-px flex-1 mx-3 transition"
                [ngClass]="i < currentStep() ? 'bg-brand-500/50' : 'bg-white/5'"
              ></div>
            }
          </div>
        }
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <!-- Main pane -->
      <section class="lg:col-span-2 t-card t-elevated rounded-md p-6">
        <!-- Step 1: Identity -->
        @if (currentStep() === 0) {
          <div class="space-y-5">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <app-icon name="tag" [size]="16" class="text-brand-400" />
                Objective & identity
              </h2>
              <p class="text-xs text-gray-400 mt-1">
                What should this system achieve, and how do you want it to introduce itself?
              </p>
            </header>
            <div>
              <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                Name <span class="text-red-400">*</span>
              </label>
              <input
                type="text"
                [(ngModel)]="draft.name"
                name="name"
                required
                class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-brand-500/60 focus:border-brand-500/50 transition"
                placeholder="Contract Analyzer"
              />
            </div>
            <div>
              <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                Objective / description
              </label>
              <textarea
                [(ngModel)]="draft.description"
                name="description"
                rows="2"
                class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-brand-500/60 focus:border-brand-500/50 transition resize-none"
                placeholder="What does this system do in one sentence?"
              ></textarea>
            </div>
            <div>
              <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2">
                Start from a template
              </label>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
                @for (tpl of templates; track tpl.id) {
                  <button
                    type="button"
                    (click)="applyTemplate(tpl)"
                    class="flex items-start gap-2.5 px-3 py-2.5 rounded border text-left transition"
                    [ngClass]="draft.template === tpl.id
                      ? 'border-brand-500/50 bg-brand-500/10'
                      : 'border-white/5 bg-black/20 hover:border-brand-500/30'"
                  >
                    <app-icon [name]="tpl.icon" [size]="16" class="text-brand-400 mt-0.5 shrink-0" />
                    <div class="min-w-0">
                      <div class="text-sm font-medium text-white truncate">{{ tpl.label }}</div>
                      <div class="text-[11px] text-gray-500 leading-relaxed line-clamp-2">
                        {{ tpl.description }}
                      </div>
                    </div>
                  </button>
                }
              </div>
            </div>
            <div>
              <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                System prompt
              </label>
              <textarea
                [(ngModel)]="draft.prompt"
                name="prompt"
                rows="4"
                class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-brand-500/60 focus:border-brand-500/50 transition resize-y font-mono text-sm"
                placeholder="You are a precise legal analyst…"
              ></textarea>
              <p class="text-[10px] text-gray-500 mt-1">
                Sets behavior, tone and safety rails. Use the template as a starting point, then refine.
              </p>
            </div>
          </div>
        }

        <!-- Step 2: Knowledge -->
        @if (currentStep() === 1) {
          <div class="space-y-5">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <app-icon name="database" [size]="16" class="text-brand-400" />
                Knowledge sources
              </h2>
              <p class="text-xs text-gray-400 mt-1">
                Pick the collections this system can retrieve from. A system can search one or many.
              </p>
            </header>

            @if (loadingCollections()) {
              <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
                @for (_ of [0, 1, 2, 3]; track $index) {
                  <div class="h-16 rounded-md bg-white/5 animate-pulse"></div>
                }
              </div>
            } @else if (collections().length === 0) {
              <app-empty-state
                icon="database"
                title="No collection yet"
                description="Upload documents to a new collection in Knowledge, then come back."
              >
                <a
                  routerLink="/knowledge"
                  class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded bg-brand-500 hover:bg-brand-600 text-white text-sm font-medium transition"
                >
                  <app-icon name="external-link" [size]="14" />
                  Open Knowledge
                </a>
              </app-empty-state>
            } @else {
              <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
                @for (col of collections(); track col) {
                  <label
                    class="flex items-center gap-3 px-3 py-2.5 rounded border cursor-pointer transition"
                    [ngClass]="isCollectionChecked(col)
                      ? 'border-brand-500/50 bg-brand-500/10'
                      : 'border-white/5 bg-black/20 hover:border-brand-500/30'"
                  >
                    <input
                      type="checkbox"
                      [checked]="isCollectionChecked(col)"
                      (change)="toggleCollection(col)"
                      class="accent-brand-500"
                    />
                    <div class="flex-1 min-w-0">
                      <div class="text-sm text-white font-mono truncate">{{ col }}</div>
                    </div>
                  </label>
                }
              </div>
              <p class="text-[11px] text-gray-500">
                Skipping all collections turns off retrieval — the system will reason without RAG.
              </p>
            }

            <div class="pt-2 border-t border-white/5">
              <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                Retrieval pipeline
              </label>
              <div class="grid grid-cols-2 md:grid-cols-4 gap-2">
                @for (mode of ragModes; track mode.id) {
                  <button
                    type="button"
                    (click)="draft.rag_mode = mode.id"
                    class="px-3 py-2 rounded border text-left transition"
                    [ngClass]="draft.rag_mode === mode.id
                      ? 'border-brand-500/50 bg-brand-500/10 text-white'
                      : 'border-white/5 bg-black/20 text-gray-300 hover:border-brand-500/30'"
                  >
                    <div class="text-sm font-medium">{{ mode.label }}</div>
                    <div class="text-[10px] text-gray-500">{{ mode.description }}</div>
                  </button>
                }
              </div>
            </div>
          </div>
        }

        <!-- Step 3: Model -->
        @if (currentStep() === 2) {
          <div class="space-y-5">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <app-icon name="cpu" [size]="16" class="text-brand-400" />
                Model & reasoning
              </h2>
              <p class="text-xs text-gray-400 mt-1">
                Pick the engine and how creative it's allowed to be.
              </p>
            </header>

            <div>
              <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2">
                Available models
              </label>
              @if (loadingModels()) {
                <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
                  @for (_ of [0, 1, 2, 3]; track $index) {
                    <div class="h-16 rounded-md bg-white/5 animate-pulse"></div>
                  }
                </div>
              } @else if (models().length === 0) {
                <div class="text-xs text-gray-500">
                  No models detected — falling back to workspace default:
                  <span class="font-mono text-gray-300">
                    {{ settings.settings().defaultModel || '—' }}
                  </span>
                </div>
              } @else {
                <div class="grid grid-cols-1 md:grid-cols-2 gap-2 max-h-72 overflow-y-auto pr-1">
                  @for (m of models(); track m.id) {
                    <button
                      type="button"
                      (click)="selectModel(m)"
                      class="flex items-start gap-2.5 px-3 py-2.5 rounded border text-left transition"
                      [ngClass]="draft.model === m.id
                        ? 'border-brand-500/50 bg-brand-500/10'
                        : 'border-white/5 bg-black/20 hover:border-brand-500/30'"
                    >
                      <div class="w-7 h-7 rounded-md bg-brand-500/15 text-brand-400 flex items-center justify-center shrink-0">
                        <app-icon name="cpu" [size]="14" />
                      </div>
                      <div class="flex-1 min-w-0">
                        <div class="text-sm font-medium text-white truncate">
                          {{ m.name || m.id }}
                        </div>
                        <div class="text-[10px] text-gray-500 truncate">
                          {{ m.provider || '—' }}
                          @if (m.context_length) {
                            · {{ m.context_length.toLocaleString() }} tokens
                          }
                        </div>
                      </div>
                    </button>
                  }
                </div>
              }
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-5 pt-2 border-t border-white/5">
              <div>
                <label class="flex items-center justify-between text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  <span>Temperature</span>
                  <span class="text-brand-400 font-mono">{{ draft.temperature.toFixed(2) }}</span>
                </label>
                <input
                  type="range"
                  min="0"
                  max="2"
                  step="0.05"
                  [(ngModel)]="draft.temperature"
                  class="w-full accent-brand-500"
                />
                <p class="text-[10px] text-gray-500 mt-1">
                  0 = deterministic · 1 = balanced · 2 = creative
                </p>
              </div>
              <div>
                <label class="flex items-center justify-between text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  <span>Max tokens</span>
                  <span class="text-brand-400 font-mono">{{ draft.max_tokens }}</span>
                </label>
                <input
                  type="range"
                  min="256"
                  max="8192"
                  step="128"
                  [(ngModel)]="draft.max_tokens"
                  class="w-full accent-brand-500"
                />
                <p class="text-[10px] text-gray-500 mt-1">
                  Upper bound on the generated answer length.
                </p>
              </div>
            </div>
          </div>
        }

        <!-- Step 4: Guardrails -->
        @if (currentStep() === 3) {
          <div class="space-y-5">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <app-icon name="shield-check" [size]="16" class="text-brand-400" />
                Guardrails & retrieval policy
              </h2>
              <p class="text-xs text-gray-400 mt-1">
                How much to retrieve and how strict to be about grounding.
              </p>
            </header>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div>
                <label class="flex items-center justify-between text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  <span>Top-K chunks</span>
                  <span class="text-brand-400 font-mono">{{ draft.top_k }}</span>
                </label>
                <input
                  type="range"
                  min="1"
                  max="30"
                  step="1"
                  [(ngModel)]="draft.top_k"
                  class="w-full accent-brand-500"
                />
                <p class="text-[10px] text-gray-500 mt-1">
                  How many passages to inject per query.
                </p>
              </div>
              <div>
                <label class="flex items-center justify-between text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  <span>Similarity threshold</span>
                  <span class="text-brand-400 font-mono">{{ draft.similarity_threshold.toFixed(2) }}</span>
                </label>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  [(ngModel)]="draft.similarity_threshold"
                  class="w-full accent-brand-500"
                />
                <p class="text-[10px] text-gray-500 mt-1">
                  Passages below this score are discarded.
                </p>
              </div>
            </div>

            <div class="space-y-2 pt-2 border-t border-white/5">
              <label class="flex items-start gap-3 px-3 py-2.5 rounded border border-white/5 bg-black/20 cursor-pointer hover:border-brand-500/30 transition">
                <input type="checkbox" [(ngModel)]="draft.require_citations" class="accent-brand-500 mt-0.5" />
                <div class="flex-1">
                  <div class="text-sm text-white font-medium">Require citations</div>
                  <div class="text-[11px] text-gray-500">
                    The system must cite sources in every answer (recommended for legal / HR).
                  </div>
                </div>
              </label>
              <label class="flex items-start gap-3 px-3 py-2.5 rounded border border-white/5 bg-black/20 cursor-pointer hover:border-brand-500/30 transition">
                <input type="checkbox" [(ngModel)]="draft.enable_audit" class="accent-brand-500 mt-0.5" />
                <div class="flex-1">
                  <div class="text-sm text-white font-medium">Log every exchange</div>
                  <div class="text-[11px] text-gray-500">
                    Send each chat to the governance audit log.
                  </div>
                </div>
              </label>
              <label class="flex items-start gap-3 px-3 py-2.5 rounded border border-white/5 bg-black/20 cursor-pointer hover:border-brand-500/30 transition">
                <input type="checkbox" [(ngModel)]="draft.auto_evaluate" class="accent-brand-500 mt-0.5" />
                <div class="flex-1">
                  <div class="text-sm text-white font-medium">Auto-evaluate responses</div>
                  <div class="text-[11px] text-gray-500">
                    Trigger LLM-judge scoring after each run.
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
                <app-icon name="rocket" [size]="16" class="text-brand-400" />
                Review & launch
              </h2>
              <p class="text-xs text-gray-400 mt-1">
                Last check before this system becomes a draft you can iterate on.
              </p>
            </header>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div class="t-card rounded p-4 bg-black/20">
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">Identity</div>
                <div class="text-white text-sm font-medium">{{ draft.name || 'Untitled' }}</div>
                <div class="text-xs text-gray-400 mt-1 line-clamp-3">
                  {{ draft.description || 'No description.' }}
                </div>
              </div>
              <div class="t-card rounded p-4 bg-black/20">
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">Knowledge</div>
                <div class="text-white text-sm">
                  {{ draft.collections.length || 0 }} collection{{ draft.collections.length === 1 ? '' : 's' }}
                </div>
                @if (draft.collections.length) {
                  <div class="text-[11px] text-gray-400 mt-1 font-mono truncate">
                    {{ draft.collections.join(', ') }}
                  </div>
                } @else {
                  <div class="text-[11px] text-gray-500 mt-1 italic">No retrieval</div>
                }
                <div class="text-[10px] text-gray-500 mt-2">
                  Pipeline: <span class="text-gray-300 font-mono">{{ draft.rag_mode }}</span>
                </div>
              </div>
              <div class="t-card rounded p-4 bg-black/20">
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">Model</div>
                <div class="text-white text-sm font-mono">{{ draft.model }}</div>
                <div class="text-[11px] text-gray-400 mt-1">
                  temp <span class="text-gray-300 font-mono">{{ draft.temperature.toFixed(2) }}</span>
                  · max <span class="text-gray-300 font-mono">{{ draft.max_tokens }}</span>
                </div>
              </div>
              <div class="t-card rounded p-4 bg-black/20">
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">Guardrails</div>
                <div class="space-y-0.5 text-[11px] text-gray-400">
                  <div>Top-K: <span class="text-gray-300 font-mono">{{ draft.top_k }}</span></div>
                  <div>Similarity ≥ <span class="text-gray-300 font-mono">{{ draft.similarity_threshold.toFixed(2) }}</span></div>
                  <div>
                    Citations:
                    <span [class.text-emerald-400]="draft.require_citations" [class.text-gray-500]="!draft.require_citations">
                      {{ draft.require_citations ? 'required' : 'optional' }}
                    </span>
                  </div>
                  <div>
                    Audit:
                    <span [class.text-emerald-400]="draft.enable_audit" [class.text-gray-500]="!draft.enable_audit">
                      {{ draft.enable_audit ? 'on' : 'off' }}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div class="rounded-md p-4 bg-amber-500/5 ring-1 ring-amber-500/20 flex items-start gap-3">
              <app-icon name="info" [size]="14" class="text-amber-400 mt-0.5 shrink-0" />
              <div class="text-[11px] text-amber-200/90 leading-relaxed">
                Systems are created locally as <span class="font-semibold">drafts</span>. The backend
                orchestrator registers agents at boot — a draft keeps all its configuration and is
                runnable in the playground once paired with an existing agent shell.
              </div>
            </div>
          </div>
        }
      </section>

      <!-- Side pane — live summary -->
      <aside class="t-card rounded-md p-5 self-start sticky top-4">
        <div class="flex items-center gap-2 mb-4">
          <div class="w-9 h-9 rounded-md flex items-center justify-center bg-gradient-to-br from-brand-500/20 to-violet-500/20 ring-1 ring-brand-500/30 text-brand-400">
            <app-icon [name]="currentIcon()" [size]="16" />
          </div>
          <div>
            <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
              Live preview
            </div>
            <div class="text-sm text-white font-medium">{{ draft.name || 'New system' }}</div>
          </div>
        </div>

        <ul class="space-y-2.5 text-xs">
          <li class="flex items-center gap-2">
            <app-icon name="tag" [size]="12" class="text-brand-400" />
            <span class="text-gray-400">Identity</span>
            <span class="ml-auto text-gray-300 truncate max-w-[160px]">
              {{ draft.name || '—' }}
            </span>
          </li>
          <li class="flex items-center gap-2">
            <app-icon name="database" [size]="12" class="text-brand-400" />
            <span class="text-gray-400">Knowledge</span>
            <span class="ml-auto text-gray-300 truncate max-w-[160px]">
              {{ draft.collections.length }} · {{ draft.rag_mode }}
            </span>
          </li>
          <li class="flex items-center gap-2">
            <app-icon name="cpu" [size]="12" class="text-brand-400" />
            <span class="text-gray-400">Model</span>
            <span class="ml-auto text-gray-300 font-mono truncate max-w-[160px]">
              {{ draft.model }}
            </span>
          </li>
          <li class="flex items-center gap-2">
            <app-icon name="shield-check" [size]="12" class="text-brand-400" />
            <span class="text-gray-400">Guardrails</span>
            <span class="ml-auto text-gray-300 font-mono">
              k={{ draft.top_k }}, τ={{ draft.similarity_threshold.toFixed(2) }}
            </span>
          </li>
        </ul>

        @if (!isStepValid(currentStep())) {
          <div class="mt-4 text-[11px] text-amber-300 flex items-start gap-2">
            <app-icon name="alert-triangle" [size]="12" class="mt-0.5" />
            <span>{{ validationMessage() }}</span>
          </div>
        }
      </aside>
    </div>

    <!-- Nav -->
    <div class="flex items-center justify-between mt-8">
      <button
        type="button"
        (click)="prev()"
        [disabled]="currentStep() === 0"
        class="inline-flex items-center gap-1.5 px-4 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed text-gray-200 ring-1 ring-white/10 transition"
      >
        <app-icon name="arrow-left" [size]="14" /> Previous
      </button>
      <div class="text-[11px] text-gray-500">
        Step {{ currentStep() + 1 }} of {{ steps.length }}
      </div>
      @if (currentStep() < steps.length - 1) {
        <button
          type="button"
          (click)="next()"
          [disabled]="!isStepValid(currentStep())"
          class="inline-flex items-center gap-1.5 px-4 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 disabled:opacity-40 disabled:cursor-not-allowed text-white shadow-glow-sm transition"
        >
          Next <app-icon name="arrow-right" [size]="14" />
        </button>
      } @else {
        <button
          type="button"
          (click)="launch()"
          [disabled]="!allStepsValid()"
          class="inline-flex items-center gap-1.5 px-4 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 disabled:opacity-40 disabled:cursor-not-allowed text-white shadow-glow-sm transition"
        >
          <app-icon name="rocket" [size]="14" /> Create system
        </button>
      }
    </div>
  `,
})
export class SystemBuilderComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastrService);
  private readonly store = inject(SystemsStore);
  readonly settings = inject(SettingsService);

  readonly templates = TEMPLATES;
  readonly ragModes = [
    { id: 'OmniRAG', label: 'OmniRAG', description: 'Hybrid dense + BM25 + rerank' },
    { id: 'Semantic', label: 'Semantic', description: 'Dense vectors only' },
    { id: 'Hybrid', label: 'Hybrid', description: 'Dense + lexical merge' },
    { id: 'None', label: 'No RAG', description: 'Pure LLM, no retrieval' },
  ];

  readonly steps: WizardStep[] = [
    { key: 'identity', title: 'Identity', description: 'Name, objective, prompt', icon: 'tag' },
    { key: 'knowledge', title: 'Knowledge', description: 'Collections & retrieval', icon: 'database' },
    { key: 'model', title: 'Model', description: 'LLM & generation', icon: 'cpu' },
    { key: 'guardrails', title: 'Guardrails', description: 'Policy & safety', icon: 'shield-check' },
    { key: 'launch', title: 'Launch', description: 'Review & create', icon: 'rocket' },
  ];

  readonly currentStep = signal(0);
  readonly furthestReached = signal(0);

  readonly collections = signal<string[]>([]);
  readonly loadingCollections = signal(false);
  readonly models = signal<ModelInfo[]>([]);
  readonly loadingModels = signal(false);

  draft = {
    name: '',
    description: '',
    template: '',
    prompt: '',
    collections: [] as string[],
    rag_mode: 'OmniRAG',
    model: 'gpt-4o-mini',
    temperature: 0.3,
    max_tokens: 2048,
    top_k: 8,
    similarity_threshold: 0.5,
    require_citations: true,
    enable_audit: true,
    auto_evaluate: false,
  };

  readonly currentIcon = computed(() => this.steps[this.currentStep()]?.icon ?? 'sparkles');

  ngOnInit(): void {
    const q = this.route.snapshot.queryParamMap;
    if (q.get('prompt')) {
      this.draft.prompt = q.get('prompt') ?? '';
      this.draft.description = q.get('prompt') ?? '';
    }
    if (q.get('name')) {
      this.draft.name = q.get('name') ?? '';
    }
    if (q.get('template')) {
      const tpl = TEMPLATES.find((t) => t.id === q.get('template'));
      if (tpl) this.applyTemplate(tpl);
    }
    this.settings.refresh();
    this.loadingCollections.set(true);
    this.loadingModels.set(true);
    forkJoin({
      collections: this.api
        .get<{ collections: string[] }>('/documents/collections')
        .pipe(catchError(() => of({ collections: [] }))),
      models: this.api
        .get<{ models: ModelInfo[] } | ModelInfo[]>('/models')
        .pipe(catchError(() => of({ models: [] }))),
    }).subscribe(({ collections, models }) => {
      const cols = collections?.collections ?? [];
      this.collections.set(cols);
      if (cols.length && this.draft.collections.length === 0) {
        this.draft.collections = [cols[0]];
      }
      const rawModels = Array.isArray(models) ? models : models?.models ?? [];
      this.models.set(rawModels);
      const s = this.settings.settings();
      if (s.defaultModel) this.draft.model = s.defaultModel;
      if (typeof s.temperature === 'number') this.draft.temperature = s.temperature;
      if (typeof s.maxTokens === 'number') this.draft.max_tokens = s.maxTokens;
      if (typeof s.ragTopK === 'number') this.draft.top_k = s.ragTopK;
      if (typeof s.ragSimilarityThreshold === 'number') {
        this.draft.similarity_threshold = s.ragSimilarityThreshold;
      }
      this.loadingCollections.set(false);
      this.loadingModels.set(false);
    });
  }

  applyTemplate(tpl: Template): void {
    this.draft.template = tpl.id;
    if (!this.draft.name) this.draft.name = tpl.label;
    if (!this.draft.description) this.draft.description = tpl.description;
    this.draft.prompt = tpl.prompt;
  }

  selectModel(m: ModelInfo): void {
    this.draft.model = m.id;
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
      case 2:
      case 3:
        return true;
      case 4:
        return this.draft.name.trim().length > 0 && !!this.draft.model;
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
        return 'A name is required to continue.';
      case 4:
        return 'Fill the name in step 1 before launching.';
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
    if (!this.allStepsValid()) return;
    const draft = this.store.createDraft({
      name: this.draft.name.trim(),
      description: this.draft.description.trim(),
      template: this.draft.template,
      model: this.draft.model,
      rag_mode: this.draft.rag_mode,
      prompt: this.draft.prompt,
    });
    this.toast.success(`"${draft.name}" is ready to configure`, 'System created');
    this.router.navigate(['/systems', draft.id]);
  }
}
