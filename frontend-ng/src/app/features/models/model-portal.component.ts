import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ApiService } from '@app/core/api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';

interface ModelProvider {
  key: string;
  label: string;
  kind: 'local' | 'cloud';
  status: 'configured' | 'available';
  models: string[];
  notes: string;
}

interface ProvidersResponse {
  providers?: ModelProvider[];
}

@Component({
  selector: 'app-model-portal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, RouterLink, IconComponent, SectionHeaderComponent],
  template: `
    <app-section-header
      breadcrumb="Workspace"
      title="Models & Providers"
      icon="cpu"
      [subtitle]="
        'LLM providers the platform can route to for ' +
        workspaceName() +
        '. Read-only snapshot — configuration lives server-side.'
      "
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        (click)="loadProviders()"
        [disabled]="loading()"
      >
        <app-icon name="refresh-cw" [size]="14" [class.animate-spin]="loading()" />
        Refresh
      </button>
      <a
        routerLink="/connectors"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
      >
        <app-icon name="arrow-left" [size]="14" /> Back to Connectors
      </a>
    </app-section-header>

    @if (!featureEnabled()) {
      <div class="mb-4 rounded-md bg-amber-500/10 p-3 text-sm text-amber-100 ring-1 ring-amber-400/25">
        Model portal is not enabled for {{ workspaceName() }}. Enable
        <span class="font-mono text-amber-200">features.model_portal_beta</span> on this workspace to view it.
      </div>
    }

    @if (error(); as err) {
      <div class="mb-4 rounded-md bg-red-500/10 p-3 text-sm text-red-100 ring-1 ring-red-400/25">
        {{ err }}
      </div>
    }

    <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      @for (provider of providers(); track provider.key) {
        <section class="ck-surface t-elevated rounded-md p-5 flex flex-col gap-3">
          <header class="flex items-start justify-between gap-3">
            <div class="flex items-center gap-2.5 min-w-0">
              <span
                class="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded bg-white/5 ring-1 ring-white/10 text-cyan-300"
              >
                <app-icon [name]="provider.kind === 'local' ? 'server' : 'cloud'" [size]="16" />
              </span>
              <div class="min-w-0">
                <h2 class="text-sm font-semibold text-white truncate">{{ provider.label }}</h2>
                <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">
                  {{ provider.key }}
                </p>
              </div>
            </div>
            <span
              class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded ring-1"
              [ngClass]="
                provider.status === 'configured'
                  ? 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/20'
                  : 'bg-white/5 text-gray-400 ring-white/10'
              "
            >
              @if (provider.status === 'configured') {
                <app-icon name="check-circle-2" [size]="10" />
              }
              {{ provider.status }}
            </span>
          </header>

          <div class="flex flex-wrap items-center gap-1.5">
            <span
              class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded ring-1"
              [ngClass]="
                provider.kind === 'local'
                  ? 'bg-cyan-500/10 text-cyan-300 ring-cyan-500/20'
                  : 'bg-indigo-500/10 text-indigo-300 ring-indigo-500/20'
              "
            >
              {{ provider.kind }}
            </span>
            @for (model of provider.models; track model) {
              <span
                class="inline-flex items-center text-[10px] font-mono px-2 py-0.5 rounded bg-black/30 text-gray-300 ring-1 ring-white/10"
              >
                {{ model }}
              </span>
            }
          </div>

          <p class="text-[11px] text-gray-400 leading-relaxed">{{ provider.notes }}</p>
        </section>
      } @empty {
        @if (!loading() && featureEnabled() && !error()) {
          <p class="text-sm text-gray-500">No providers reported.</p>
        }
      }
    </div>
  `,
})
export class ModelPortalComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);

  readonly featureEnabled = this.workspace.modelPortalEnabled;
  readonly workspaceName = computed(
    () => this.workspace.current()?.name || this.workspace.currentSlug() || 'current workspace',
  );

  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly providers = signal<ModelProvider[]>([]);

  ngOnInit(): void {
    this.loadProviders();
  }

  loadProviders(): void {
    if (!this.featureEnabled()) {
      this.error.set(null);
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    this.api.get<ProvidersResponse>('/models/providers').subscribe({
      next: (res) => {
        this.providers.set(res?.providers ?? []);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        if (err?.status === 403) {
          this.error.set('Model portal is not available for this workspace (403).');
          return;
        }
        this.error.set(err?.error?.detail || 'Failed to load model providers');
      },
    });
  }
}
