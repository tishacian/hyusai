import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ToastrService } from 'ngx-toastr';
import { I18nService } from '@app/core/i18n.service';
import { SettingsService, AppSettings } from '@app/core/settings.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';

interface ProviderOption {
  value: string;
  /** Raw fallback only — the rendered name comes from `settings.provider.<value>`. */
  label: string;
  models: string[];
}

const PROVIDERS: ProviderOption[] = [
  { value: 'openai', label: 'OpenAI', models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo'] },
  { value: 'anthropic', label: 'Anthropic', models: ['claude-3-5-sonnet', 'claude-3-opus', 'claude-3-haiku'] },
  { value: 'ollama', label: 'Ollama (self-hosted)', models: ['deepseek-r1:14b', 'llama3.1:8b', 'qwen2.5:14b', 'mixtral'] },
];

// Labels and descriptions come from `settings.mode.<value>` / `.desc`.
const RAG_MODES = ['auto', 'naive', 'hybrid', 'hah', 'chah'] as const;

@Component({
  selector: 'app-rag-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, IconComponent, SectionHeaderComponent],
  template: `
    <app-section-header
      [breadcrumb]="i18n.t('settings.breadcrumb')"
      [title]="i18n.t('settings.title')"
      icon="sliders-horizontal"
      [subtitle]="i18n.t('settings.description')"
    >
      <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mr-2">
        {{ dirty() ? i18n.t('settings.state.unsaved') : i18n.t('settings.state.synced') }}
      </span>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        (click)="resetDraft()"
        [disabled]="!dirty()"
      >
        <app-icon name="rotate-ccw" [size]="14" /> {{ i18n.t('settings.reset.cta') }}
      </button>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-cyan-500 hover:bg-cyan-600 text-white transition disabled:opacity-50"
        (click)="save()"
        [disabled]="!dirty() || saving()"
      >
        <app-icon [name]="saving() ? 'loader-2' : 'save'" [size]="14" [class.animate-spin]="saving()" />
        {{ saving() ? i18n.t('settings.saving') : i18n.t('settings.save.cta') }}
      </button>
    </app-section-header>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <!-- Model / generation -->
      <section class="ck-surface rounded-md p-5">
        <div class="flex items-center gap-2 mb-4">
          <app-icon name="cpu" [size]="16" class="text-cyan-400" />
          <h3 class="text-sm font-semibold text-white">{{ isDemoMode() ? i18n.t('settings.generation.title.managed') : i18n.t('settings.generation.title') }}</h3>
        </div>

        <div class="space-y-4">
          @if (isDemoMode()) {
            <div class="rounded-md bg-white/5 ring-1 ring-white/10 p-4">
              <div class="flex items-center gap-2 text-sm font-semibold text-white">
                <app-icon name="shield-check" [size]="15" class="text-cyan-300" />
                {{ i18n.t('settings.generation.managed.title') }}
              </div>
              <p class="text-xs text-gray-400 mt-2 leading-relaxed">
                {{ i18n.t('settings.generation.managed.body') }}
              </p>
            </div>
          } @else {
            <div>
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">{{ i18n.t('settings.generation.provider') }}</label>
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
                    (click)="setProvider(p.value)"
                  >
                    {{ providerLabel(p) }}
                  </button>
                }
              </div>
            </div>

            <div>
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">{{ i18n.t('settings.generation.model') }}</label>
              <select
                class="settings-select mt-1.5 w-full"
                [ngModel]="draft().defaultModel"
                (ngModelChange)="patch({ defaultModel: $event })"
                name="model"
              >
                @for (m of availableModels(); track m) {
                  <option [value]="m">{{ m }}</option>
                }
              </select>
            </div>
          }

          <div>
            <div class="flex justify-between items-baseline">
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">{{ i18n.t('settings.generation.temperature') }}</label>
              <span class="font-mono text-xs text-cyan-300">{{ fmt(draft().temperature, 2) }}</span>
            </div>
            <input
              type="range"
              min="0"
              max="2"
              step="0.05"
              class="w-full mt-1.5 accent-cyan-500"
              [ngModel]="draft().temperature"
              (ngModelChange)="patch({ temperature: +$event })"
              name="temp"
            />
            <p class="text-[10px] text-gray-500 mt-1">{{ i18n.t('settings.generation.temperature.hint') }}</p>
          </div>

          <div>
            <div class="flex justify-between items-baseline">
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">{{ i18n.t('settings.generation.tokens') }}</label>
              <span class="font-mono text-xs text-cyan-300">{{ draft().maxTokens }}</span>
            </div>
            <input
              type="range"
              min="256"
              max="8000"
              step="128"
              class="w-full mt-1.5 accent-cyan-500"
              [ngModel]="draft().maxTokens"
              (ngModelChange)="patch({ maxTokens: +$event })"
              name="maxTokens"
            />
          </div>
        </div>
      </section>

      <!-- RAG pipeline -->
      <section class="ck-surface rounded-md p-5">
        <div class="flex items-center gap-2 mb-4">
          <app-icon name="database" [size]="16" class="text-cyan-400" />
          <h3 class="text-sm font-semibold text-white">Retrieval pipeline</h3>
        </div>

        <div class="space-y-4">
          <div>
            <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">Pipeline mode</label>
            <div class="grid grid-cols-5 gap-1.5 mt-1.5">
              @for (m of ragModes; track m) {
                <button
                  type="button"
                  [title]="modeDesc(m)"
                  class="px-2 py-2 rounded text-xs font-semibold ring-1 transition"
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
            <p class="text-[10px] text-gray-500 mt-2">{{ currentModeDesc() }}</p>
          </div>

          <div>
            <div class="flex justify-between items-baseline">
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">{{ i18n.t('settings.retrieval.topk') }}</label>
              <span class="font-mono text-xs text-cyan-300">{{ draft().ragTopK }}</span>
            </div>
            <input
              type="range"
              min="1"
              max="50"
              step="1"
              class="w-full mt-1.5 accent-cyan-500"
              [ngModel]="draft().ragTopK"
              (ngModelChange)="patch({ ragTopK: +$event })"
              name="topk"
            />
            <p class="text-[10px] text-gray-500 mt-1">{{ i18n.t('settings.retrieval.topk.hint') }}</p>
          </div>

          <div>
            <div class="flex justify-between items-baseline">
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">{{ i18n.t('settings.retrieval.similarity') }}</label>
              <span class="font-mono text-xs text-cyan-300">{{ fmt(draft().ragSimilarityThreshold, 2) }}</span>
            </div>
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              class="w-full mt-1.5 accent-cyan-500"
              [ngModel]="draft().ragSimilarityThreshold"
              (ngModelChange)="patch({ ragSimilarityThreshold: +$event })"
              name="sim"
            />
            <p class="text-[10px] text-gray-500 mt-1">{{ i18n.t('settings.retrieval.similarity.hint') }}</p>
          </div>

          <div class="flex items-center justify-between py-2 border-t border-white/5 pt-3">
            <div>
              <div class="text-sm text-white font-medium">{{ i18n.t('settings.retrieval.hybrid') }}</div>
              <div class="text-[11px] text-gray-500">{{ i18n.t('settings.retrieval.hybrid.hint') }}</div>
            </div>
            <button
              type="button"
              class="relative inline-flex h-5 w-9 items-center rounded-full transition"
              [class.bg-cyan-500]="draft().ragUseHybridSearch"
              [class.bg-white\\/10]="!draft().ragUseHybridSearch"
              (click)="patch({ ragUseHybridSearch: !draft().ragUseHybridSearch })"
            >
              <span
                class="inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform"
                [style.transform]="draft().ragUseHybridSearch ? 'translateX(18px)' : 'translateX(3px)'"
              ></span>
            </button>
          </div>

          @if (draft().ragUseHybridSearch) {
            <div class="grid grid-cols-2 gap-3 pt-1">
              <div>
                <div class="flex justify-between items-baseline">
                  <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">{{ i18n.t('settings.retrieval.weight.vector') }}</label>
                  <span class="font-mono text-xs text-cyan-300">{{ fmt(draft().ragVectorWeight, 2) }}</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  class="w-full mt-1 accent-cyan-500"
                  [ngModel]="draft().ragVectorWeight"
                  (ngModelChange)="patch({ ragVectorWeight: +$event })"
                  name="vecw"
                />
              </div>
              <div>
                <div class="flex justify-between items-baseline">
                  <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">{{ i18n.t('settings.retrieval.weight.sparse') }}</label>
                  <span class="font-mono text-xs text-cyan-300">{{ fmt(draft().ragBM25Weight, 2) }}</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  class="w-full mt-1 accent-cyan-500"
                  [ngModel]="draft().ragBM25Weight"
                  (ngModelChange)="patch({ ragBM25Weight: +$event })"
                  name="bm25w"
                />
              </div>
            </div>
          }
        </div>
      </section>

      <!-- Chunking -->
      <section class="ck-surface rounded-md p-5">
        <div class="flex items-center gap-2 mb-4">
          <app-icon name="boxes" [size]="16" class="text-cyan-400" />
          <h3 class="text-sm font-semibold text-white">{{ i18n.t('settings.chunking.title') }}</h3>
        </div>
        <div class="space-y-4">
          <div>
            <div class="flex justify-between items-baseline">
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">{{ i18n.t('settings.chunking.size') }}</label>
              <span class="font-mono text-xs text-cyan-300">{{ draft().ragChunkSize }}</span>
            </div>
            <input
              type="range"
              min="200"
              max="4000"
              step="50"
              class="w-full mt-1.5 accent-cyan-500"
              [ngModel]="draft().ragChunkSize"
              (ngModelChange)="patch({ ragChunkSize: +$event })"
              name="cs"
            />
          </div>
          <div>
            <div class="flex justify-between items-baseline">
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">{{ i18n.t('settings.chunking.overlap') }}</label>
              <span class="font-mono text-xs text-cyan-300">{{ draft().ragChunkOverlap }}</span>
            </div>
            <input
              type="range"
              min="0"
              max="1000"
              step="25"
              class="w-full mt-1.5 accent-cyan-500"
              [ngModel]="draft().ragChunkOverlap"
              (ngModelChange)="patch({ ragChunkOverlap: +$event })"
              name="co"
            />
          </div>
        </div>
      </section>

      <!-- UX toggles -->
      <section class="ck-surface rounded-md p-5">
        <div class="flex items-center gap-2 mb-4">
          <app-icon name="eye" [size]="16" class="text-cyan-400" />
          <h3 class="text-sm font-semibold text-white">{{ i18n.t('settings.experience.title') }}</h3>
        </div>
        <div class="space-y-3">
          @for (t of toggles; track t.key) {
            <div class="flex items-center justify-between py-1.5">
              <div>
                <div class="text-sm text-white font-medium">{{ i18n.t(t.labelKey) }}</div>
                <div class="text-[11px] text-gray-500">{{ i18n.t(t.descKey) }}</div>
              </div>
              <button
                type="button"
                class="relative inline-flex h-5 w-9 items-center rounded-full transition"
                [class.bg-cyan-500]="!!draft()[t.key]"
                [class.bg-white\\/10]="!draft()[t.key]"
                (click)="patchKey(t.key, !draft()[t.key])"
              >
                <span
                  class="inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform"
                  [style.transform]="draft()[t.key] ? 'translateX(18px)' : 'translateX(3px)'"
                ></span>
              </button>
            </div>
          }
        </div>
      </section>
    </div>
  `,
  styles: [`
    .settings-select {
      appearance: none;
      min-height: 2.25rem;
      border-radius: 0.375rem;
      border: 1px solid rgba(255, 255, 255, 0.1);
      background-color: rgba(2, 6, 23, 0.7);
      background-image:
        linear-gradient(45deg, transparent 50%, rgba(148, 163, 184, 0.9) 50%),
        linear-gradient(135deg, rgba(148, 163, 184, 0.9) 50%, transparent 50%);
      background-position:
        calc(100% - 15px) 50%,
        calc(100% - 10px) 50%;
      background-size: 5px 5px, 5px 5px;
      background-repeat: no-repeat;
      color: #e5e7eb;
      font-size: 0.875rem;
      line-height: 1.25rem;
      padding: 0.5rem 2rem 0.5rem 0.75rem;
    }

    .settings-select:focus {
      outline: none;
      border-color: rgba(103, 232, 249, 0.42);
      box-shadow: 0 0 0 1px rgba(103, 232, 249, 0.24);
    }
  `],
})
export class RagSettingsComponent implements OnInit {
  private readonly settings = inject(SettingsService);
  private readonly toast = inject(ToastrService);
  private readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);

  readonly providers = PROVIDERS;
  readonly ragModes = RAG_MODES;
  // Dict keys resolved with t() in the template, so labels follow language flips.
  readonly toggles: { key: keyof AppSettings; labelKey: string; descKey: string }[] = [
    { key: 'enableStreaming', labelKey: 'settings.experience.streaming', descKey: 'settings.experience.streaming.desc' },
    { key: 'showReasoningTraces', labelKey: 'settings.experience.reasoning', descKey: 'settings.experience.reasoning.desc' },
    { key: 'showSources', labelKey: 'settings.experience.sources', descKey: 'settings.experience.sources.desc' },
    { key: 'autoExpandReasoning', labelKey: 'settings.experience.expand', descKey: 'settings.experience.expand.desc' },
  ];

  draft = signal<AppSettings>({ ...this.settings.settings() });
  saving = signal(false);
  readonly isDemoMode = computed(() => this.workspace.isDemoSafeMode());

  readonly dirty = computed(() => {
    return JSON.stringify(this.draft()) !== JSON.stringify(this.settings.settings());
  });

  readonly availableModels = computed(() => {
    const p = this.providers.find((pr) => pr.value === this.draft().defaultProvider);
    return p?.models ?? [];
  });

  readonly currentModeDesc = computed(() => this.modeDesc(this.draft().ragPipelineMode ?? 'auto'));

  /** `settings.mode.<value>` with a raw-value fallback for unknown API modes. */
  modeLabel(mode: string): string {
    const key = 'settings.mode.' + mode;
    const label = this.i18n.t(key);
    return label === key ? mode : label;
  }

  modeDesc(mode: string): string {
    const key = 'settings.mode.' + mode + '.desc';
    const label = this.i18n.t(key);
    return label === key ? '' : label;
  }

  /** `settings.provider.<value>` with the seeded label as fallback. */
  providerLabel(p: ProviderOption): string {
    const key = 'settings.provider.' + p.value;
    const label = this.i18n.t(key);
    return label === key ? p.label : label;
  }

  ngOnInit(): void {
    this.settings.refresh();
    // Pick up refreshed values after a brief tick so they don't overwrite a fresh draft.
    queueMicrotask(() => this.draft.set({ ...this.settings.settings() }));
  }

  setProvider(value: string): void {
    const providerModels = this.providers.find((p) => p.value === value)?.models ?? [];
    const current = this.draft().defaultModel;
    const nextModel = providerModels.includes(current ?? '') ? current : providerModels[0];
    this.draft.set({ ...this.draft(), defaultProvider: value, defaultModel: nextModel });
  }

  patch(p: Partial<AppSettings>): void {
    this.draft.set({ ...this.draft(), ...p });
  }

  patchKey(key: keyof AppSettings, value: unknown): void {
    this.draft.set({ ...this.draft(), [key]: value } as AppSettings);
  }

  resetDraft(): void {
    this.draft.set({ ...this.settings.settings() });
  }

  save(): void {
    this.saving.set(true);
    const patch = this.draft();
    this.settings.update(patch);
    queueMicrotask(() => {
      this.saving.set(false);
      this.toast.success(this.i18n.t('settings.toast.saved'), this.i18n.t('settings.toast.title'));
    });
  }

  fmt(v: unknown, digits = 2): string {
    const n = typeof v === 'number' ? v : Number(v);
    return Number.isFinite(n) ? n.toFixed(digits) : '—';
  }
}
