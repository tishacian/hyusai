import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { ToastrService } from 'ngx-toastr';

import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import {
  RagPresetService,
  type RagPreset,
  type RagPresetScope,
} from '@app/core/rag-preset.service';

/**
 * Presets catalog — the "Govern · Presets" landing page.
 *
 * Each row is a preset; the page groups by scope so the admin sees at a
 * glance which workspace/capability/system-level overrides are active and
 * which one is the default. Follows the `<ck-object-header>` + cards
 * pattern agreed for Vague A (see legacy-screens-audit.canvas.tsx).
 */
@Component({
  selector: 'app-presets-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, CkObjectHeaderComponent],
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
        (click)="createWorkspaceDefault()"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
        [disabled]="creating()"
      >
        {{ creating() ? 'Cloning…' : 'Clone default' }}
      </button>
    </ck-object-header>

    @if (loading()) {
      <div class="t-card rounded-md p-5 text-center text-xs text-gray-400">
        Loading presets…
      </div>
    } @else if (presets().length === 0) {
      <div class="t-card rounded-md p-8 text-center">
        <h3 class="text-sm font-semibold text-white mb-2">No preset yet</h3>
        <p class="text-xs text-gray-400">
          The backend hasn't seeded a workspace preset. Run a settings change
          from the legacy /settings page to auto-create one, or clone the
          process default above.
        </p>
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
              <span class="text-[11px] text-gray-500">{{ group.items.length }} preset{{ group.items.length === 1 ? '' : 's' }}</span>
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
  `,
})
export class PresetsListComponent implements OnInit {
  private readonly service = inject(RagPresetService);
  private readonly toastr = inject(ToastrService);

  readonly presets = signal<RagPreset[]>([]);
  readonly loading = signal(true);
  readonly creating = signal(false);

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
    return order
      .map((scope) => ({
        scope,
        items: this.presets()
          .filter((p) => p.scope === scope)
          .sort((a, b) => Number(b.is_default) - Number(a.is_default)),
      }))
      .filter((g) => g.items.length > 0);
  });

  ngOnInit(): void {
    this.refresh();
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

  summarize(p: RagPreset): string {
    const cfg = p.config ?? {};
    const provider = cfg['defaultProvider'] ?? '—';
    const model = cfg['defaultModel'] ?? '—';
    const topK = cfg['ragTopK'] ?? '—';
    const mode = cfg['ragPipelineMode'] ?? cfg['ragUseHybridSearch'] ? 'hybrid' : 'vector';
    return `Provider ${provider} · Model ${model} · Top-K ${topK} · Mode ${mode}`;
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

  createWorkspaceDefault(): void {
    const existing = this.presets().find(
      (p) => p.scope === 'workspace' && p.is_default,
    );
    const base = existing?.config ?? {};
    const stamp = new Date().toISOString().slice(0, 16).replace('T', ' ');
    this.creating.set(true);
    this.service
      .create({
        name: `Preset — ${stamp}`,
        scope: 'workspace',
        config: { ...base } as any,
        is_default: false,
      })
      .then(() => {
        this.toastr.success('Preset cloned');
        this.refresh();
      })
      .catch(() => this.toastr.error('Failed to clone preset'))
      .finally(() => this.creating.set(false));
  }
}
