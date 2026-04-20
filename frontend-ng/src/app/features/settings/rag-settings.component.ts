import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ToastrService } from 'ngx-toastr';
import { SettingsService, AppSettings } from '@app/core/settings.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';

interface ProviderOption {
  value: string;
  label: string;
  models: string[];
}

const PROVIDERS: ProviderOption[] = [
  { value: 'openai', label: 'OpenAI', models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo'] },
  { value: 'anthropic', label: 'Anthropic', models: ['claude-3-5-sonnet', 'claude-3-opus', 'claude-3-haiku'] },
  { value: 'ollama', label: 'Ollama (self-hosted)', models: ['deepseek-r1:14b', 'llama3.1:8b', 'qwen2.5:14b', 'mixtral'] },
];

const RAG_MODES = [
  { value: 'auto', label: 'Auto', desc: 'Heuristic routing between modes' },
  { value: 'naive', label: 'Naive', desc: 'Vector similarity only' },
  { value: 'hybrid', label: 'Hybrid', desc: 'Vector + BM25 fusion' },
  { value: 'hah', label: 'HAH', desc: 'Hierarchical agentic heuristic' },
  { value: 'chah', label: 'CHAH', desc: 'Contextual hierarchical agentic heuristic' },
] as const;

@Component({
  selector: 'app-rag-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, IconComponent, SectionHeaderComponent],
  template: `
    <app-section-header
      breadcrumb="Configure"
      title="Settings"
      icon="sliders-horizontal"
      subtitle="Generation, retrieval and pipeline tuning shared across playground sessions."
    >
      <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mr-2">
        {{ dirty() ? 'Unsaved changes' : 'Synced' }}
      </span>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        (click)="resetDraft()"
        [disabled]="!dirty()"
      >
        <app-icon name="rotate-ccw" [size]="14" /> Reset
      </button>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white transition disabled:opacity-50"
        (click)="save()"
        [disabled]="!dirty() || saving()"
      >
        <app-icon [name]="saving() ? 'loader-2' : 'save'" [size]="14" [class.animate-spin]="saving()" />
        {{ saving() ? 'Saving…' : 'Save changes' }}
      </button>
    </app-section-header>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <!-- Model / generation -->
      <section class="t-card t-elevated rounded-md p-5">
        <div class="flex items-center gap-2 mb-4">
          <app-icon name="cpu" [size]="16" class="text-brand-400" />
          <h3 class="text-sm font-semibold text-white">Model & generation</h3>
        </div>

        <div class="space-y-4">
          <div>
            <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">Provider</label>
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
                  (click)="setProvider(p.value)"
                >
                  {{ p.label }}
                </button>
              }
            </div>
          </div>

          <div>
            <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">Model</label>
            <select
              class="w-full mt-1.5 bg-white/5 ring-1 ring-white/10 rounded px-3 py-2 text-sm text-white focus:outline-none focus:ring-brand-400"
              [ngModel]="draft().defaultModel"
              (ngModelChange)="patch({ defaultModel: $event })"
              name="model"
            >
              @for (m of availableModels(); track m) {
                <option [value]="m">{{ m }}</option>
              }
            </select>
          </div>

          <div>
            <div class="flex justify-between items-baseline">
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">Temperature</label>
              <span class="font-mono text-xs text-brand-300">{{ fmt(draft().temperature, 2) }}</span>
            </div>
            <input
              type="range"
              min="0"
              max="2"
              step="0.05"
              class="w-full mt-1.5 accent-brand-500"
              [ngModel]="draft().temperature"
              (ngModelChange)="patch({ temperature: +$event })"
              name="temp"
            />
            <p class="text-[10px] text-gray-500 mt-1">0 = deterministic · 1 = balanced · 2 = creative</p>
          </div>

          <div>
            <div class="flex justify-between items-baseline">
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">Max tokens</label>
              <span class="font-mono text-xs text-brand-300">{{ draft().maxTokens }}</span>
            </div>
            <input
              type="range"
              min="256"
              max="8000"
              step="128"
              class="w-full mt-1.5 accent-brand-500"
              [ngModel]="draft().maxTokens"
              (ngModelChange)="patch({ maxTokens: +$event })"
              name="maxTokens"
            />
          </div>
        </div>
      </section>

      <!-- RAG pipeline -->
      <section class="t-card t-elevated rounded-md p-5">
        <div class="flex items-center gap-2 mb-4">
          <app-icon name="database" [size]="16" class="text-brand-400" />
          <h3 class="text-sm font-semibold text-white">Retrieval pipeline</h3>
        </div>

        <div class="space-y-4">
          <div>
            <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">Pipeline mode</label>
            <div class="grid grid-cols-5 gap-1.5 mt-1.5">
              @for (m of ragModes; track m.value) {
                <button
                  type="button"
                  [title]="m.desc"
                  class="px-2 py-2 rounded text-xs font-semibold ring-1 transition"
                  [class.bg-brand-500\\/15]="draft().ragPipelineMode === m.value"
                  [class.text-brand-200]="draft().ragPipelineMode === m.value"
                  [class.ring-brand-500\\/40]="draft().ragPipelineMode === m.value"
                  [class.bg-white\\/5]="draft().ragPipelineMode !== m.value"
                  [class.text-gray-300]="draft().ragPipelineMode !== m.value"
                  [class.ring-white\\/10]="draft().ragPipelineMode !== m.value"
                  (click)="patch({ ragPipelineMode: m.value })"
                >
                  {{ m.label }}
                </button>
              }
            </div>
            <p class="text-[10px] text-gray-500 mt-2">{{ currentModeDesc() }}</p>
          </div>

          <div>
            <div class="flex justify-between items-baseline">
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">Top K</label>
              <span class="font-mono text-xs text-brand-300">{{ draft().ragTopK }}</span>
            </div>
            <input
              type="range"
              min="1"
              max="50"
              step="1"
              class="w-full mt-1.5 accent-brand-500"
              [ngModel]="draft().ragTopK"
              (ngModelChange)="patch({ ragTopK: +$event })"
              name="topk"
            />
            <p class="text-[10px] text-gray-500 mt-1">Number of chunks retrieved per query.</p>
          </div>

          <div>
            <div class="flex justify-between items-baseline">
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">Similarity threshold</label>
              <span class="font-mono text-xs text-brand-300">{{ fmt(draft().ragSimilarityThreshold, 2) }}</span>
            </div>
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              class="w-full mt-1.5 accent-brand-500"
              [ngModel]="draft().ragSimilarityThreshold"
              (ngModelChange)="patch({ ragSimilarityThreshold: +$event })"
              name="sim"
            />
            <p class="text-[10px] text-gray-500 mt-1">Chunks below this score are dropped before synthesis.</p>
          </div>

          <div class="flex items-center justify-between py-2 border-t border-white/5 pt-3">
            <div>
              <div class="text-sm text-white font-medium">Hybrid search</div>
              <div class="text-[11px] text-gray-500">Fuse vector + BM25 scores</div>
            </div>
            <button
              type="button"
              class="relative inline-flex h-5 w-9 items-center rounded-full transition"
              [class.bg-brand-500]="draft().ragUseHybridSearch"
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
                  <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">Vector weight</label>
                  <span class="font-mono text-xs text-brand-300">{{ fmt(draft().ragVectorWeight, 2) }}</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  class="w-full mt-1 accent-brand-500"
                  [ngModel]="draft().ragVectorWeight"
                  (ngModelChange)="patch({ ragVectorWeight: +$event })"
                  name="vecw"
                />
              </div>
              <div>
                <div class="flex justify-between items-baseline">
                  <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">BM25 weight</label>
                  <span class="font-mono text-xs text-brand-300">{{ fmt(draft().ragBM25Weight, 2) }}</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  class="w-full mt-1 accent-brand-500"
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
      <section class="t-card t-elevated rounded-md p-5">
        <div class="flex items-center gap-2 mb-4">
          <app-icon name="boxes" [size]="16" class="text-brand-400" />
          <h3 class="text-sm font-semibold text-white">Chunking</h3>
        </div>
        <div class="space-y-4">
          <div>
            <div class="flex justify-between items-baseline">
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">Chunk size (chars)</label>
              <span class="font-mono text-xs text-brand-300">{{ draft().ragChunkSize }}</span>
            </div>
            <input
              type="range"
              min="200"
              max="4000"
              step="50"
              class="w-full mt-1.5 accent-brand-500"
              [ngModel]="draft().ragChunkSize"
              (ngModelChange)="patch({ ragChunkSize: +$event })"
              name="cs"
            />
          </div>
          <div>
            <div class="flex justify-between items-baseline">
              <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">Chunk overlap (chars)</label>
              <span class="font-mono text-xs text-brand-300">{{ draft().ragChunkOverlap }}</span>
            </div>
            <input
              type="range"
              min="0"
              max="1000"
              step="25"
              class="w-full mt-1.5 accent-brand-500"
              [ngModel]="draft().ragChunkOverlap"
              (ngModelChange)="patch({ ragChunkOverlap: +$event })"
              name="co"
            />
          </div>
        </div>
      </section>

      <!-- UX toggles -->
      <section class="t-card t-elevated rounded-md p-5">
        <div class="flex items-center gap-2 mb-4">
          <app-icon name="eye" [size]="16" class="text-brand-400" />
          <h3 class="text-sm font-semibold text-white">Experience</h3>
        </div>
        <div class="space-y-3">
          @for (t of toggles; track t.key) {
            <div class="flex items-center justify-between py-1.5">
              <div>
                <div class="text-sm text-white font-medium">{{ t.label }}</div>
                <div class="text-[11px] text-gray-500">{{ t.desc }}</div>
              </div>
              <button
                type="button"
                class="relative inline-flex h-5 w-9 items-center rounded-full transition"
                [class.bg-brand-500]="!!draft()[t.key]"
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
})
export class RagSettingsComponent implements OnInit {
  private readonly settings = inject(SettingsService);
  private readonly toast = inject(ToastrService);

  readonly providers = PROVIDERS;
  readonly ragModes = RAG_MODES;
  readonly toggles: { key: keyof AppSettings; label: string; desc: string }[] = [
    { key: 'enableStreaming', label: 'Streaming responses', desc: 'Stream tokens as they arrive' },
    { key: 'showReasoningTraces', label: 'Show reasoning trail', desc: 'Expose orchestrator decision steps' },
    { key: 'showSources', label: 'Show sources', desc: 'Attach citations to responses' },
    { key: 'autoExpandReasoning', label: 'Auto-expand trail', desc: 'Open the reasoning panel by default' },
  ];

  draft = signal<AppSettings>({ ...this.settings.settings() });
  saving = signal(false);

  readonly dirty = computed(() => {
    return JSON.stringify(this.draft()) !== JSON.stringify(this.settings.settings());
  });

  readonly availableModels = computed(() => {
    const p = this.providers.find((pr) => pr.value === this.draft().defaultProvider);
    return p?.models ?? [];
  });

  readonly currentModeDesc = computed(() => {
    const m = this.ragModes.find((r) => r.value === this.draft().ragPipelineMode);
    return m?.desc ?? '';
  });

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
      this.toast.success('Settings saved', 'Preferences');
    });
  }

  fmt(v: unknown, digits = 2): string {
    const n = typeof v === 'number' ? v : Number(v);
    return Number.isFinite(n) ? n.toFixed(digits) : '—';
  }
}
