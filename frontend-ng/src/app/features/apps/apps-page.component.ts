import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';
import { NgClass } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ToastrService } from 'ngx-toastr';
import { WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import {
  APPS,
  AppDef,
  readAppToggles,
  writeAppToggle,
} from '../resources/resources.catalog';

type Filter = 'all' | 'enabled' | 'ready' | 'beta';

@Component({
  selector: 'app-apps-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgClass,
    FormsModule,
    IconComponent,
    CkObjectHeaderComponent,
  ],
  template: `
    <ck-object-header
      eyebrow="Govern · Apps"
      title="Apps & integrations"
      subtitle="Packaged extensions and integrations the orchestrator can plug into any system — not to be confused with /skills, the atomic registry."
      [kpis]="headerKpis()"
    >
      <a
        actions
        href="mailto:product@agentium.papai.ai?subject=App%20runtime%20wiring%20request"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
      >
        <app-icon name="send" [size]="14" /> Request wiring
      </a>
    </ck-object-header>

    <div class="mb-5 rounded-md p-3 bg-amber-500/5 ring-1 ring-amber-500/25 flex items-start gap-3">
      <app-icon name="alert-triangle" [size]="14" class="text-amber-400 mt-0.5 shrink-0" />
      <div class="flex-1">
        <div class="text-[11px] uppercase tracking-wider font-semibold text-amber-300 mb-0.5">
          Catalog only · no runtime wiring yet
        </div>
        <p class="text-[11px] text-amber-200/80 leading-relaxed">
          These apps advertise orchestrator integrations but are not yet bound to a backend runtime.
          Toggling them surfaces them in the Builder wizard but does not connect to a live service.
          Use <span class="font-semibold">Request wiring</span> to prioritise one. For atomic
          skill primitives, head to <span class="font-mono">/skills</span>.
        </p>
      </div>
    </div>

    <div class="flex items-center gap-1 mb-5 p-1 bg-white/5 ring-1 ring-white/10 rounded-md w-fit">
      @for (f of filters; track f.id) {
        <button
          type="button"
          (click)="filter.set(f.id)"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition"
          [ngClass]="filter() === f.id
            ? 'bg-cyan-500 text-white shadow-glow-sm'
            : 'text-gray-400 hover:text-gray-200 hover:bg-white/5'"
        >
          {{ f.label }}
          <span
            class="ml-1 text-[9px] font-mono px-1 rounded"
            [class.bg-white\\/15]="filter() === f.id"
            [class.bg-white\\/5]="filter() !== f.id"
          >
            {{ f.count() }}
          </span>
        </button>
      }
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
      @for (a of filtered(); track a.id) {
        <div
          class="ck-surface t-elevated rounded-md p-4 flex flex-col gap-2.5 transition"
          [ngClass]="isEnabled(a.id)
            ? 'ring-1 ring-cyan-500/40 bg-cyan-500/5'
            : ''"
        >
          <div class="flex items-start justify-between">
            <div
              class="w-10 h-10 rounded-md flex items-center justify-center"
              [ngClass]="isEnabled(a.id)
                ? 'bg-cyan-500/20 text-cyan-300'
                : 'bg-white/5 text-gray-400'"
            >
              <app-icon [name]="a.icon" [size]="20" />
            </div>
            <div class="flex items-center gap-2">
              <span
                class="text-[9px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded ring-1 bg-white/5 text-gray-400 ring-white/10"
                title="Listed in the catalog but not yet bound to a runtime"
              >
                catalog only
              </span>
              <button
                type="button"
                (click)="toggle(a.id)"
                role="switch"
                [attr.aria-checked]="isEnabled(a.id)"
                class="w-10 h-5 rounded-full relative transition-colors"
                [ngClass]="isEnabled(a.id) ? 'bg-cyan-500' : 'bg-white/10'"
              >
                <span
                  class="block w-3.5 h-3.5 bg-white rounded-full absolute top-[3px] transition-all"
                  [ngClass]="isEnabled(a.id) ? 'left-[22px]' : 'left-[3px]'"
                ></span>
              </button>
            </div>
          </div>
          <div>
            <div class="text-sm font-semibold text-white">{{ a.name }}</div>
            <p class="text-[11px] text-gray-400 leading-relaxed mt-0.5">
              {{ a.description }}
            </p>
          </div>
          <div class="text-[10px] font-mono text-gray-500 mt-auto pt-2 border-t border-white/5">
            ID: {{ a.id }}
          </div>
        </div>
      }
    </div>

    <div class="mt-6 rounded-md p-4 bg-cyan-500/5 ring-1 ring-cyan-500/20 flex items-start gap-3 max-w-2xl">
      <app-icon name="lightbulb" [size]="14" class="text-cyan-400 mt-0.5 shrink-0" />
      <p class="text-[11px] text-cyan-200/90 leading-relaxed">
        Enabling an app exposes it in the Builder wizard per system. Runtime
        wiring is still on the roadmap — until a backend connector ships,
        toggles act as catalog intent only.
      </p>
    </div>
  `,
})
export class AppsPageComponent {
  private readonly toast = inject(ToastrService);
  private readonly workspace = inject(WorkspaceService);

  readonly APPS = APPS;
  readonly filter = signal<Filter>('all');
  private readonly version = signal(0);

  readonly filters = [
    { id: 'all' as Filter, label: 'All', count: () => APPS.length },
    { id: 'enabled' as Filter, label: 'Enabled', count: () => this.enabledCount() },
    { id: 'ready' as Filter, label: 'Ready', count: () => this.readyCount() },
    { id: 'beta' as Filter, label: 'Beta', count: () => this.betaCount() },
  ];

  readonly filtered = computed<AppDef[]>(() => {
    this.version();
    const toggles = readAppToggles(this.workspace.currentSlug());
    switch (this.filter()) {
      case 'enabled':
        return APPS.filter((a) => !!toggles[a.id]);
      case 'ready':
        return APPS.filter((a) => a.status === 'ready');
      case 'beta':
        return APPS.filter((a) => a.status === 'beta');
      default:
        return APPS;
    }
  });

  readonly enabledCount = computed(() => {
    this.version();
    const t = readAppToggles(this.workspace.currentSlug());
    return Object.values(t).filter(Boolean).length;
  });
  readonly readyCount = computed(() => APPS.filter((a) => a.status === 'ready').length);
  readonly betaCount = computed(() => APPS.filter((a) => a.status === 'beta').length);

  readonly headerKpis = computed<CkObjectKpi[]>(() => [
    { label: 'Total apps', value: String(APPS.length) },
    {
      label: 'Enabled',
      value: String(this.enabledCount()),
      hint: this.enabledCount() > 0 ? 'Ready to be used' : 'Turn some on',
      tone: this.enabledCount() > 0 ? 'pos' : 'neutral',
    },
    { label: 'Ready', value: String(this.readyCount()), tone: 'cool' },
    {
      label: 'In beta',
      value: String(this.betaCount()),
      tone: this.betaCount() > 0 ? 'warn' : 'neutral',
    },
  ]);

  isEnabled(id: string): boolean {
    this.version();
    return !!readAppToggles(this.workspace.currentSlug())[id];
  }

  toggle(id: string): void {
    const slug = this.workspace.currentSlug();
    const current = !!readAppToggles(slug)[id];
    writeAppToggle(slug, id, !current);
    this.version.update((v) => v + 1);
    const app = APPS.find((a) => a.id === id);
    if (app) {
      this.toast.success(
        current ? `${app.name} disabled` : `${app.name} enabled`,
        'Apps',
      );
    }
  }

}
