import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ApiService } from '@app/core/api.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { StatTileComponent } from '@app/shared/ui/stat-tile.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';

interface ModelInfo {
  id?: string;
  name?: string;
  provider?: string;
  context_length?: number;
  size?: number;
  modified_at?: string;
  [key: string]: unknown;
}

interface Connector {
  id: string;
  name: string;
  icon: string;
  description: string;
  backendPrefix: string | null;
  /** when non-null, the UI calls GET /<prefix>/health or equivalent to assess connectivity */
  status: 'available' | 'unconfigured' | 'coming-soon';
  docsHref?: string;
}

const CONNECTORS: Connector[] = [
  {
    id: 'sharepoint',
    name: 'Microsoft SharePoint',
    icon: 'folder',
    description: 'Sync document libraries through delegated OTP auth.',
    backendPrefix: 'sharepoint',
    status: 'available',
  },
  {
    id: 'slack',
    name: 'Slack',
    icon: 'message-square',
    description: 'Channel history + threaded context ingestion.',
    backendPrefix: null,
    status: 'coming-soon',
  },
  {
    id: 'notion',
    name: 'Notion',
    icon: 'book-open',
    description: 'Workspace pages as live knowledge.',
    backendPrefix: null,
    status: 'coming-soon',
  },
  {
    id: 'confluence',
    name: 'Confluence',
    icon: 'layers',
    description: 'Spaces + pages with ACL-aware retrieval.',
    backendPrefix: null,
    status: 'coming-soon',
  },
];

@Component({
  selector: 'app-resources-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    IconComponent,
    SectionHeaderComponent,
    StatTileComponent,
    EmptyStateComponent,
    StatusPulseComponent,
  ],
  template: `
    <app-section-header
      breadcrumb="Configure"
      title="Resources"
      icon="plug"
      subtitle="Models available to your systems and external data connectors."
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        (click)="refresh()"
        [disabled]="loading()"
      >
        <app-icon name="refresh-cw" [size]="14" [class.animate-spin]="loading()" />
        Refresh
      </button>
    </app-section-header>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      <app-stat-tile label="Models" [value]="models().length" icon="cpu" />
      <app-stat-tile
        label="Providers"
        [value]="providers().length"
        icon="server"
      />
      <app-stat-tile label="Connectors" [value]="activeConnectors()" icon="plug" />
      <app-stat-tile
        label="Coming soon"
        [value]="comingSoonConnectors()"
        icon="sparkles"
      />
    </div>

    <!-- Models -->
    <section class="t-card t-elevated rounded-md overflow-hidden mb-6">
      <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
          <app-icon name="cpu" [size]="16" class="text-brand-400" />
          Available models
        </h3>
        <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
          {{ models().length }} / {{ providers().length }} providers
        </span>
      </div>

      @if (loading() && models().length === 0) {
        <div class="divide-y divide-white/5">
          @for (_ of [0, 1, 2, 3, 4]; track $index) {
            <div class="px-5 py-3 animate-pulse">
              <div class="h-3 w-60 bg-white/5 rounded"></div>
            </div>
          }
        </div>
      } @else if (models().length === 0) {
        <app-empty-state
          icon="cpu"
          title="No models configured"
          description="Configure a provider in backend settings or start an Ollama instance."
        />
      } @else {
        <ul class="divide-y divide-white/5">
          @for (m of models(); track modelKey(m)) {
            <li class="px-5 py-3 grid grid-cols-12 gap-3 items-center text-sm">
              <div class="col-span-6 min-w-0 flex items-center gap-2">
                <div
                  class="w-7 h-7 rounded-md flex items-center justify-center text-xs font-semibold shrink-0 bg-gradient-to-br from-brand-500/20 to-violet-500/20 ring-1 ring-brand-500/30 text-brand-400"
                >
                  {{ providerInitial(m) }}
                </div>
                <div class="min-w-0">
                  <div class="text-white truncate font-mono text-xs">
                    {{ modelName(m) }}
                  </div>
                  @if (m.provider) {
                    <div class="text-[11px] text-gray-500 capitalize">{{ m.provider }}</div>
                  }
                </div>
              </div>
              <div class="col-span-3 text-xs text-gray-400 font-mono tabular-nums">
                @if (m.context_length) {
                  {{ (m.context_length / 1000).toFixed(0) }}k ctx
                }
              </div>
              <div class="col-span-2 text-xs text-gray-400 font-mono tabular-nums">
                @if (m.size) {
                  {{ (m.size / 1e9).toFixed(1) }} GB
                }
              </div>
              <div class="col-span-1 text-right">
                <app-status-pulse tone="success" label="ready" />
              </div>
            </li>
          }
        </ul>
      }
    </section>

    <!-- Connectors -->
    <section class="grid grid-cols-1 md:grid-cols-2 gap-4">
      @for (c of connectors; track c.id) {
        <div class="t-card t-elevated rounded-md p-5 relative">
          <div class="flex items-start gap-3 mb-3">
            <div
              class="w-10 h-10 rounded-md flex items-center justify-center shrink-0"
              [class.bg-brand-500\\/15]="c.status === 'available'"
              [class.text-brand-400]="c.status === 'available'"
              [class.bg-white\\/5]="c.status !== 'available'"
              [class.text-gray-400]="c.status !== 'available'"
            >
              <app-icon [name]="c.icon" [size]="20" />
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <h3 class="text-sm font-semibold text-white">{{ c.name }}</h3>
                @if (c.status === 'available') {
                  <app-status-pulse tone="success" label="available" />
                } @else if (c.status === 'unconfigured') {
                  <app-status-pulse tone="warning" label="needs setup" />
                } @else {
                  <span
                    class="text-[9px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-white/5 text-gray-400"
                  >
                    Soon
                  </span>
                }
              </div>
              <p class="text-xs text-gray-400 leading-relaxed mt-1">{{ c.description }}</p>
            </div>
          </div>
          @if (c.status === 'available') {
            <div class="flex items-center justify-end">
              <span class="text-[11px] text-gray-500 font-mono">
                /api/v1/{{ c.backendPrefix }}
              </span>
            </div>
          }
        </div>
      }
    </section>
  `,
})
export class ResourcesPageComponent implements OnInit {
  private readonly api = inject(ApiService);

  readonly connectors = CONNECTORS;

  models = signal<ModelInfo[]>([]);
  loading = signal(false);

  readonly providers = computed(() => {
    const set = new Set<string>();
    for (const m of this.models()) {
      if (m.provider) set.add(m.provider);
    }
    return Array.from(set);
  });

  readonly activeConnectors = computed(
    () => CONNECTORS.filter((c) => c.status === 'available').length,
  );
  readonly comingSoonConnectors = computed(
    () => CONNECTORS.filter((c) => c.status === 'coming-soon').length,
  );

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.loading.set(true);
    this.api.get<{ models: ModelInfo[] }>('/models').subscribe({
      next: (res) => {
        this.models.set(res?.models ?? []);
        this.loading.set(false);
      },
      error: () => {
        this.models.set([]);
        this.loading.set(false);
      },
    });
  }

  modelName(m: ModelInfo): string {
    return (
      (typeof m.id === 'string' && m.id) ||
      (typeof m.name === 'string' && m.name) ||
      JSON.stringify(m)
    );
  }

  modelKey(m: ModelInfo): string {
    return this.modelName(m) + ':' + (m.provider ?? '');
  }

  providerInitial(m: ModelInfo): string {
    const p = (m.provider || this.modelName(m)).toString();
    return p.charAt(0).toUpperCase();
  }
}
