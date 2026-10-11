import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { ToastrService } from 'ngx-toastr';

import { CkBackLinkComponent } from '@app/shared/cockpit';
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
import { I18nService } from '@app/core/i18n.service';
import {
  WorkspaceRequestInvalidatedError,
  WorkspaceService,
} from '@app/core/workspace.service';
import type { AppSettings } from '@app/core/settings.service';

type PresetTab = 'generation' | 'retrieval' | 'chunking' | 'experience';

// Vendor names are data, not chrome — they stay literal.
const PROVIDERS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'ollama', label: 'Ollama' },
];

// Labels come from `presets.mode.<value>` / `presets.chunking.<value>`.
const PIPELINE_MODES = ['auto', 'naive', 'hybrid', 'hah', 'chah'] as const;

const CHUNKING_METHODS = [
  'recursive_character',
  'sentence',
  'markdown',
  'semantic',
] as const;

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
    CkBackLinkComponent,
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
          <span class="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-300 ring-1 ring-cyan-500/40">
            {{ i18n.t('presets.badge.default') }}
          </span>
        }
        @if (dirty()) {
          <span class="text-[10px] uppercase tracking-wider text-gray-400">
            {{ i18n.t('presets.view.unsaved') }}
          </span>
        }
      </div>
      <button
        actions
        type="button"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
        (click)="impactPanelOpen.set(true)"
      >
        {{ i18n.t('presets.view.impact.cta') }}
      </button>
      @if (!preset()?.is_default) {
        <button
          actions
          type="button"
          class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
          (click)="setAsDefault()"
        >
          {{ i18n.t('presets.action.default') }}
        </button>
      }
      <button
        actions
        type="button"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-cyan-500 hover:bg-cyan-600 text-white transition disabled:opacity-50"
        (click)="save()"
        [disabled]="!dirty() || saving()"
      >
        {{ saving() ? i18n.t('presets.saving') : i18n.t('presets.view.save.cta') }}
      </button>
    </ck-object-header>

    @if (loading()) {
      <div class="ck-surface rounded-md p-5 text-center text-xs text-gray-400">
        {{ i18n.t('presets.view.loading') }}
      </div>
    } @else if (!preset()) {
      <div class="ck-surface rounded-md p-8 text-center">
        <h3 class="text-sm font-semibold text-white mb-2">{{ i18n.t('presets.view.notfound.title') }}</h3>
        <ck-back-link />
      </div>
    } @else {
      <ck-tabs
        [active]="activeTab()"
        (activeChange)="onTabChange($event)"
        [ariaLabel]="i18n.t('presets.view.tabs.aria')"
      >
        <ck-tab id="generation" [label]="i18n.t('presets.tab.generation')">
          <section class="ck-surface t-elevated rounded-md p-5 space-y-4">
            @if (isDemoMode()) {
              <div class="rounded-md bg-white/5 ring-1 ring-white/10 p-4">
                <div class="text-sm font-semibold text-white">{{ i18n.t('presets.view.managed.title') }}</div>
                <p class="text-xs text-gray-400 mt-2">
                  {{ i18n.t('presets.view.managed.body') }}
                </p>
              </div>
            } @else {
              <div>
                <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                  {{ i18n.t('presets.field.provider') }}
                </label>
                <div class="grid grid-cols-3 gap-1.5 mt-1.5">
                  @for (p of providers; track p.value) {
                    <button
                      type="button"
                      class="px-3 py-2 rounded text-xs font-medium ring-1 transition"
                      [class.bg-cyan-500\\/15]="draft().defaultProvider === p.value"
                      [class.text-cyan-200]="draft().defaultProvider === p.value"
                      [class.ring-cyan-500\\/40]="draft().defaultProvider === p.value"
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
                  {{ i18n.t('presets.field.model') }}
                </label>
                <input
                  type="text"
                  [ngModel]="draft().defaultModel"
                  (ngModelChange)="patch({ defaultModel: $event })"
                  class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-cyan-500/60"
                  [placeholder]="i18n.t('presets.field.model.placeholder')"
                />
              </div>
            }
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                  {{ i18n.t('presets.field.temperature') }}
                </label>
                <input
                  type="number"
                  min="0" max="2" step="0.05"
                  [ngModel]="draft().temperature"
                  (ngModelChange)="patch({ temperature: +$event })"
                  class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-cyan-500/60"
                />
              </div>
              <div>
                <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                  {{ i18n.t('presets.field.tokens') }}
                </label>
                <input
                  type="number"
                  min="128" max="32000" step="128"
                  [ngModel]="draft().maxTokens"
                  (ngModelChange)="patch({ maxTokens: +$event })"
                  class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-cyan-500/60"
                />
              </div>
            </div>
          </section>
        </ck-tab>

        <ck-tab id="retrieval" [label]="i18n.t('presets.tab.retrieval')">
          <section class="ck-surface t-elevated rounded-md p-5 space-y-4">
            <div>
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                Pipeline mode
              </label>
              <div class="flex flex-wrap gap-1.5 mt-1.5">
                @for (m of pipelineModes; track m) {
                  <button
                    type="button"
                    class="px-3 py-1.5 rounded text-xs font-medium ring-1 transition"
                    [class.bg-cyan-500\\/15]="draft().ragPipelineMode === m"
                    [class.text-cyan-200]="draft().ragPipelineMode === m"
                    [class.ring-cyan-500\\/40]="draft().ragPipelineMode === m"
                    [class.bg-white\\/5]="draft().ragPipelineMode !== m"
                    [class.text-gray-300]="draft().ragPipelineMode !== m"
                    [class.ring-white\\/10]="draft().ragPipelineMode !== m"
                    (click)="patch({ ragPipelineMode: m })"
                  >
                    {{ modeLabel(m) }}
                  </button>
                }
              </div>
            </div>
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                  {{ i18n.t('presets.field.topk') }}
                </label>
                <input
                  type="number"
                  min="1" max="50" step="1"
                  [ngModel]="draft().ragTopK"
                  (ngModelChange)="patch({ ragTopK: +$event })"
                  class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-cyan-500/60"
                />
              </div>
              <div>
                <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                  {{ i18n.t('presets.field.similarity') }}
                </label>
                <input
                  type="number"
                  min="0" max="1" step="0.05"
                  [ngModel]="draft().ragSimilarityThreshold"
                  (ngModelChange)="patch({ ragSimilarityThreshold: +$event })"
                  class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-cyan-500/60"
                />
              </div>
            </div>
            <label class="flex items-center gap-2 text-xs text-gray-200 cursor-pointer">
              <input
                type="checkbox"
                [checked]="!!draft().ragUseHybridSearch"
                (change)="patch({ ragUseHybridSearch: $any($event.target).checked })"
                class="accent-cyan-500"
              />
              {{ i18n.t('presets.retrieval.hybrid') }}
            </label>
            @if (draft().ragUseHybridSearch) {
              <div class="grid grid-cols-2 gap-4">
                <div>
                  <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                    {{ i18n.t('presets.retrieval.weight.vector') }}
                  </label>
                  <input
                    type="number"
                    min="0" max="1" step="0.05"
                    [ngModel]="draft().ragVectorWeight"
                    (ngModelChange)="patch({ ragVectorWeight: +$event })"
                    class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-cyan-500/60"
                  />
                </div>
                <div>
                  <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                    {{ i18n.t('presets.retrieval.weight.sparse') }}
                  </label>
                  <input
                    type="number"
                    min="0" max="1" step="0.05"
                    [ngModel]="draft().ragBM25Weight"
                    (ngModelChange)="patch({ ragBM25Weight: +$event })"
                    class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-cyan-500/60"
                  />
                </div>
              </div>
            }
          </section>
        </ck-tab>

        <ck-tab id="chunking" [label]="i18n.t('presets.tab.chunking')">
          <section class="ck-surface t-elevated rounded-md p-5 space-y-4">
            <div>
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                {{ i18n.t('presets.chunking.method') }}
              </label>
              <div class="grid grid-cols-2 gap-1.5 mt-1.5">
                @for (m of chunkingMethods; track m) {
                  <button
                    type="button"
                    class="px-3 py-2 rounded text-xs font-medium ring-1 transition text-left"
                    [class.bg-cyan-500\\/15]="draft()['ragChunkingMethod'] === m"
                    [class.text-cyan-200]="draft()['ragChunkingMethod'] === m"
                    [class.ring-cyan-500\\/40]="draft()['ragChunkingMethod'] === m"
                    [class.bg-white\\/5]="draft()['ragChunkingMethod'] !== m"
                    [class.text-gray-300]="draft()['ragChunkingMethod'] !== m"
                    [class.ring-white\\/10]="draft()['ragChunkingMethod'] !== m"
                    (click)="patch({ ragChunkingMethod: m })"
                  >
                    {{ chunkingLabel(m) }}
                  </button>
                }
              </div>
            </div>
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                  {{ i18n.t('presets.chunking.size') }}
                </label>
                <input
                  type="number"
                  min="128" max="8000" step="64"
                  [ngModel]="draft().ragChunkSize"
                  (ngModelChange)="patch({ ragChunkSize: +$event })"
                  class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-cyan-500/60"
                />
              </div>
              <div>
                <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
                  {{ i18n.t('presets.chunking.overlap') }}
                </label>
                <input
                  type="number"
                  min="0" max="2000" step="16"
                  [ngModel]="draft().ragChunkOverlap"
                  (ngModelChange)="patch({ ragChunkOverlap: +$event })"
                  class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-cyan-500/60"
                />
              </div>
            </div>
          </section>
        </ck-tab>

        <ck-tab id="experience" [label]="i18n.t('presets.tab.experience')">
          <section class="ck-surface t-elevated rounded-md p-5 space-y-3">
            <label class="flex items-center gap-2 text-xs text-gray-200 cursor-pointer">
              <input
                type="checkbox"
                [checked]="!!draft().enableStreaming"
                (change)="patch({ enableStreaming: $any($event.target).checked })"
                class="accent-cyan-500"
              />
              {{ i18n.t('presets.experience.streaming') }}
            </label>
            <label class="flex items-center gap-2 text-xs text-gray-200 cursor-pointer">
              <input
                type="checkbox"
                [checked]="!!draft().showReasoningTraces"
                (change)="patch({ showReasoningTraces: $any($event.target).checked })"
                class="accent-cyan-500"
              />
              {{ i18n.t('presets.experience.reasoning') }}
            </label>
            <label class="flex items-center gap-2 text-xs text-gray-200 cursor-pointer">
              <input
                type="checkbox"
                [checked]="!!draft().showSources"
                (change)="patch({ showSources: $any($event.target).checked })"
                class="accent-cyan-500"
              />
              {{ i18n.t('presets.experience.sources') }}
            </label>
            <label class="flex items-center gap-2 text-xs text-gray-200 cursor-pointer">
              <input
                type="checkbox"
                [checked]="!!draft().autoExpandReasoning"
                (change)="patch({ autoExpandReasoning: $any($event.target).checked })"
                class="accent-cyan-500"
              />
              {{ i18n.t('presets.experience.expand') }}
            </label>
          </section>
        </ck-tab>
      </ck-tabs>
    }

    <ck-panel
      [open]="impactPanelOpen()"
      (openChange)="impactPanelOpen.set($event)"
      position="side"
      [eyebrow]="i18n.t('presets.view.impact.eyebrow')"
      [title]="i18n.t('presets.view.impact.cta')"
      width="420px"
    >
      <p class="text-xs text-gray-400 mb-3">
        {{ i18n.t('presets.view.impact.description') }}
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
            {{ i18n.t('presets.view.impact.empty') }}
          </li>
        }
      </ul>
    </ck-panel>
  `,
})
export class PresetViewComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly navigation = inject(ZoomContextService);
  private readonly service = inject(RagPresetService);
  private readonly toastr = inject(ToastrService);
  private readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);
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

  readonly title = computed(
    () => this.preset()?.name ?? this.i18n.t('presets.view.title.fallback'),
  );

  readonly eyebrow = computed(() => {
    const p = this.preset();
    if (!p) return this.i18n.t('presets.view.eyebrow');
    return this.i18n.t('presets.view.eyebrow.scoped', { scope: this.scopeShortLabel(p.scope) });
  });

  readonly subtitle = computed(() => {
    const p = this.preset();
    if (!p) return '';
    return p.scope === 'workspace'
      ? this.i18n.t('presets.view.subtitle.workspace')
      : p.scope === 'capability'
        ? this.i18n.t('presets.view.subtitle.capability')
        : this.i18n.t('presets.view.subtitle.system');
  });

  readonly kpis = computed<CkObjectKpi[]>(() => {
    const cfg = this.draft();
    return [
      {
        label: this.isDemoMode()
          ? this.i18n.t('presets.field.runtime')
          : this.i18n.t('presets.field.provider'),
        value: this.isDemoMode()
          ? this.i18n.t('presets.value.managed')
          : String(cfg.defaultProvider ?? '—'),
      },
      {
        label: this.i18n.t('presets.field.mode'),
        value: String(cfg.ragPipelineMode ?? (cfg.ragUseHybridSearch ? 'hybrid' : 'vector')),
        tone: 'cool',
      },
      { label: this.i18n.t('presets.field.topk'), value: String(cfg.ragTopK ?? '—'), tone: 'violet' },
      {
        label: this.i18n.t('presets.field.hybrid'),
        value: cfg.ragUseHybridSearch
          ? this.i18n.t('presets.state.on')
          : this.i18n.t('presets.state.off'),
        tone: cfg.ragUseHybridSearch ? 'pos' : 'neutral',
      },
    ];
  });

  /**
   * Short scope name (`presets.scope.<value>`), falling back to the raw
   * value if the backend ever grows a scope the dictionary doesn't know.
   */
  scopeShortLabel(scope: string): string {
    const key = `presets.scope.${scope}`;
    const label = this.i18n.t(key);
    return label === key ? scope : label;
  }

  /** Display name of a retrieval mode, falling back to the raw value. */
  modeLabel(mode: string): string {
    const key = `presets.mode.${mode}`;
    const label = this.i18n.t(key);
    return label === key ? mode : label;
  }

  /** Display name of a chunking method, falling back to the raw value. */
  chunkingLabel(method: string): string {
    const key = `presets.chunking.${method}`;
    const label = this.i18n.t(key);
    return label === key ? method : label;
  }

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
    const facet = this.route.snapshot.queryParamMap.get('facet');
    if (facet) this.activeTab.set(facet as PresetTab);
    this.route.paramMap.subscribe((params) => {
      const id = params.get('presetId');
      if (!id) {
        void this.router.navigateByUrl(this.navigation.surfaceUrl('presets'));
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
      .catch((error: unknown) => {
        if (!(error instanceof WorkspaceRequestInvalidatedError)) this.preset.set(null);
      })
      .finally(() => this.loading.set(false));
  }

  onTabChange(id: string): void {
    this.activeTab.set(id as PresetTab);
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { facet: id },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
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
        this.toastr.success(this.i18n.t('presets.toast.save.success'));
      })
      .catch((error: unknown) => {
        if (!(error instanceof WorkspaceRequestInvalidatedError)) {
          this.toastr.error(this.i18n.t('presets.toast.save.error'));
        }
      })
      .finally(() => this.saving.set(false));
  }

  setAsDefault(): void {
    const p = this.preset();
    if (!p) return;
    this.service
      .setDefault(p.id)
      .then((updated) => {
        this.preset.set(updated);
        this.toastr.success(this.i18n.t('presets.view.toast.default'));
      })
      .catch((error: unknown) => {
        if (!(error instanceof WorkspaceRequestInvalidatedError)) {
          this.toastr.error(this.i18n.t('presets.view.toast.default.error'));
        }
      });
  }
}
