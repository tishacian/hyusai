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

interface AssistantProfileDraft {
  key: string;
  label?: string;
  subtitle?: string;
  default_knowledge_scope?: string;
  executive_mode?: boolean;
  showcase_mode?: string;
  design_mode?: string;
  tone?: string;
  prompt_pack?: PromptCardDraft[];
  chat?: Record<string, unknown>;
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
              <p class="text-sm text-gray-400 mt-1 max-w-2xl leading-relaxed">
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
                <div class="flex flex-wrap items-center justify-between gap-3 mb-5">
                  <label class="scope-default-toggle">
                    <input
                      type="radio"
                      name="default_scope"
                      [checked]="scope.is_default"
                      [disabled]="!canEdit()"
                      (change)="setDefaultScope(i)"
                    />
                    <span>
                      <span class="block text-sm font-semibold text-gray-100">Workspace default</span>
                      <span class="block text-xs text-gray-500">Used by Quick ask unless the default assistant profile defines another scope.</span>
                    </span>
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

                <div class="grid gap-4 md:grid-cols-[minmax(150px,0.75fr)_minmax(240px,1.25fr)]">
                  <label class="block">
                    <span class="field-label">Key</span>
                    <input class="ag-field font-mono" [(ngModel)]="scope.key" [disabled]="!canEdit()" />
                  </label>
                  <label class="block">
                    <span class="field-label">Visible label</span>
                    <input class="ag-field" [(ngModel)]="scope.label" [disabled]="!canEdit()" />
                  </label>
                </div>

                <div class="grid gap-4 mt-4 md:grid-cols-[minmax(180px,260px)_minmax(120px,160px)]">
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
            <p class="text-sm text-gray-400 mt-1 max-w-2xl leading-relaxed">
              Workspace defaults are the portable baseline. The preview below shows the effective Quick ask surface after
              assistant profile overrides and generated source prompts are applied.
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

            <div class="effective-preview">
              <div class="effective-preview-header">
                <div>
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">Effective Quick ask</p>
                  <h4 class="text-sm font-semibold text-white mt-1">What the chat will show now</h4>
                </div>
                <div class="text-right">
                  <p class="text-[10px] uppercase tracking-[0.16em] text-gray-500">Auto source</p>
                  <p class="text-sm font-semibold text-cyan-100">{{ effectiveScopeLabel() }}</p>
                </div>
              </div>

              @if (activeProfileChatOverrides()) {
                <div class="mx-4 mt-4 rounded border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
                  The default assistant profile contributes chat metadata. This is why the live chat can differ from empty workspace fields.
                </div>
              }

              <div class="p-4">
                <div class="rounded border border-white/10 bg-black/20 p-4">
                  <div class="flex items-start gap-3">
                    <span class="preview-orb">
                      <app-icon name="sparkles" [size]="18" />
                    </span>
                    <div class="min-w-0">
                      <h5 class="text-base font-semibold text-white">{{ effectiveChatTitle() }}</h5>
                      <p class="mt-1 text-sm text-gray-400 leading-relaxed">{{ effectiveChatSubtitle() }}</p>
                      <p class="mt-3 rounded bg-black/25 px-3 py-2 text-xs text-gray-500 ring-1 ring-white/10">
                        Placeholder: <span class="text-gray-300">{{ effectiveChatPlaceholder() }}</span>
                      </p>
                    </div>
                  </div>

                  <div class="mt-4 grid gap-3 md:grid-cols-2">
                    @for (prompt of effectivePromptCards(); track prompt.label + prompt.prompt) {
                      <div class="preview-prompt">
                        <span class="preview-prompt-icon">
                          <app-icon [name]="prompt.icon || 'sparkles'" [size]="14" />
                        </span>
                        <div class="min-w-0">
                          <p class="text-sm font-semibold text-white truncate">{{ prompt.label }}</p>
                          <p class="mt-1 text-xs leading-relaxed text-gray-400 line-clamp-2">{{ prompt.prompt }}</p>
                        </div>
                      </div>
                    }
                  </div>
                </div>

                <button
                  type="button"
                  class="mt-3 inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-xs font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-40"
                  [disabled]="!canEdit()"
                  (click)="copyEffectiveChatToWorkspace()"
                >
                  <app-icon name="copy" [size]="13" /> Copy preview into workspace defaults
                </button>
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
          <p class="mt-2 text-xs text-gray-500 leading-relaxed">
            The default assistant may set the automatic Knowledge source and, when configured, the visible Quick ask surface.
          </p>
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
    .scope-default-toggle {
      display: inline-flex;
      align-items: center;
      gap: 0.75rem;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(255,255,255,0.025);
      padding: 0.625rem 0.75rem;
    }
    .scope-default-toggle input {
      width: 1rem;
      height: 1rem;
      accent-color: rgb(56 189 248);
    }
    .effective-preview {
      overflow: hidden;
      border-radius: 8px;
      border: 1px solid rgba(34,211,238,0.22);
      background:
        radial-gradient(circle at 80% 0%, rgba(34,211,238,0.08), transparent 34%),
        rgba(0,0,0,0.12);
    }
    .effective-preview-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 1rem;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      padding: 1rem;
    }
    .preview-orb {
      display: inline-flex;
      width: 2.5rem;
      height: 2.5rem;
      align-items: center;
      justify-content: center;
      flex: 0 0 auto;
      border-radius: 999px;
      background: linear-gradient(135deg, rgba(14,165,233,0.18), rgba(124,58,237,0.22));
      color: rgb(34 211 238);
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.08);
    }
    .preview-prompt {
      display: flex;
      min-height: 5rem;
      align-items: flex-start;
      gap: 0.75rem;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(255,255,255,0.025);
      padding: 0.875rem;
    }
    .preview-prompt-icon {
      display: inline-flex;
      width: 2rem;
      height: 2rem;
      align-items: center;
      justify-content: center;
      flex: 0 0 auto;
      border-radius: 7px;
      background: rgba(34,211,238,0.10);
      color: rgb(34 211 238);
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
    return this.assistantProfiles()
      .map((profile) => typeof profile?.key === 'string' ? profile.key : '')
      .filter(Boolean);
  });

  readonly assistantProfiles = computed<AssistantProfileDraft[]>(() => {
    try {
      const parsed = JSON.parse(this.assistantProfilesJson || '[]');
      return Array.isArray(parsed) ? parsed.filter((profile) => this.asRecord(profile)) as AssistantProfileDraft[] : [];
    } catch {
      return [];
    }
  });

  readonly activeAssistantProfile = computed<AssistantProfileDraft | null>(() =>
    this.assistantProfiles().find((profile) => profile.key === this.assistantProfileDefault) ?? null,
  );

  readonly workspaceDefaultScope = computed(() =>
    this.scopes().find((scope) => scope.is_default)?.key || this.scopes()[0]?.key || null,
  );

  readonly effectiveScopeKey = computed(() =>
    this.activeAssistantProfile()?.default_knowledge_scope || this.workspaceDefaultScope(),
  );

  readonly effectiveScopeLabel = computed(() => this.scopeLabel(this.effectiveScopeKey()));

  readonly activeProfileChatOverrides = computed(() => {
    const profile = this.activeAssistantProfile();
    if (!profile) return false;
    const chat = this.asRecord(profile.chat);
    return Boolean(
      this.str(chat['title'])
      || this.str(chat['subtitle'])
      || this.str(chat['placeholder'])
      || this.promptPackDraft(chat['prompt_pack']).length,
    );
  });

  readonly effectiveChatTitle = computed(() => {
    const configured = this.str(this.effectiveChatConfig()['title']);
    if (configured) return configured;
    const profile = this.activeAssistantProfile();
    if (profile?.label) return `Ask ${profile.label}`;
    return 'Start a conversation';
  });

  readonly effectiveChatSubtitle = computed(() => {
    const configured = this.str(this.effectiveChatConfig()['subtitle']);
    if (configured) return configured;
    const scope = this.effectiveScopeLabel();
    return scope && scope !== 'workspace'
      ? `Ask a sourced question using ${scope}.`
      : 'Ask a workspace question, or choose a Knowledge source before sending.';
  });

  readonly effectiveChatPlaceholder = computed(() => {
    const configured = this.str(this.effectiveChatConfig()['placeholder']);
    if (configured) return configured;
    const scope = this.effectiveScopeLabel();
    return scope && scope !== 'workspace'
      ? `Ask a sourced question using ${scope}...`
      : 'Ask a workspace question...';
  });

  readonly effectivePromptCards = computed<PromptCardDraft[]>(() => {
    const config = this.effectiveChatConfig();
    const activeScope = this.effectiveScopeKey();
    const byScope = this.asRecord(config['prompt_pack_by_scope']);
    const scopedPack = activeScope ? this.promptPackDraft(byScope[activeScope]) : [];
    if (scopedPack.length) return scopedPack.slice(0, 4);
    const workspacePack = this.promptPackDraft(config['prompt_pack']).filter((card) => {
      return !card.scope_key || !activeScope || card.scope_key === activeScope;
    });
    if (workspacePack.length) return workspacePack.slice(0, 4);
    return this.generatedKnowledgePrompts(this.effectiveScopeLabel());
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

  copyEffectiveChatToWorkspace(): void {
    this.chatDraft = {
      title: this.effectiveChatTitle(),
      subtitle: this.effectiveChatSubtitle(),
      placeholder: this.effectiveChatPlaceholder(),
      prompt_pack: this.effectivePromptCards().map((prompt) => ({ ...prompt })),
    };
    this.toastr.info('Preview copied into editable workspace defaults', 'Workspace');
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
    settings['chat'] = this.cleanChatSettings(this.asRecord(settings['chat']));
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

  private cleanChatSettings(base: Record<string, unknown> = {}): Record<string, unknown> {
    const chat: Record<string, unknown> = { ...base };
    this.setOrDelete(chat, 'title', this.chatDraft.title);
    this.setOrDelete(chat, 'subtitle', this.chatDraft.subtitle);
    this.setOrDelete(chat, 'placeholder', this.chatDraft.placeholder);
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
    else delete chat['prompt_pack'];
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

  private effectiveChatConfig(): Record<string, unknown> {
    const workspaceChat = this.workspaceChatDraftRecord();
    const profileChat = this.asRecord(this.activeAssistantProfile()?.chat);
    return { ...workspaceChat, ...profileChat };
  }

  private workspaceChatDraftRecord(): Record<string, unknown> {
    const chat: Record<string, unknown> = { ...this.asRecord(this.detail()?.settings?.['chat']) };
    this.setOrDelete(chat, 'title', this.chatDraft.title);
    this.setOrDelete(chat, 'subtitle', this.chatDraft.subtitle);
    this.setOrDelete(chat, 'placeholder', this.chatDraft.placeholder);
    const prompts = this.chatDraft.prompt_pack
      .map((prompt) => ({ ...prompt }))
      .filter((prompt) => prompt.label.trim() && prompt.prompt.trim());
    if (prompts.length) chat['prompt_pack'] = prompts;
    else delete chat['prompt_pack'];
    return chat;
  }

  private setOrDelete(target: Record<string, unknown>, key: string, value: string): void {
    const trimmed = value.trim();
    if (trimmed) target[key] = trimmed;
    else delete target[key];
  }

  private generatedKnowledgePrompts(sourceLabel: string): PromptCardDraft[] {
    const label = sourceLabel || 'workspace Knowledge';
    return [
      {
        icon: 'file-search',
        label: 'Find a value',
        prompt: `In ${label}, find the value of a business parameter and cite the file, page/sheet, and row or section used.`,
        scope_key: '',
        context_mode: 'any',
      },
      {
        icon: 'binary',
        label: 'Cited answer',
        prompt: `Answer using ${label} only, with citations for every factual claim.`,
        scope_key: '',
        context_mode: 'any',
      },
      {
        icon: 'layers',
        label: 'Locate the table',
        prompt: `Find the table or section in ${label} that defines a parameter, then explain how to read it.`,
        scope_key: '',
        context_mode: 'any',
      },
      {
        icon: 'shield-check',
        label: 'Evidence gap',
        prompt: `Check whether ${label} contains enough evidence to answer the question, and say what is missing if it does not.`,
        scope_key: '',
        context_mode: 'any',
      },
    ];
  }

  private scopeLabel(scopeKey: string | null | undefined): string {
    if (!scopeKey) return 'workspace';
    const scope = this.scopes().find((item) => item.key === scopeKey);
    return scope?.label || scopeKey;
  }
}
