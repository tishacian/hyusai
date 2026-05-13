import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { WorkspaceService } from '@app/core/workspace.service';
import { CONNECTORS, type ConnectorDef } from '@app/features/resources/resources.catalog';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';

@Component({
  selector: 'app-connectors-page',
  standalone: true,
  imports: [CommonModule, RouterLink, IconComponent, SectionHeaderComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-section-header
      breadcrumb="Govern"
      title="Connectors"
      icon="layers"
      [subtitle]="'Workspace-scoped connectors for ' + workspaceName() + '. Configuration and data never cross workspace boundaries.'"
    >
      <a
        routerLink="/resources"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
      >
        <app-icon name="arrow-left" [size]="14" /> Resources
      </a>
    </app-section-header>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      @for (connector of connectors(); track connector.id) {
        <article class="t-card t-elevated rounded-md p-5">
          <div class="flex items-start justify-between gap-3">
            <span class="inline-flex h-10 w-10 items-center justify-center rounded bg-brand-500/10 text-brand-200 ring-1 ring-brand-400/20">
              <app-icon [name]="connector.icon" [size]="18" />
            </span>
            <span
              class="rounded px-2 py-1 text-[10px] uppercase tracking-wider ring-1"
              [ngClass]="statusClass(connector.status)"
            >
              {{ connectorStatus(connector) }}
            </span>
          </div>

          <h2 class="mt-4 text-base font-semibold text-white">{{ connector.name }}</h2>
          <p class="mt-2 min-h-[48px] text-sm leading-6 text-gray-400">{{ connector.description }}</p>
          <p class="mt-3 font-mono text-[11px] uppercase tracking-wider text-gray-600">{{ connector.version }}</p>

          <div class="mt-5">
            @if (connector.id === 'sftp') {
              <a
                routerLink="/connectors/sftp"
                class="inline-flex w-full items-center justify-center gap-2 rounded bg-brand-500 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-400"
              >
                <app-icon name="arrow-right" [size]="14" />
                Open workspace deposit
              </a>
            } @else if (connector.id === 'institutional_calendar') {
              <a
                routerLink="/hypervisor/mission-room/agenda"
                class="inline-flex w-full items-center justify-center gap-2 rounded bg-brand-500 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-400"
              >
                <app-icon name="arrow-right" [size]="14" />
                Open agenda
              </a>
            } @else if (connector.id === 'visual_streams') {
              <a
                routerLink="/hypervisor/mission-room/monitor"
                class="inline-flex w-full items-center justify-center gap-2 rounded bg-brand-500 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-400"
              >
                <app-icon name="arrow-right" [size]="14" />
                Open situation monitor
              </a>
            } @else if (connector.id === 'sharepoint') {
              <a
                routerLink="/connectors/sharepoint"
                class="inline-flex w-full items-center justify-center gap-2 rounded bg-white/5 px-4 py-2 text-sm font-semibold text-gray-100 ring-1 ring-white/10 hover:bg-white/10"
              >
                <app-icon name="arrow-right" [size]="14" />
                Open connector
              </a>
            } @else {
              <button
                type="button"
                class="inline-flex w-full cursor-not-allowed items-center justify-center gap-2 rounded bg-white/5 px-4 py-2 text-sm font-semibold text-gray-500 ring-1 ring-white/10"
                disabled
              >
                Not configured in this workspace
              </button>
            }
          </div>
        </article>
      }
    </section>
  `,
})
export class ConnectorsPageComponent {
  private readonly workspace = inject(WorkspaceService);

  readonly workspaceName = computed(() => this.workspace.current()?.name || this.workspace.currentSlug() || 'current workspace');
  readonly connectors = computed<ConnectorDef[]>(() => {
    const workspace = this.workspace.current();
    const settings = (workspace?.settings || {}) as Record<string, any>;
    const connectorSettings = (settings['connectors'] || {}) as Record<string, any>;
    const calendar = (settings['calendar'] || {}) as Record<string, any>;
    const enabled = new Set<string>();
    if (calendar['connector_id'] === 'institutional_calendar' || connectorSettings['institutional_calendar']?.enabled) {
      enabled.add('institutional_calendar');
    }
    if (workspace?.slug === 'andritz' || connectorSettings['secure_deposit']?.enabled || connectorSettings['sftp']?.enabled) {
      enabled.add('sftp');
    }
    if (connectorSettings['sharepoint']?.enabled) {
      enabled.add('sharepoint');
    }
    const visual = (settings['visual_intelligence'] || {}) as Record<string, any>;
    if (visual['enabled'] || connectorSettings['visual_streams']?.enabled) {
      enabled.add('visual_streams');
    }
    return CONNECTORS.filter((connector) => enabled.has(connector.id));
  });

  connectorStatus(connector: ConnectorDef): string {
    if (connector.id === 'institutional_calendar') return 'connected';
    if (connector.id === 'visual_streams') return 'connected';
    return connector.status;
  }

  statusClass(status: ConnectorDef['status']): string {
    if (status === 'active') return 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/20';
    if (status === 'available') return 'bg-cyan-500/10 text-cyan-200 ring-cyan-500/20';
    return 'bg-white/5 text-gray-400 ring-white/10';
  }
}
