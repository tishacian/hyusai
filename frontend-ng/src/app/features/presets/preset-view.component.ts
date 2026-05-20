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
import { ToastrService } from 'ngx-toastr';

import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { CkTabsComponent, CkTabComponent } from '@app/shared/cockpit/tabs.component';
import { CkPanelComponent } from '@app/shared/cockpit/panel.component';
import {
  RagPresetService,
  type RagPreset,
} from '@app/core/rag-preset.service';
import { WorkspaceService } from '@app/core/workspace.service';
import type { AppSettings } from '@app/core/settings.service';

type PresetTab = 'generation' | 'retrieval' | 'chunking' | 'experience';

const PROVIDERS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'ollama', label: 'Ollama' },
];

const PIPELINE_MODES = [
  { value: 'auto', label: 'Auto' },
  { value: 'naive', label: 'Naive' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'hah', label: 'HAH' },
  { value: 'chah', label: 'CHAH' },
];

const CHUNKING_METHODS = [
  { value: 'recursive_character', label: 'Recursive character' },
  { value: 'sentence', label: 'Sentence' },
  { value: 'markdown', label: 'Markdown-aware' },
  { value: 'semantic', label: 'Semantic' },
];

/**
 * Detail page for a single RAG Preset.
 *
 * Follows the `<ck-object-header>` + `<ck-tabs>` contract: the header is
 * invariant across facets (Generation / Retrieval / Chunking / Experience)
 * and the tab panels preserve their local state. Secondary views
 * (Impact preview, Compare with default) live in opportunistic
 * `<ck-panel>` overlays so they never steal canvas real estate.
 */
@Component({
  selector: 'app-preset-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    FormsModule,
    CkObjectHeaderComponent,
    CkTabsComponent,
    CkTabComponent,
    CkPanelComponent,
  ],
  template: `
    <ck-object-header
      [eyebrow]="eyebrow()"
      [title]="title()"
      [subtitle]="subtitle()"
      [kpis]="kpis()"
    >
      <div status class="flex items-center gap-2">
        @if (preset()?.is_default) {
          <span class="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-brand-500/15 text-brand-300 ring-1 ring-brand-500/40">
            Default
          </span>
        }
        @if (dirty()) {
          <span class="text-[10px] uppercase tracking-wider text-gray-400">
            Unsaved
          </span>
        }
      </div>
      <button
        actions
        type="button"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
        (click)="impactPanelOpen.set(true)"
      >
        Impact preview
      </button>
      @if (!preset()?.is_default) {
        <button
          actions
          type="button"
          class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
          (click)="setAsDefault()"
        >
          Set default
        </button>
      }
      <button
        actions
        type="button"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white transition disabled:opacity-50"
        (click)="save()"
        [disabled]="!dirty() || saving()"
      >
        {{ saving() ? 'Saving…' : 'Save changes' }}
      </button>
    </ck-object-header>

    @if (loading()) {
      <div class="t-card rounded-md p-5 text-center text-xs text-gray-400">
        Loading preset…
      </div>
    } @else if (!preset()) {
      <div class="t-card rounded-md p-8 text-center">
        <h3 class="text-sm font-semibold text-white mb-2">Preset not found</h3>
        <a routerLink="/presets" class="text-xs text-brand-300 hover:underline">
          Back to catalog
        </a>
      </div>
    } @else {
      <ck-tabs
        [active]="activeTab()"
        (activeChange)="onTabChange($event)"
        ariaLabel="Preset facets"
      >
        <ck-tab id="generation" label="Generation">
          <section class="t-card t-elevated rounded-md p-5 space-y-4">
            @if (isDemoMode()) {
              <div class="rounded-md bg-white/5 ring-1 ring-white/10 p-4">
                <div class="text-sm font-semibold text-white">Managed runtime</div>
                <p class="text-xs text-gray-400 mt-2">
                  Provider and model names are hidden by demo-safe presentation.
                </p>
              </div>
            } @else {
              <div>
                <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                  Provider
                </label>
                <div class="grid grid-cols-3 gap-1.5 mt-1.5">
                  @for (p of providers; track p.value) {
                    <button
                      type="button"
                      class="px-3 py-2 rounded text-xs font-medium ring-1 transition"
                      [class.bg-brand-500\\/15]="draft().defaultProvider === p.value"
                      [class.text-brand-200]="draft().defaultProvider === p.value"
                      [class.ring-brand-500\\/40]="draft().defaultProvider === p.value"
                      [class.bg-white\\/5]="draft().defaultProvider !== p.value"
                      [class.text-gray-300]="draft().defaultProvider !== p.value"
                      [class.ring-white\\/10]="draft().defaultProvider !== p.value"
                      (click)="patch({ defaultProvider: p.value })"
                    >
                      {{ p.label }}
                    </button>
                  }
                </div>
              </div>
              <div>
                <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                  Model
                </label>
                <input
                  type="text"
                  [ngModel]="draft().defaultModel"
                  (ngModelChange)="patch({ defaultModel: $event })"
                  class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-brand-500/60"
                  placeholder="e.g. gpt-4o-mini"
                />
              </div>
            }
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                  Temperature
                </label>
                <input
                  type="number"
                  min="0" max="2" step="0.05"
                  [ngModel]="draft().temperature"
                  (ngModelChange)="patch({ temperature: +$event })"
                  class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-brand-500/60"
                />
              </div>
              <div>
                <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                  Max tokens
                </label>
                <input
                  type="number"
                  min="128" max="32000" step="128"
                  [ngModel]="draft().maxTokens"
                  (ngModelChange)="patch({ maxTokens: +$event })"
                  class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-brand-500/60"
                />
              </div>
            </div>
          </section>
        </ck-tab>

        <ck-tab id="retrieval" label="Retrieval">
          <section class="t-card t-elevated rounded-md p-5 space-y-4">
            <div>
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                Pipeline mode
              </label>
              <div class="flex flex-wrap gap-1.5 mt-1.5">
                @for (m of pipelineModes; track m.value) {
                  <button
                    type="button"
                    class="px-3 py-1.5 rounded text-xs font-medium ring-1 transition"
                    [class.bg-brand-500\\/15]="draft().ragPipelineMode === m.value"
                    [class.text-brand-200]="draft().ragPipelineMode === m.value"
                    [class.ring-brand-500\\/40]="draft().ragPipelineMode === m.value"
                    [class.bg-white\\/5]="draft().ragPipelineMode !== m.value"
                    [class.text-gray-300]="draft().ragPipelineMode !== m.value"
                    [class.ring-white\\/10]="draft().ragPipelineMode !== m.value"
                    (click)="patch({ ragPipelineMode: $any(m.value) })"
                  >
                    {{ m.label }}
                  </button>
                }
              </div>
            </div>
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                  Top-K
                </label>
                <input
                  type="number"
                  min="1" max="50" step="1"
                  [ngModel]="draft().ragTopK"
                  (ngModelChange)="patch({ ragTopK: +$event })"
                  class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-brand-500/60"
                />
              </div>
              <div>
                <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                  Similarity threshold
                </label>
                <input
                  type="number"
                  min="0" max="1" step="0.05"
                  [ngModel]="draft().ragSimilarityThreshold"
                  (ngModelChange)="patch({ ragSimilarityThreshold: +$event })"
                  class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-brand-500/60"
                />
              </div>
            </div>
            <label class="flex items-center gap-2 text-xs text-gray-200 cursor-pointer">
              <input
                type="checkbox"
                [checked]="!!draft().ragUseHybridSearch"
                (change)="patch({ ragUseHybridSearch: $any($event.target).checked })"
                class="accent-brand-500"
              />
              Use hybrid search (vector + BM25)
            </label>
            @if (draft().ragUseHybridSearch) {
              <div class="grid grid-cols-2 gap-4">
                <div>
                  <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                    Vector weight
                  </label>
                  <input
                    type="number"
                    min="0" max="1" step="0.05"
                    [ngModel]="draft().ragVectorWeight"
                    (ngModelChange)="patch({ ragVectorWeight: +$event })"
                    class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-brand-500/60"
                  />
                </div>
                <div>
                  <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                    BM25 weight
                  </label>
                  <input
                    type="number"
                    min="0" max="1" step="0.05"
                    [ngModel]="draft().ragBM25Weight"
                    (ngModelChange)="patch({ ragBM25Weight: +$event })"
                    class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-brand-500/60"
                  />
                </div>
              </div>
            }
          </section>
        </ck-tab>

        <ck-tab id="chunking" label="Chunking">
          <section class="t-card t-elevated rounded-md p-5 space-y-4">
            <div>
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                Method
              </label>
              <div class="grid grid-cols-2 gap-1.5 mt-1.5">
                @for (m of chunkingMethods; track m.value) {
                  <button
                    type="button"
                    class="px-3 py-2 rounded text-xs font-medium ring-1 transition text-left"
                    [class.bg-brand-500\\/15]="draft()['ragChunkingMethod'] === m.value"
                    [class.text-brand-200]="draft()['ragChunkingMethod'] === m.value"
                    [class.ring-brand-500\\/40]="draft()['ragChunkingMethod'] === m.value"
                    [class.bg-white\\/5]="draft()['ragChunkingMethod'] !== m.value"
                    [class.text-gray-300]="draft()['ragChunkingMethod'] !== m.value"
                    [class.ring-white\\/10]="draft()['ragChunkingMethod'] !== m.value"
                    (click)="patch({ ragChunkingMethod: m.value })"
                  >
                    {{ m.label }}
                  </button>
                }
              </div>
            </div>
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                  Chunk size
                </label>
                <input
                  type="number"
                  min="128" max="8000" step="64"
                  [ngModel]="draft().ragChunkSize"
                  (ngModelChange)="patch({ ragChunkSize: +$event })"
                  class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-brand-500/60"
                />
              </div>
              <div>
                <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                  Chunk overlap
                </label>
                <input
                  type="number"
                  min="0" max="2000" step="16"
                  [ngModel]="draft().ragChunkOverlap"
                  (ngModelChange)="patch({ ragChunkOverlap: +$event })"
                  class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-brand-500/60"
                />
              </div>
            </div>
          </section>
        </ck-tab>

        <ck-tab id="experience" label="Experience">
          <section class="t-card t-elevated rounded-md p-5 space-y-3">
            <label class="flex items-center gap-2 text-xs text-gray-200 cursor-pointer">
              <input
                type="checkbox"
                [checked]="!!draft().enableStreaming"
                (change)="patch({ enableStreaming: $any($event.target).checked })"
                class="accent-brand-500"
              />
              Enable streaming responses
            </label>
            <label class="flex items-center gap-2 text-xs text-gray-200 cursor-pointer">
              <input
                type="checkbox"
                [checked]="!!draft().showReasoningTraces"
                (change)="patch({ showReasoningTraces: $any($event.target).checked })"
                class="accent-brand-500"
              />
              Show reasoning traces by default
            </label>
            <label class="flex items-center gap-2 text-xs text-gray-200 cursor-pointer">
              <input
                type="checkbox"
                [checked]="!!draft().showSources"
                (change)="patch({ showSources: $any($event.target).checked })"
                class="accent-brand-500"
              />
              Always show sources
            </label>
            <label class="flex items-center gap-2 text-xs text-gray-200 cursor-pointer">
              <input
                type="checkbox"
                [checked]="!!draft().autoExpandReasoning"
                (change)="patch({ autoExpandReasoning: $any($event.target).checked })"
                class="accent-brand-500"
              />
              Auto-expand reasoning panel
            </label>
          </section>
        </ck-tab>
      </ck-tabs>
    }

    <ck-panel
      [open]="impactPanelOpen()"
      (openChange)="impactPanelOpen.set($event)"
      position="side"
      eyebrow="Preset · impact"
      title="Impact preview"
      width="420px"
    >
      <p class="text-xs text-gray-400 mb-3">
        Diff vs the workspace default. This preview is a placeholder — a
        future wave will replay a canonical Run under this preset to show
        the measurable delta (latency, token cost, citation quality).
      </p>
      <ul class="space-y-2 text-xs">
        @for (row of impactRows(); track row.key) {
          <li class="flex items-center justify-between px-3 py-2 rounded bg-white/5 ring-1 ring-white/10">
            <span class="text-gray-300">{{ row.key }}</span>
            <span class="ck-mono text-gray-100">
              {{ row.base }} <span class="text-gray-500">→</span> {{ row.next }}
            </span>
          </li>
        } @empty {
          <li class="text-gray-500 text-xs">
            This preset matches the workspace default.
          </li>
        }
      </ul>
    </ck-panel>
  `,
})
export class PresetViewComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly service = inject(RagPresetService);
  private readonly toastr = inject(ToastrService);
  private readonly workspace = inject(WorkspaceService);
  readonly isDemoMode = computed(() => this.workspace.isDemoSafeMode());

  readonly providers = PROVIDERS;
  readonly pipelineModes = PIPELINE_MODES;
  readonly chunkingMethods = CHUNKING_METHODS;

  readonly preset = signal<RagPreset | null>(null);
  readonly defaultPreset = signal<RagPreset | null>(null);
  readonly draft = signal<AppSettings>({});
  readonly loading = signal(true);
  readonly saving = signal(false);
  readonly activeTab = signal<PresetTab>('generation');
  readonly impactPanelOpen = signal(false);

  readonly dirty = computed(() => {
    const p = this.preset();
    if (!p) return false;
    return JSON.stringify(p.config ?? {}) !== JSON.stringify(this.draft());
  });

  readonly title = computed(() => this.preset()?.name ?? 'Preset');

  readonly eyebrow = computed(() => {
    const p = this.preset();
    if (!p) return 'Govern · Preset';
    return `Govern · Preset · ${p.scope}`;
  });

  readonly subtitle = computed(() => {
    const p = this.preset();
    if (!p) return '';
    const scopeBit = p.scope === 'workspace'
      ? 'Applies workspace-wide when no capability or system preset matches.'
      : p.scope === 'capability'
        ? 'Overrides the workspace default for runs tied to a specific capability.'
        : 'Overrides everything for runs of one specific system.';
    return scopeBit;
  });

  readonly kpis = computed<CkObjectKpi[]>(() => {
    const cfg = this.draft();
    return [
      { label: this.isDemoMode() ? 'Runtime' : 'Provider', value: this.isDemoMode() ? 'Managed' : String(cfg.defaultProvider ?? '—') },
      {
        label: 'Mode',
        value: String(cfg.ragPipelineMode ?? (cfg.ragUseHybridSearch ? 'hybrid' : 'vector')),
        tone: 'cool',
      },
      { label: 'Top-K', value: String(cfg.ragTopK ?? '—'), tone: 'violet' },
      {
        label: 'Hybrid',
        value: cfg.ragUseHybridSearch ? 'On' : 'Off',
        tone: cfg.ragUseHybridSearch ? 'pos' : 'neutral',
      },
    ];
  });

  readonly impactRows = computed<{ key: string; base: string; next: string }[]>(() => {
    const base = this.defaultPreset()?.config ?? {};
    const next = this.draft();
    const keys: (keyof AppSettings)[] = [
      'defaultProvider', 'defaultModel', 'temperature', 'maxTokens',
      'ragPipelineMode', 'ragTopK', 'ragSimilarityThreshold',
      'ragUseHybridSearch', 'ragVectorWeight', 'ragBM25Weight',
      'ragChunkSize', 'ragChunkOverlap',
    ].filter((k) => !this.isDemoMode() || (k !== 'defaultProvider' && k !== 'defaultModel'));
    const rows: { key: string; base: string; next: string }[] = [];
    for (const k of keys) {
      const a = (base as any)[k];
      const b = (next as any)[k];
      if (String(a ?? '') !== String(b ?? '')) {
        rows.push({ key: String(k), base: String(a ?? '—'), next: String(b ?? '—') });
      }
    }
    return rows;
  });

  ngOnInit(): void {
    this.route.paramMap.subscribe((params) => {
      const id = params.get('presetId');
      if (!id) {
        this.router.navigate(['/presets']);
        return;
      }
      this.loadById(id);
    });
  }

  private loadById(id: string): void {
    this.loading.set(true);
    this.service
      .list()
      .then((list) => {
        this.defaultPreset.set(
          list.find((p) => p.scope === 'workspace' && p.is_default) ?? null,
        );
        const found = list.find((p) => p.id === id) ?? null;
        if (found) {
          this.preset.set(found);
          this.draft.set({ ...(found.config ?? {}) });
        }
        return found;
      })
      .then((found) => {
        if (!found) {
          return this.service
            .get(id)
            .then((p) => {
              this.preset.set(p);
              this.draft.set({ ...(p.config ?? {}) });
            })
            .catch(() => {
              this.preset.set(null);
            });
        }
        return undefined;
      })
      .finally(() => this.loading.set(false));
  }

  onTabChange(id: string): void {
    this.activeTab.set(id as PresetTab);
  }

  patch(delta: Partial<AppSettings>): void {
    this.draft.set({ ...this.draft(), ...delta });
  }

  save(): void {
    const p = this.preset();
    if (!p) return;
    this.saving.set(true);
    this.service
      .update(p.id, { config: this.draft() })
      .then((updated) => {
        this.preset.set(updated);
        this.draft.set({ ...(updated.config ?? {}) });
        this.toastr.success('Preset saved');
      })
      .catch(() => this.toastr.error('Failed to save preset'))
      .finally(() => this.saving.set(false));
  }

  setAsDefault(): void {
    const p = this.preset();
    if (!p) return;
    this.service
      .setDefault(p.id)
      .then((updated) => {
        this.preset.set(updated);
        this.toastr.success('Preset is now default');
      })
      .catch(() => this.toastr.error('Failed to elect default'));
  }
}
