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
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { StatTileComponent } from '@app/shared/ui/stat-tile.component';
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
    SectionHeaderComponent,
    StatTileComponent,
  ],
  template: `
    <app-section-header
      breadcrumb="Extend"
      title="Apps & skills"
      icon="sparkles"
      subtitle="Capabilities the orchestrator can plug into any system."
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        (click)="enableAll()"
      >
        <app-icon name="check" [size]="14" /> Enable all
      </button>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        (click)="disableAll()"
      >
        <app-icon name="x" [size]="14" /> Disable all
      </button>
    </app-section-header>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      <app-stat-tile label="Total apps" [value]="APPS.length" icon="sparkles" />
      <app-stat-tile
        label="Enabled"
        [value]="enabledCount()"
        icon="check-circle-2"
        [hint]="enabledCount() > 0 ? 'Ready to be used' : 'Turn some on to extend reach'"
      />
      <app-stat-tile
        label="Ready"
        [value]="readyCount()"
        icon="zap"
      />
      <app-stat-tile
        label="In beta"
        [value]="betaCount()"
        icon="flag"
      />
    </div>

    <div class="flex items-center gap-1 mb-5 p-1 bg-white/5 ring-1 ring-white/10 rounded-md w-fit">
      @for (f of filters; track f.id) {
        <button
          type="button"
          (click)="filter.set(f.id)"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition"
          [ngClass]="filter() === f.id
            ? 'bg-brand-500 text-white shadow-glow-sm'
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
          class="t-card t-elevated rounded-md p-4 flex flex-col gap-2.5 transition"
          [ngClass]="isEnabled(a.id)
            ? 'ring-1 ring-brand-500/40 bg-brand-500/5'
            : ''"
        >
          <div class="flex items-start justify-between">
            <div
              class="w-10 h-10 rounded-md flex items-center justify-center"
              [ngClass]="isEnabled(a.id)
                ? 'bg-brand-500/20 text-brand-300'
                : 'bg-white/5 text-gray-400'"
            >
              <app-icon [name]="a.icon" [size]="20" />
            </div>
            <div class="flex items-center gap-2">
              <span
                class="text-[9px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded ring-1"
                [ngClass]="a.status === 'ready'
                  ? 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20'
                  : 'bg-amber-500/10 text-amber-400 ring-amber-500/20'"
              >
                {{ a.status }}
              </span>
              <button
                type="button"
                (click)="toggle(a.id)"
                role="switch"
                [attr.aria-checked]="isEnabled(a.id)"
                class="w-10 h-5 rounded-full relative transition-colors"
                [ngClass]="isEnabled(a.id) ? 'bg-brand-500' : 'bg-white/10'"
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

    <div class="mt-6 rounded-md p-4 bg-brand-500/5 ring-1 ring-brand-500/20 flex items-start gap-3 max-w-2xl">
      <app-icon name="lightbulb" [size]="14" class="text-brand-400 mt-0.5 shrink-0" />
      <p class="text-[11px] text-brand-200/90 leading-relaxed">
        Enabled apps become available in the agent's execution pipeline. The
        orchestrator selects them dynamically based on query intent — the
        builder wizard can also pre-wire a subset per system.
      </p>
    </div>
  `,
})
export class AppsPageComponent {
  private readonly toast = inject(ToastrService);

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
    const toggles = readAppToggles();
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
    const t = readAppToggles();
    return Object.values(t).filter(Boolean).length;
  });
  readonly readyCount = computed(() => APPS.filter((a) => a.status === 'ready').length);
  readonly betaCount = computed(() => APPS.filter((a) => a.status === 'beta').length);

  isEnabled(id: string): boolean {
    this.version();
    return !!readAppToggles()[id];
  }

  toggle(id: string): void {
    const current = !!readAppToggles()[id];
    writeAppToggle(id, !current);
    this.version.update((v) => v + 1);
    const app = APPS.find((a) => a.id === id);
    if (app) {
      this.toast.success(
        current ? `${app.name} disabled` : `${app.name} enabled`,
        'Apps',
      );
    }
  }

  enableAll(): void {
    for (const a of APPS) writeAppToggle(a.id, true);
    this.version.update((v) => v + 1);
    this.toast.success(`All ${APPS.length} apps enabled`, 'Apps');
  }

  disableAll(): void {
    for (const a of APPS) writeAppToggle(a.id, false);
    this.version.update((v) => v + 1);
    this.toast.info('All apps disabled', 'Apps');
  }
}
