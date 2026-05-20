import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { forkJoin, map } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { WorkspaceDetail, WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';

type RagMode = 'auto' | 'naive' | 'hybrid' | 'hah' | 'chah';
type SessionPromptMode = 'any' | 'replace' | 'combine';

interface KnowledgeScopeApi {
  key: string;
  label?: string | null;
  description?: string | null;
  collection_slugs: string[];
  default_mode?: RagMode | null;
  top_k?: number | null;
  is_default?: boolean;
}

interface KnowledgeScopeDraft {
  key: string;
  label: string;
  description: string;
  collection_slugs_text: string;
  default_mode: RagMode;
  top_k: number | null;
  is_default: boolean;
}

interface PromptCardDraft {
  icon: string;
  label: string;
  prompt: string;
  scope_key: string;
  context_mode: SessionPromptMode;
}

interface ChatSettingsDraft {
  title: string;
  subtitle: string;
  placeholder: string;
  prompt_pack: PromptCardDraft[];
}

@Component({
  selector: 'app-chat-knowledge-settings',
  standalone: true,
  imports: [FormsModule, IconComponent, SectionHeaderComponent],
  template: `
    <app-section-header
      breadcrumb="Workspace · Defaults"
      title="Chat & Knowledge"
      icon="database"
      subtitle="Configure workspace Knowledge scopes, chat defaults and assistant metadata used by Quick ask."
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 text-gray-200 ring-1 ring-white/10 transition"
        (click)="load()"
      >
        <app-icon name="refresh-cw" [size]="14" /> Refresh
      </button>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-semibold bg-brand-500 hover:bg-brand-400 text-white disabled:opacity-50 transition"
        [disabled]="saving() || !canEdit()"
        (click)="saveAll()"
      >
        <app-icon name="save" [size]="14" /> {{ saving() ? 'Saving...' : 'Save defaults' }}
      </button>
    </app-section-header>

    @if (error(); as message) {
      <div class="mb-4 rounded-md border border-red-400/25 bg-red-500/10 px-4 py-3 text-sm text-red-100">
        {{ message }}
      </div>
    }

    <div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div class="space-y-5">
        <section class="t-card t-elevated rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5 flex items-start justify-between gap-3">
            <div>
              <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Knowledge routing</p>
              <h3 class="text-base font-semibold text-white mt-1">Knowledge scopes</h3>
              <p class="text-sm text-gray-400 mt-1 max-w-2xl">
                A scope gives the chat a human label and maps it to one or more indexed collections.
                The default scope is what users see as <span class="text-gray-200">Workspace default</span>.
              </p>
            </div>
            <button
              type="button"
              class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-sm font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
              [disabled]="!canEdit()"
              (click)="addScope()"
            >
              <app-icon name="plus" [size]="14" /> Add scope
            </button>
          </div>

          <div class="divide-y divide-white/5">
            @for (scope of scopes(); track scope.key; let i = $index) {
              <article class="p-5">
                <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
                  <label class="inline-flex items-center gap-2 text-sm text-gray-200">
                    <input
                      type="radio"
                      name="default_scope"
                      class="accent-brand-400"
                      [checked]="scope.is_default"
                      [disabled]="!canEdit()"
                      (change)="setDefaultScope(i)"
                    />
                    Workspace default
                  </label>
                  <button
                    type="button"
                    class="inline-flex items-center gap-1.5 rounded bg-red-500/10 px-3 py-1.5 text-xs font-medium text-red-200 ring-1 ring-red-400/20 disabled:opacity-40"
                    [disabled]="!canEdit() || scopes().length <= 1"
                    (click)="removeScope(i)"
                  >
                    <app-icon name="trash-2" [size]="13" /> Remove
                  </button>
                </div>

                <div class="grid gap-4 lg:grid-cols-[1fr_1fr_150px_110px]">
                  <label class="block">
                    <span class="field-label">Key</span>
                    <input class="ag-field font-mono" [(ngModel)]="scope.key" [disabled]="!canEdit()" />
                  </label>
                  <label class="block">
                    <span class="field-label">Visible label</span>
                    <input class="ag-field" [(ngModel)]="scope.label" [disabled]="!canEdit()" />
                  </label>
                  <label class="block">
                    <span class="field-label">Retrieval mode</span>
                    <span class="ag-select-wrap">
                      <select class="ag-select" [(ngModel)]="scope.default_mode" [disabled]="!canEdit()">
                        @for (mode of ragModes; track mode) {
                          <option [ngValue]="mode">{{ mode }}</option>
                        }
                      </select>
                      <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
                    </span>
                  </label>
                  <label class="block">
                    <span class="field-label">Top-K</span>
                    <input class="ag-field" type="number" min="1" max="50" [(ngModel)]="scope.top_k" [disabled]="!canEdit()" />
                  </label>
                </div>

                <label class="block mt-4">
                  <span class="field-label">Description</span>
                  <input class="ag-field" [(ngModel)]="scope.description" [disabled]="!canEdit()" />
                </label>

                <label class="block mt-4">
                  <span class="field-label">Collection slugs</span>
                  <input
                    class="ag-field font-mono"
                    [(ngModel)]="scope.collection_slugs_text"
                    [disabled]="!canEdit()"
                    placeholder="collection-a, collection-b"
                  />
                </label>
              </article>
            }
          </div>
        </section>

        <section class="t-card t-elevated rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5">
            <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Chat surface</p>
            <h3 class="text-base font-semibold text-white mt-1">Chat defaults</h3>
            <p class="text-sm text-gray-400 mt-1 max-w-2xl">
              These values drive the empty state, input placeholder and suggested prompts in Quick ask.
            </p>
          </div>

          <div class="p-5 space-y-4">
            <div class="grid gap-4 lg:grid-cols-2">
              <label class="block">
                <span class="field-label">Empty state title</span>
                <input class="ag-field" [(ngModel)]="chatDraft.title" [disabled]="!canEdit()" placeholder="Ask Agentium" />
              </label>
              <label class="block">
                <span class="field-label">Input placeholder</span>
                <input class="ag-field" [(ngModel)]="chatDraft.placeholder" [disabled]="!canEdit()" placeholder="Ask a sourced question..." />
              </label>
            </div>
            <label class="block">
              <span class="field-label">Subtitle</span>
              <input class="ag-field" [(ngModel)]="chatDraft.subtitle" [disabled]="!canEdit()" placeholder="Ask questions grounded in workspace Knowledge." />
            </label>

            <div class="rounded-md border border-white/10 bg-black/10">
              <div class="px-4 py-3 border-b border-white/5 flex items-center justify-between gap-3">
                <div>
                  <h4 class="text-sm font-semibold text-white">Suggested prompts</h4>
                  <p class="text-xs text-gray-500 mt-0.5">Optional. Leave empty to use Agentium generated prompts based on the active source.</p>
                </div>
                <button
                  type="button"
                  class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-1.5 text-xs text-gray-200 ring-1 ring-white/10"
                  [disabled]="!canEdit()"
                  (click)="addPrompt()"
                >
                  <app-icon name="plus" [size]="13" /> Add prompt
                </button>
              </div>

              <div class="divide-y divide-white/5">
                @if (chatDraft.prompt_pack.length === 0) {
                  <p class="px-4 py-5 text-sm text-gray-500">No custom prompts. The chat will use contextual Agentium suggestions.</p>
                }
                @for (prompt of chatDraft.prompt_pack; track prompt; let i = $index) {
                  <div class="p-4 grid gap-3 lg:grid-cols-[120px_1fr_180px_140px_40px] lg:items-end">
                    <label class="block">
                      <span class="field-label">Icon</span>
                      <input class="ag-field" [(ngModel)]="prompt.icon" [disabled]="!canEdit()" />
                    </label>
                    <label class="block">
                      <span class="field-label">Prompt</span>
                      <input class="ag-field" [(ngModel)]="prompt.prompt" [disabled]="!canEdit()" />
                    </label>
                    <label class="block">
                      <span class="field-label">Label</span>
                      <input class="ag-field" [(ngModel)]="prompt.label" [disabled]="!canEdit()" />
                    </label>
                    <label class="block">
                      <span class="field-label">Scope</span>
                      <span class="ag-select-wrap">
                        <select class="ag-select" [(ngModel)]="prompt.scope_key" [disabled]="!canEdit()">
                          <option value="">Any</option>
                          @for (scope of scopes(); track scope.key) {
                            <option [ngValue]="scope.key">{{ scope.label || scope.key }}</option>
                          }
                        </select>
                        <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
                      </span>
                    </label>
                    <button
                      type="button"
                      class="h-10 rounded bg-red-500/10 text-red-200 ring-1 ring-red-400/20 disabled:opacity-40"
                      [disabled]="!canEdit()"
                      (click)="removePrompt(i)"
                      title="Remove prompt"
                    >
                      <app-icon name="trash-2" [size]="14" class="inline" />
                    </button>
                  </div>
                }
              </div>
            </div>
          </div>
        </section>
      </div>

      <aside class="space-y-5">
        <section class="t-card t-elevated rounded-md p-5">
          <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Available collections</p>
          <h3 class="text-sm font-semibold text-white mt-1">Workspace Knowledge</h3>
          <p class="text-xs text-gray-500 mt-2">
            Copy slugs into a Knowledge scope. A scope may combine several collections.
          </p>
          <div class="mt-4 max-h-72 overflow-y-auto space-y-2 pr-1">
            @for (collection of collections(); track collection) {
              <button
                type="button"
                class="w-full text-left rounded border border-white/10 bg-white/[0.03] px-3 py-2 text-xs font-mono text-gray-300 hover:bg-white/[0.06]"
                (click)="copyCollection(collection)"
              >
                {{ collection }}
              </button>
            } @empty {
              <p class="text-sm text-gray-500">No indexed collection reported yet.</p>
            }
          </div>
        </section>

        <section class="t-card t-elevated rounded-md p-5">
          <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Assistant profile</p>
          <h3 class="text-sm font-semibold text-white mt-1">Default assistant</h3>
          <label class="block mt-4">
            <span class="field-label">assistant_profile_default</span>
            <span class="ag-select-wrap">
              <select class="ag-select" [(ngModel)]="assistantProfileDefault" [disabled]="!canEdit()">
                <option value="">None</option>
                @for (profile of assistantProfileOptions(); track profile) {
                  <option [ngValue]="profile">{{ profile }}</option>
                }
              </select>
              <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
            </span>
          </label>
          <label class="block mt-4">
            <span class="field-label">assistant_profiles JSON</span>
            <textarea
              class="ag-field min-h-56 font-mono text-xs leading-relaxed"
              [(ngModel)]="assistantProfilesJson"
              [disabled]="!canEdit()"
              spellcheck="false"
            ></textarea>
          </label>
          <p class="mt-3 text-xs text-gray-500 leading-relaxed">
            This remains an advanced field until assistant profiles get a dedicated editor.
          </p>
        </section>
      </aside>
    </div>
  `,
  styles: [`
    .field-label {
      display: block;
      margin-bottom: 0.375rem;
      font-size: 10px;
      line-height: 1;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: rgb(107 114 128);
      font-weight: 700;
    }
    .ag-field {
      width: 100%;
      border-radius: 6px;
      border: 1px solid rgba(255,255,255,0.10);
      background: rgba(0,0,0,0.28);
      color: rgb(243 244 246);
      padding: 0.625rem 0.75rem;
      font-size: 0.875rem;
      outline: none;
      transition: border-color 120ms, box-shadow 120ms, background 120ms;
    }
    .ag-field:focus {
      border-color: rgba(56,189,248,0.65);
      box-shadow: 0 0 0 2px rgba(56,189,248,0.18);
      background: rgba(0,0,0,0.36);
    }
    .ag-field:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
    .ag-select-wrap {
      position: relative;
      display: block;
    }
    .ag-select {
      width: 100%;
      height: 40px;
      appearance: none;
      -webkit-appearance: none;
      border-radius: 6px;
      border: 1px solid rgba(255,255,255,0.10);
      background: rgba(0,0,0,0.30);
      color: rgb(243 244 246);
      padding: 0 2.25rem 0 0.75rem;
      font-size: 0.875rem;
      outline: none;
      color-scheme: dark;
    }
    .ag-select:focus {
      border-color: rgba(56,189,248,0.65);
      box-shadow: 0 0 0 2px rgba(56,189,248,0.18);
    }
    .ag-select-chevron {
      position: absolute;
      right: 0.75rem;
      top: 50%;
      transform: translateY(-50%);
      color: rgb(156 163 175);
      pointer-events: none;
    }
  `],
})
export class ChatKnowledgeSettingsComponent {
  private readonly api = inject(ApiService);
  protected readonly workspace = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);
  private readonly toastr = inject(ToastrService);

  private readonly routeSlug = toSignal(
    this.route.parent!.paramMap.pipe(map((p) => p.get('slug') ?? null)),
    { initialValue: null as string | null },
  );

  readonly detail = signal<WorkspaceDetail | null>(null);
  readonly collections = signal<string[]>([]);
  readonly scopes = signal<KnowledgeScopeDraft[]>([]);
  readonly saving = signal(false);
  readonly error = signal<string | null>(null);

  readonly ragModes: RagMode[] = ['auto', 'naive', 'hybrid', 'hah', 'chah'];
  assistantProfileDefault = '';
  assistantProfilesJson = '[]';
  chatDraft: ChatSettingsDraft = {
    title: '',
    subtitle: '',
    placeholder: '',
    prompt_pack: [],
  };

  readonly canEdit = computed(() => {
    const role = this.detail()?.role;
    const template = this.detail()?.role_template;
    return role === 'owner' || role === 'admin' || template === 'workspace_owner' || template === 'workspace_admin';
  });

  readonly assistantProfileOptions = computed(() => {
    try {
      const parsed = JSON.parse(this.assistantProfilesJson || '[]');
      if (!Array.isArray(parsed)) return [];
      return parsed
        .map((profile) => typeof profile?.key === 'string' ? profile.key : '')
        .filter(Boolean);
    } catch {
      return [];
    }
  });

  constructor() {
    effect(() => {
      const slug = this.routeSlug();
      if (slug) this.load();
    });
  }

  load(): void {
    const slug = this.routeSlug();
    if (!slug) return;
    this.error.set(null);
    forkJoin({
      workspace: this.workspace.getWorkspace(slug),
      scopes: this.api.get<{ scopes: KnowledgeScopeApi[] }>('/knowledge/scopes'),
      collections: this.api.get<{ collections: string[] }>('/documents/collections'),
    }).subscribe({
      next: ({ workspace, scopes, collections }) => {
        this.detail.set(workspace);
        this.hydrateSettings(workspace);
        this.scopes.set((scopes.scopes || []).map((scope) => this.scopeToDraft(scope)));
        if (this.scopes().length === 0) this.addScope();
        this.collections.set([...(collections.collections || [])].sort((a, b) => a.localeCompare(b)));
      },
      error: () => this.error.set('Unable to load workspace chat and Knowledge settings.'),
    });
  }

  addScope(): void {
    const next = [...this.scopes()];
    next.push({
      key: `scope_${next.length + 1}`,
      label: `Scope ${next.length + 1}`,
      description: '',
      collection_slugs_text: this.collections()[0] || '',
      default_mode: 'chah',
      top_k: 5,
      is_default: next.length === 0,
    });
    this.scopes.set(next);
  }

  removeScope(index: number): void {
    const next = this.scopes().filter((_, i) => i !== index);
    if (next.length && !next.some((scope) => scope.is_default)) next[0].is_default = true;
    this.scopes.set(next);
  }

  setDefaultScope(index: number): void {
    this.scopes.set(this.scopes().map((scope, i) => ({ ...scope, is_default: i === index })));
  }

  addPrompt(): void {
    this.chatDraft.prompt_pack = [
      ...this.chatDraft.prompt_pack,
      { icon: 'file-search', label: 'Sourced answer', prompt: 'Answer with citations from the selected Knowledge source.', scope_key: '', context_mode: 'any' },
    ];
  }

  removePrompt(index: number): void {
    this.chatDraft.prompt_pack = this.chatDraft.prompt_pack.filter((_, i) => i !== index);
  }

  copyCollection(collection: string): void {
    void navigator.clipboard?.writeText(collection);
    this.toastr.info(collection, 'Collection slug copied');
  }

  saveAll(): void {
    const detail = this.detail();
    if (!detail) return;
    const scopePayload = this.toScopePayload();
    if (!scopePayload) return;

    let assistantProfiles: unknown;
    try {
      assistantProfiles = JSON.parse(this.assistantProfilesJson || '[]');
      if (!Array.isArray(assistantProfiles)) throw new Error('assistant_profiles must be an array');
    } catch (err) {
      this.error.set(err instanceof Error ? err.message : 'Invalid assistant_profiles JSON.');
      return;
    }

    const settings = { ...(detail.settings || {}) };
    settings['knowledge_scopes'] = scopePayload;
    settings['chat'] = this.cleanChatSettings();
    settings['assistant_profile_default'] = this.assistantProfileDefault || null;
    settings['assistant_profiles'] = assistantProfiles;

    this.saving.set(true);
    this.error.set(null);
    this.api.patch('/knowledge/scopes', { scopes: scopePayload }).subscribe({
      next: () => {
        this.workspace.updateWorkspaceSettings(detail.slug, settings).subscribe({
          next: (workspace) => {
            this.saving.set(false);
            this.detail.set(workspace);
            this.workspace.refreshCurrentWorkspace().subscribe();
            this.toastr.success('Chat and Knowledge defaults saved', 'Workspace');
            this.load();
          },
          error: (err) => {
            this.saving.set(false);
            this.error.set(err?.error?.detail || 'Knowledge scopes saved, but chat defaults could not be saved.');
          },
        });
      },
      error: (err) => {
        this.saving.set(false);
        this.error.set(err?.error?.detail || 'Unable to save Knowledge scopes.');
      },
    });
  }

  private hydrateSettings(workspace: WorkspaceDetail): void {
    const settings = workspace.settings || {};
    const chat = this.asRecord(settings['chat']);
    this.chatDraft = {
      title: this.str(chat['title']),
      subtitle: this.str(chat['subtitle']),
      placeholder: this.str(chat['placeholder']),
      prompt_pack: this.promptPackDraft(chat['prompt_pack']),
    };
    this.assistantProfileDefault = this.str(settings['assistant_profile_default']);
    this.assistantProfilesJson = JSON.stringify(Array.isArray(settings['assistant_profiles']) ? settings['assistant_profiles'] : [], null, 2);
  }

  private scopeToDraft(scope: KnowledgeScopeApi): KnowledgeScopeDraft {
    return {
      key: scope.key,
      label: scope.label || scope.key,
      description: scope.description || '',
      collection_slugs_text: (scope.collection_slugs || []).join(', '),
      default_mode: scope.default_mode || 'auto',
      top_k: scope.top_k || null,
      is_default: !!scope.is_default,
    };
  }

  private toScopePayload(): KnowledgeScopeApi[] | null {
    const payload = this.scopes().map((scope) => {
      const collections = scope.collection_slugs_text
        .split(',')
        .map((slug) => slug.trim())
        .filter(Boolean);
      return {
        key: scope.key.trim(),
        label: scope.label.trim(),
        description: scope.description.trim(),
        collection_slugs: collections,
        default_mode: scope.default_mode || 'auto',
        top_k: scope.top_k ? Number(scope.top_k) : null,
        is_default: !!scope.is_default,
      };
    });

    if (payload.some((scope) => !scope.key || scope.collection_slugs.length === 0)) {
      this.error.set('Each Knowledge scope needs a key and at least one collection slug.');
      return null;
    }
    if (new Set(payload.map((scope) => scope.key)).size !== payload.length) {
      this.error.set('Knowledge scope keys must be unique.');
      return null;
    }
    if (!payload.some((scope) => scope.is_default)) payload[0].is_default = true;
    return payload;
  }

  private cleanChatSettings(): Record<string, unknown> {
    const chat: Record<string, unknown> = {};
    if (this.chatDraft.title.trim()) chat['title'] = this.chatDraft.title.trim();
    if (this.chatDraft.subtitle.trim()) chat['subtitle'] = this.chatDraft.subtitle.trim();
    if (this.chatDraft.placeholder.trim()) chat['placeholder'] = this.chatDraft.placeholder.trim();
    const prompts = this.chatDraft.prompt_pack
      .map((prompt) => ({
        icon: prompt.icon.trim() || 'sparkles',
        label: prompt.label.trim(),
        prompt: prompt.prompt.trim(),
        scope_key: prompt.scope_key || undefined,
        context_mode: prompt.context_mode && prompt.context_mode !== 'any' ? prompt.context_mode : undefined,
      }))
      .filter((prompt) => prompt.label && prompt.prompt);
    if (prompts.length) chat['prompt_pack'] = prompts;
    return chat;
  }

  private promptPackDraft(value: unknown): PromptCardDraft[] {
    if (!Array.isArray(value)) return [];
    return value.flatMap((item) => {
      const record = this.asRecord(item);
      const label = this.str(record['label']);
      const prompt = this.str(record['prompt']);
      if (!label || !prompt) return [];
      return [{
        icon: this.str(record['icon']) || 'sparkles',
        label,
        prompt,
        scope_key: this.str(record['scope_key'] || record['knowledge_scope'] || record['source_key']),
        context_mode: record['context_mode'] === 'replace' || record['context_mode'] === 'combine'
          ? record['context_mode'] as SessionPromptMode
          : 'any',
      }];
    });
  }

  private asRecord(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
  }

  private str(value: unknown): string {
    return typeof value === 'string' ? value : '';
  }
}
