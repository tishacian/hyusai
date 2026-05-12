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
import { ToastrService } from 'ngx-toastr';

import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { CkPanelComponent } from '@app/shared/cockpit/panel.component';
import {
  RagPresetService,
  type RagPreset,
  type RagPresetScope,
} from '@app/core/rag-preset.service';
import {
  CanonicalApiService,
  type Capability,
  type System,
} from '@app/core/canonical-api.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { WorkspaceService } from '@app/core/workspace.service';
import type { AppSettings } from '@app/core/settings.service';

type DraftState = {
  name: string;
  scope: RagPresetScope;
  scopeId: string | null;
  baseId: string | null;
  isDefault: boolean;
};

/**
 * Presets catalog — the "Govern · Presets" landing page.
 *
 * Each row is a preset; the page groups by scope so the admin sees at a
 * glance which workspace/capability/system-level overrides are active and
 * which one is the default. A side `<ck-panel>` drives the full
 * multi-scope workflow: create a new preset at any scope, clone an
 * existing preset to a different scope, or simulate the effective
 * resolution the backend would return for a given (capability, system)
 * pair.
 */
@Component({
  selector: 'app-presets-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    FormsModule,
    CkObjectHeaderComponent,
    CkPanelComponent,
  ],
  template: `
    <ck-object-header
      eyebrow="Govern · Presets"
      title="RAG Presets"
      subtitle="Multi-scope retrieval + generation configuration. The most specific preset wins at run time: system > capability > workspace."
      [kpis]="kpis()"
    >
      <button
        actions
        type="button"
        (click)="openResolvePanel()"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
      >
        Resolve preset
      </button>
      <a
        actions
        routerLink="/presets/evaluation"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-emerald-500/15 hover:bg-emerald-500/20 text-emerald-200 ring-1 ring-emerald-500/30 transition"
      >
        Evaluation thresholds
      </a>
      <button
        actions
        type="button"
        (click)="openNewPanel()"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white transition"
      >
        + New preset
      </button>
    </ck-object-header>

    @if (loading()) {
      <div class="t-card rounded-md p-5 text-center text-xs text-gray-400">
        Loading presets…
      </div>
    } @else if (presets().length === 0) {
      <div class="t-card rounded-md p-8 text-center">
        <h3 class="text-sm font-semibold text-white mb-2">No preset yet</h3>
        <p class="text-xs text-gray-400 mb-4">
          This page lists RAG presets. The showcase evaluation loop lives under
          <a routerLink="/presets/evaluation" class="text-brand-300 hover:text-brand-200">Evaluation thresholds</a>.
          Use
          <span class="font-semibold">New preset</span> above to create one,
          or keep using the workspace default.
        </p>
        <button
          type="button"
          (click)="openNewPanel()"
          class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white transition"
        >
          Create workspace default
        </button>
      </div>
    } @else {
      <section class="space-y-5">
        @for (group of groupedPresets(); track group.scope) {
          <div class="t-card t-elevated rounded-md overflow-hidden">
            <header class="flex items-center justify-between px-4 py-3 bg-white/5 border-b border-white/10">
              <div>
                <div class="text-[10px] uppercase tracking-[0.14em] text-gray-500 font-semibold">
                  Scope
                </div>
                <h3 class="text-sm font-semibold text-white">
                  {{ scopeLabel(group.scope) }}
                </h3>
              </div>
              <div class="flex items-center gap-3">
                <span class="text-[11px] text-gray-500">
                  {{ group.items.length }} preset{{ group.items.length === 1 ? '' : 's' }}
                </span>
                <button
                  type="button"
                  class="text-[11px] px-2 py-1 rounded bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-300 transition"
                  (click)="openNewPanelForScope(group.scope)"
                >
                  + Add
                </button>
              </div>
            </header>
            <ul class="divide-y divide-white/10">
              @for (p of group.items; track p.id) {
                <li class="px-4 py-3 flex items-center justify-between gap-3 hover:bg-white/5 transition">
                  <div class="flex items-start gap-3 min-w-0">
                    <span
                      class="mt-1 inline-block w-2 h-2 rounded-full shrink-0"
                      [class.bg-brand-400]="p.is_default"
                      [class.bg-gray-600]="!p.is_default"
                      [title]="p.is_default ? 'Default preset for this scope' : 'Secondary preset'"
                    ></span>
                    <div class="min-w-0">
                      <div class="flex items-center gap-2 flex-wrap">
                        <a
                          [routerLink]="['/presets', p.id]"
                          class="text-sm font-medium text-white hover:text-brand-300 truncate"
                        >
                          {{ p.name }}
                        </a>
                        @if (p.is_default) {
                          <span class="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-brand-500/15 text-brand-300 ring-1 ring-brand-500/40">
                            Default
                          </span>
                        }
                        @if (p.scope_id) {
                          <span
                            class="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-white/5 text-gray-400 ring-1 ring-white/10"
                            [title]="p.scope_id"
                          >
                            {{ scopeAnchorLabel(p) }}
                          </span>
                        }
                      </div>
                      <p class="text-[11px] text-gray-500 mt-0.5 truncate">
                        {{ summarize(p) }}
                      </p>
                    </div>
                  </div>
                  <div class="flex items-center gap-2 shrink-0">
                    @if (!p.is_default) {
                      <button
                        type="button"
                        class="px-2.5 py-1 text-[11px] rounded bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-300 transition"
                        (click)="setDefault(p.id)"
                      >
                        Set default
                      </button>
                    }
                    <button
                      type="button"
                      class="px-2.5 py-1 text-[11px] rounded bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-300 transition"
                      (click)="openCloneFrom(p)"
                    >
                      Clone…
                    </button>
                    <button
                      type="button"
                      class="px-2.5 py-1 text-[11px] rounded bg-white/5 hover:bg-red-500/15 ring-1 ring-white/10 hover:ring-red-500/40 text-gray-300 hover:text-red-200 transition disabled:opacity-40 disabled:hover:bg-white/5 disabled:hover:text-gray-300"
                      [disabled]="p.is_default && p.scope === 'workspace'"
                      [title]="p.is_default && p.scope === 'workspace' ? 'The workspace default cannot be deleted' : 'Delete preset'"
                      (click)="confirmDelete(p)"
                    >
                      Delete
                    </button>
                    <a
                      [routerLink]="['/presets', p.id]"
                      class="px-2.5 py-1 text-[11px] rounded bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-300 transition"
                    >
                      Open →
                    </a>
                  </div>
                </li>
              }
            </ul>
          </div>
        }
      </section>
    }

    <!-- NEW / CLONE PRESET PANEL -->
    <ck-panel
      [open]="newPanelOpen()"
      (openChange)="newPanelOpen.set($event)"
      position="side"
      eyebrow="Presets · new"
      [title]="newPanelTitle()"
      width="460px"
    >
      <p class="text-xs text-gray-400 mb-4">
        {{ draftBase() ? 'Clone this preset into a new scope — the new preset keeps the source configuration and can diverge independently.' : 'Create a new preset. Pick a scope (workspace, capability, or system) and a base to inherit values from.' }}
      </p>

      <div class="space-y-4">
        <div>
          <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
            Name
          </label>
          <input
            type="text"
            [ngModel]="draft().name"
            (ngModelChange)="patchDraft({ name: $event })"
            class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-brand-500/60"
            placeholder="e.g. EU-West high-recall"
          />
        </div>

        <div>
          <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
            Scope
          </label>
          <div class="grid grid-cols-3 gap-1.5 mt-1.5">
            @for (s of scopeChoices; track s.value) {
              <button
                type="button"
                class="px-3 py-2 rounded text-xs font-medium ring-1 transition"
                [class.bg-brand-500\\/15]="draft().scope === s.value"
                [class.text-brand-200]="draft().scope === s.value"
                [class.ring-brand-500\\/40]="draft().scope === s.value"
                [class.bg-white\\/5]="draft().scope !== s.value"
                [class.text-gray-300]="draft().scope !== s.value"
                [class.ring-white\\/10]="draft().scope !== s.value"
                (click)="selectScope(s.value)"
              >
                {{ s.label }}
              </button>
            }
          </div>
        </div>

        @if (draft().scope === 'capability') {
          <div>
            <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
              Anchor capability
            </label>
            <select
              [ngModel]="draft().scopeId"
              (ngModelChange)="patchDraft({ scopeId: $event })"
              class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-brand-500/60"
            >
              <option [ngValue]="null" disabled>— Select a capability —</option>
              @for (c of capabilities(); track c.id) {
                <option [ngValue]="c.id">{{ c.name }}</option>
              }
            </select>
          </div>
        } @else if (draft().scope === 'system') {
          <div>
            <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
              Anchor system
            </label>
            <select
              [ngModel]="draft().scopeId"
              (ngModelChange)="patchDraft({ scopeId: $event })"
              class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-brand-500/60"
            >
              <option [ngValue]="null" disabled>— Select a system —</option>
              @for (s of systems(); track s.id) {
                <option [ngValue]="s.id">{{ s.name }}</option>
              }
            </select>
          </div>
        }

        <div>
          <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
            Seed configuration from
          </label>
          <select
            [ngModel]="draft().baseId"
            (ngModelChange)="patchDraft({ baseId: $event })"
            class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-brand-500/60"
          >
            <option [ngValue]="null">Empty config (use backend defaults)</option>
            @for (p of presets(); track p.id) {
              <option [ngValue]="p.id">
                {{ p.name }} ({{ scopeLabel(p.scope) }}{{ p.is_default ? ' · default' : '' }})
              </option>
            }
          </select>
        </div>

        <label class="flex items-center gap-2 text-xs text-gray-200 cursor-pointer pt-1">
          <input
            type="checkbox"
            [checked]="draft().isDefault"
            (change)="onIsDefaultChange($event)"
            class="accent-brand-500"
          />
          Set as default for this scope
        </label>
      </div>

      <div class="mt-5 flex items-center justify-end gap-2">
        <button
          type="button"
          class="px-3 py-2 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-300 transition"
          (click)="newPanelOpen.set(false)"
        >
          Cancel
        </button>
        <button
          type="button"
          class="px-3 py-2 rounded text-xs font-medium bg-brand-500 hover:bg-brand-600 text-white transition disabled:opacity-50"
          [disabled]="!canSubmit() || creating()"
          (click)="submitNew()"
        >
          {{ creating() ? 'Creating…' : (draftBase() ? 'Clone preset' : 'Create preset') }}
        </button>
      </div>
    </ck-panel>

    <!-- RESOLVE PRESET PANEL -->
    <ck-panel
      [open]="resolvePanelOpen()"
      (openChange)="resolvePanelOpen.set($event)"
      position="side"
      eyebrow="Presets · resolve"
      title="Effective preset resolver"
      width="420px"
    >
      <p class="text-xs text-gray-400 mb-4">
        Simulate which preset the backend would pick for a given
        (capability, system) pair. The rule is <span class="ck-mono">system &gt; capability &gt; workspace</span>.
      </p>

      <div class="space-y-4">
        <div>
          <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
            Capability (optional)
          </label>
          <select
            [(ngModel)]="resolveCap"
            class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-brand-500/60"
          >
            <option [ngValue]="null">— None —</option>
            @for (c of capabilities(); track c.id) {
              <option [ngValue]="c.id">{{ c.name }}</option>
            }
          </select>
        </div>
        <div>
          <label class="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
            System (optional)
          </label>
          <select
            [(ngModel)]="resolveSys"
            class="mt-1.5 w-full px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-sm text-white focus:outline-none focus:ring-brand-500/60"
          >
            <option [ngValue]="null">— None —</option>
            @for (s of systems(); track s.id) {
              <option [ngValue]="s.id">{{ s.name }}</option>
            }
          </select>
        </div>
        <button
          type="button"
          class="w-full px-3 py-2 rounded text-xs font-medium bg-brand-500 hover:bg-brand-600 text-white transition disabled:opacity-50"
          [disabled]="resolving()"
          (click)="runResolve()"
        >
          {{ resolving() ? 'Resolving…' : 'Resolve effective preset' }}
        </button>

        @if (resolveResult(); as r) {
          <div class="rounded-md ring-1 ring-white/10 bg-white/5 p-3 space-y-2">
            <div class="flex items-center justify-between">
              <span class="text-[10px] uppercase tracking-[0.14em] text-gray-500 font-semibold">
                Winning scope
              </span>
              <span class="text-[11px] px-2 py-0.5 rounded bg-brand-500/15 text-brand-200 ring-1 ring-brand-500/40 uppercase tracking-wider">
                {{ r.scope_hint }}
              </span>
            </div>
            <dl class="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
              @if (isDemoMode()) {
                <dt class="text-gray-500">Runtime</dt>
                <dd class="text-gray-100 ck-mono">Managed</dd>
              } @else {
                <dt class="text-gray-500">Provider</dt>
                <dd class="text-gray-100 ck-mono">{{ r.config.defaultProvider ?? '—' }}</dd>
                <dt class="text-gray-500">Model</dt>
                <dd class="text-gray-100 ck-mono">{{ r.config.defaultModel ?? '—' }}</dd>
              }
              <dt class="text-gray-500">Mode</dt>
              <dd class="text-gray-100 ck-mono">{{ r.config.ragPipelineMode ?? '—' }}</dd>
              <dt class="text-gray-500">Top-K</dt>
              <dd class="text-gray-100 ck-mono">{{ r.config.ragTopK ?? '—' }}</dd>
              <dt class="text-gray-500">Hybrid</dt>
              <dd class="text-gray-100 ck-mono">{{ r.config.ragUseHybridSearch ? 'on' : 'off' }}</dd>
            </dl>
          </div>
        }
      </div>
    </ck-panel>
  `,
})
export class PresetsListComponent implements OnInit {
  private readonly service = inject(RagPresetService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly toastr = inject(ToastrService);
  private readonly zoom = inject(ZoomContextService);
  private readonly workspace = inject(WorkspaceService);
  readonly isDemoMode = computed(() => this.workspace.isDemoMode());

  readonly presets = signal<RagPreset[]>([]);
  readonly capabilities = signal<Capability[]>([]);
  readonly systems = signal<System[]>([]);
  readonly loading = signal(true);
  readonly creating = signal(false);

  // -- Panel state ----------------------------------------------------------
  readonly newPanelOpen = signal(false);
  readonly resolvePanelOpen = signal(false);
  readonly resolving = signal(false);
  readonly resolveResult = signal<{
    scope_hint: RagPresetScope;
    config: AppSettings;
  } | null>(null);
  resolveCap: string | null = null;
  resolveSys: string | null = null;

  readonly scopeChoices: { value: RagPresetScope; label: string }[] = [
    { value: 'workspace', label: 'Workspace' },
    { value: 'capability', label: 'Capability' },
    { value: 'system', label: 'System' },
  ];

  readonly draft = signal<DraftState>({
    name: '',
    scope: 'workspace',
    scopeId: null,
    baseId: null,
    isDefault: false,
  });

  readonly draftBase = computed<RagPreset | null>(() => {
    const id = this.draft().baseId;
    if (!id) return null;
    return this.presets().find((p) => p.id === id) ?? null;
  });

  readonly newPanelTitle = computed(() =>
    this.draftBase() ? 'Clone preset to new scope' : 'New preset',
  );

  readonly canSubmit = computed(() => {
    const d = this.draft();
    if (!d.name.trim()) return false;
    if (d.scope !== 'workspace' && !d.scopeId) return false;
    return true;
  });

  readonly kpis = computed<CkObjectKpi[]>(() => {
    const list = this.presets();
    const total = list.length;
    const workspace = list.filter((p) => p.scope === 'workspace').length;
    const capability = list.filter((p) => p.scope === 'capability').length;
    const system = list.filter((p) => p.scope === 'system').length;
    return [
      { label: 'Total', value: String(total) },
      { label: 'Workspace', value: String(workspace), tone: 'cool' },
      { label: 'Capability', value: String(capability), tone: 'violet' },
      { label: 'System', value: String(system), tone: 'pos' },
    ];
  });

  readonly groupedPresets = computed<{ scope: RagPresetScope; items: RagPreset[] }[]>(() => {
    const order: RagPresetScope[] = ['workspace', 'capability', 'system'];
    return order.map((scope) => ({
      scope,
      items: this.presets()
        .filter((p) => p.scope === scope)
        .sort((a, b) => Number(b.is_default) - Number(a.is_default)),
    }));
  });

  ngOnInit(): void {
    // Presets is workspace-scoped administration — drop any prior
    // Capability/System/Run focus so the breadcrumb reads
    // "Portfolio › Presets" rather than lying about an active object.
    this.zoom.clear();
    this.refresh();
    this.canonical.listCapabilities().subscribe((list) => this.capabilities.set(list));
    this.canonical.listSystems().subscribe((list) => this.systems.set(list));
  }

  private refresh(): void {
    this.loading.set(true);
    this.service
      .list()
      .then((list) => this.presets.set(list))
      .catch(() => this.toastr.error('Unable to load presets'))
      .finally(() => this.loading.set(false));
  }

  scopeLabel(scope: RagPresetScope): string {
    switch (scope) {
      case 'workspace':
        return 'Workspace defaults';
      case 'capability':
        return 'Capability overrides';
      case 'system':
        return 'System overrides';
    }
  }

  scopeAnchorLabel(p: RagPreset): string {
    if (!p.scope_id) return '';
    if (p.scope === 'capability') {
      return this.capabilities().find((c) => c.id === p.scope_id)?.name
        ?? `cap:${p.scope_id.slice(0, 6)}`;
    }
    if (p.scope === 'system') {
      return this.systems().find((s) => s.id === p.scope_id)?.name
        ?? `sys:${p.scope_id.slice(0, 6)}`;
    }
    return p.scope_id;
  }

  summarize(p: RagPreset): string {
    const cfg = p.config ?? {};
    if (this.isDemoMode()) {
      const topK = cfg.ragTopK ?? '—';
      const mode = cfg.ragPipelineMode ?? (cfg.ragUseHybridSearch ? 'hybrid' : 'vector');
      return `Runtime managed · Top-K ${topK} · Mode ${mode}`;
    }
    const provider = cfg.defaultProvider ?? '—';
    const model = cfg.defaultModel ?? '—';
    const topK = cfg.ragTopK ?? '—';
    const mode = cfg.ragPipelineMode ?? (cfg.ragUseHybridSearch ? 'hybrid' : 'vector');
    return `Provider ${provider} · Model ${model} · Top-K ${topK} · Mode ${mode}`;
  }

  patchDraft(patch: Partial<DraftState>): void {
    this.draft.set({ ...this.draft(), ...patch });
  }

  onIsDefaultChange(ev: Event): void {
    const checked = (ev.target as HTMLInputElement | null)?.checked ?? false;
    this.patchDraft({ isDefault: checked });
  }

  setDefault(id: string): void {
    this.service
      .setDefault(id)
      .then(() => {
        this.toastr.success('Preset elected as default');
        this.refresh();
      })
      .catch(() => this.toastr.error('Failed to update default preset'));
  }

  // -- New / Clone panel ----------------------------------------------------

  openNewPanel(): void {
    const defaultWs = this.presets().find(
      (p) => p.scope === 'workspace' && p.is_default,
    );
    this.draft.set({
      name: this.suggestName('workspace'),
      scope: 'workspace',
      scopeId: null,
      baseId: defaultWs?.id ?? null,
      isDefault: this.presets().filter((p) => p.scope === 'workspace').length === 0,
    });
    this.newPanelOpen.set(true);
  }

  openNewPanelForScope(scope: RagPresetScope): void {
    const defaultWs = this.presets().find(
      (p) => p.scope === 'workspace' && p.is_default,
    );
    this.draft.set({
      name: this.suggestName(scope),
      scope,
      scopeId: null,
      baseId: defaultWs?.id ?? null,
      isDefault: this.presets().filter((p) => p.scope === scope).length === 0,
    });
    this.newPanelOpen.set(true);
  }

  openCloneFrom(source: RagPreset): void {
    this.draft.set({
      name: `${source.name} (clone)`,
      scope: source.scope,
      scopeId: source.scope_id ?? null,
      baseId: source.id,
      isDefault: false,
    });
    this.newPanelOpen.set(true);
  }

  selectScope(scope: RagPresetScope): void {
    // Changing scope invalidates the scope_id anchor.
    this.patchDraft({
      scope,
      scopeId: scope === 'workspace' ? null : this.draft().scopeId,
    });
  }

  submitNew(): void {
    if (!this.canSubmit()) return;
    const d = this.draft();
    const base = this.draftBase();
    const config = (base?.config ?? {}) as AppSettings;
    this.creating.set(true);
    this.service
      .create({
        name: d.name.trim(),
        scope: d.scope,
        scope_id: d.scope === 'workspace' ? null : d.scopeId,
        config,
        is_default: d.isDefault,
      })
      .then(() => {
        this.toastr.success('Preset created');
        this.newPanelOpen.set(false);
        this.refresh();
      })
      .catch(() => this.toastr.error('Failed to create preset'))
      .finally(() => this.creating.set(false));
  }

  private suggestName(scope: RagPresetScope): string {
    const stamp = new Date().toISOString().slice(0, 16).replace('T', ' ');
    const label =
      scope === 'workspace' ? 'Workspace' : scope === 'capability' ? 'Capability' : 'System';
    return `${label} preset — ${stamp}`;
  }

  // -- Delete ---------------------------------------------------------------

  confirmDelete(p: RagPreset): void {
    if (p.is_default && p.scope === 'workspace') {
      this.toastr.warning('The workspace default cannot be deleted.');
      return;
    }
    const ok = typeof window !== 'undefined'
      ? window.confirm(`Delete preset "${p.name}"? This cannot be undone.`)
      : true;
    if (!ok) return;
    this.service
      .remove(p.id)
      .then(() => {
        this.toastr.success('Preset deleted');
        this.refresh();
      })
      .catch(() => this.toastr.error('Failed to delete preset'));
  }

  // -- Resolve panel --------------------------------------------------------

  openResolvePanel(): void {
    this.resolveResult.set(null);
    this.resolvePanelOpen.set(true);
  }

  runResolve(): void {
    this.resolving.set(true);
    this.service
      .resolve({ capability_id: this.resolveCap, system_id: this.resolveSys })
      .then((res) => this.resolveResult.set(res))
      .catch(() => this.toastr.error('Failed to resolve preset'))
      .finally(() => this.resolving.set(false));
  }
}
