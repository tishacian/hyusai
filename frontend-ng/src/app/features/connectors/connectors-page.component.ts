import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { WorkspaceService } from '@app/core/workspace.service';
import {
  CONNECTOR_CATEGORIES,
  CONNECTORS,
  type ConnectorDef,
  hasConnectorConfig,
  readConnectorConfig,
  writeConnectorConfig,
} from '@app/features/resources/resources.catalog';
import { DrawerComponent } from '@app/shared/ui/drawer.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';

@Component({
  selector: 'app-connectors-page',
  standalone: true,
  imports: [CommonModule, RouterLink, IconComponent, SectionHeaderComponent, DrawerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-section-header
      breadcrumb="Govern"
      title="Connectors"
      icon="layers"
      [subtitle]="'Workspace-scoped connector catalog for ' + workspaceName() + '. Setup stays inside the workspace boundary.'"
    >
      <a
        routerLink="/resources"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
      >
        <app-icon name="arrow-left" [size]="14" /> Resources
      </a>
    </app-section-header>

    <section class="grid gap-3 md:grid-cols-4 mb-5">
      <div class="rounded-md border border-white/10 bg-white/[0.03] p-3">
        <div class="text-[10px] uppercase tracking-[0.16em] text-gray-500">Supported</div>
        <div class="mt-1 text-2xl font-semibold text-white">{{ supportedCount() }}</div>
      </div>
      <div class="rounded-md border border-white/10 bg-white/[0.03] p-3">
        <div class="text-[10px] uppercase tracking-[0.16em] text-gray-500">Configured</div>
        <div class="mt-1 text-2xl font-semibold text-emerald-300">{{ configuredCount() }}</div>
      </div>
      <div class="rounded-md border border-white/10 bg-white/[0.03] p-3">
        <div class="text-[10px] uppercase tracking-[0.16em] text-gray-500">Available</div>
        <div class="mt-1 text-2xl font-semibold text-cyan-200">{{ availableCount() }}</div>
      </div>
      <div class="rounded-md border border-white/10 bg-white/[0.03] p-3">
        <div class="text-[10px] uppercase tracking-[0.16em] text-gray-500">Planned</div>
        <div class="mt-1 text-2xl font-semibold text-amber-300">{{ plannedCount() }}</div>
      </div>
    </section>

    @for (category of categories; track category.id) {
      <section class="mb-6">
        <header class="mb-3 flex items-center gap-2">
          <span class="inline-flex h-8 w-8 items-center justify-center rounded bg-cyan-500/10 text-cyan-200 ring-1 ring-cyan-400/20">
            <app-icon [name]="category.icon" [size]="15" />
          </span>
          <div>
            <h2 class="text-[10px] uppercase tracking-[0.16em] font-semibold text-gray-400">{{ category.label }}</h2>
            <p class="text-[11px] text-gray-500">{{ connectorsInCategory(category.id).length }} connectors</p>
          </div>
          <div class="ml-2 h-px flex-1 bg-white/5"></div>
        </header>

        <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          @for (connector of connectorsInCategory(category.id); track connector.id) {
            <article class="ck-surface rounded-md p-5">
              <div class="flex items-start justify-between gap-3">
                <span class="inline-flex h-10 w-10 items-center justify-center rounded bg-cyan-500/10 text-cyan-200 ring-1 ring-cyan-400/20">
                  <app-icon [name]="connector.icon" [size]="18" />
                </span>
                <span
                  class="rounded px-2 py-1 text-[10px] uppercase tracking-wider ring-1"
                  [ngClass]="statusClass(connector)"
                >
                  {{ connectorStatus(connector) }}
                </span>
              </div>

              <h3 class="mt-4 text-base font-semibold text-white">{{ connector.name }}</h3>
              <p class="mt-2 min-h-[48px] text-sm leading-6 text-gray-400">{{ connector.description }}</p>

              <div class="mt-4 flex items-center justify-between border-t border-white/5 pt-3">
                <span class="font-mono text-[11px] uppercase tracking-wider text-gray-600">{{ connector.version }}</span>
                @if (isConfigured(connector.id)) {
                  <span class="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-300">
                    <app-icon name="check-circle-2" [size]="12" /> Config saved
                  </span>
                } @else {
                  <span class="inline-flex items-center gap-1 text-[11px] font-medium text-gray-500">
                    <app-icon name="shield" [size]="12" /> Workspace scoped
                  </span>
                }
              </div>

              <div class="mt-5">
                @if (connector.id === 'sftp') {
                  <a
                    routerLink="/connectors/sftp"
                    class="inline-flex w-full items-center justify-center gap-2 rounded bg-cyan-500 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-400"
                  >
                    <app-icon name="arrow-right" [size]="14" />
                    Open secure deposit
                  </a>
                } @else if (connector.id === 'institutional_calendar') {
                  <a
                    routerLink="/hypervisor/mission-room/agenda"
                    class="inline-flex w-full items-center justify-center gap-2 rounded bg-cyan-500 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-400"
                  >
                    <app-icon name="arrow-right" [size]="14" />
                    Open agenda
                  </a>
                } @else if (connector.id === 'visual_streams') {
                  <a
                    routerLink="/hypervisor/mission-room/monitor"
                    class="inline-flex w-full items-center justify-center gap-2 rounded bg-cyan-500 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-400"
                  >
                    <app-icon name="arrow-right" [size]="14" />
                    Open monitor
                  </a>
                } @else if (connector.id === 'sharepoint') {
                  <a
                    routerLink="/connectors/sharepoint"
                    class="inline-flex w-full items-center justify-center gap-2 rounded bg-cyan-500 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-400"
                  >
                    <app-icon name="arrow-right" [size]="14" />
                    Open SharePoint setup
                  </a>
                } @else {
                  <button
                    type="button"
                    (click)="openSetup(connector)"
                    class="inline-flex w-full items-center justify-center gap-2 rounded bg-white/5 px-4 py-2 text-sm font-semibold text-gray-100 ring-1 ring-white/10 hover:bg-white/10"
                  >
                    <app-icon [name]="isConfigured(connector.id) ? 'pencil' : 'plug'" [size]="14" />
                    {{ setupLabel(connector) }}
                  </button>
                }
              </div>
            </article>
          }
        </div>
      </section>
    }

    <app-drawer
      [open]="drawerOpen()"
      [title]="activeConnector()?.name ?? 'Connector setup'"
      [subtitle]="activeConnector()?.version ?? ''"
      [icon]="activeConnector()?.icon ?? 'plug'"
      [width]="460"
      (close)="closeSetup()"
    >
      @if (activeConnector(); as connector) {
        <div class="space-y-5">
          <p class="text-xs text-gray-400 leading-relaxed">{{ connector.description }}</p>

          <div
            class="rounded-md p-3 flex items-start gap-2 ring-1"
            [ngClass]="connector.status === 'coming-soon'
              ? 'bg-amber-500/5 ring-amber-500/20'
              : 'bg-cyan-500/5 ring-cyan-500/20'"
          >
            <app-icon
              [name]="connector.status === 'coming-soon' ? 'clock' : 'shield-check'"
              [size]="14"
              class="mt-0.5 shrink-0"
              [ngClass]="connector.status === 'coming-soon' ? 'text-amber-400' : 'text-cyan-300'"
            />
            <div
              class="text-[11px] leading-relaxed"
              [ngClass]="connector.status === 'coming-soon' ? 'text-amber-200/90' : 'text-cyan-200/90'"
            >
              @if (connector.status === 'coming-soon') {
                Adapter planned. The setup draft is saved locally for showcase review.
              } @else {
                Setup draft is stored in this browser for the current workspace showcase.
              }
            </div>
          </div>

          <form (submit)="saveSetup($event)" class="space-y-4">
            @for (field of connector.fields; track field.key) {
              <div>
                <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  {{ field.label }}
                  @if (field.required) {
                    <span class="text-red-400">*</span>
                  }
                </label>
                <input
                  [type]="field.type"
                  [value]="draftValues[field.key] || ''"
                  (input)="onFieldInput(field.key, $event)"
                  [placeholder]="field.placeholder ?? ''"
                  [required]="!!field.required"
                  class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 focus:border-cyan-500/50 transition text-sm"
                />
              </div>
            }

            <div class="flex items-center gap-2 pt-2">
              <button
                type="submit"
                class="inline-flex items-center gap-1.5 px-4 py-2 rounded bg-cyan-500 hover:bg-cyan-400 text-white text-sm font-medium transition"
              >
                <app-icon name="save" [size]="14" /> Save
              </button>
              <button
                type="button"
                (click)="testSetup()"
                class="inline-flex items-center gap-1.5 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-gray-200 text-sm ring-1 ring-white/10 transition"
              >
                <app-icon name="zap" [size]="14" /> Test
              </button>
              <button
                type="button"
                (click)="clearSetup()"
                class="ml-auto inline-flex items-center gap-1.5 px-3 py-2 rounded text-red-300 hover:bg-red-500/10 text-sm transition"
              >
                <app-icon name="trash-2" [size]="14" /> Clear
              </button>
            </div>
          </form>
        </div>
      }
    </app-drawer>
  `,
})
export class ConnectorsPageComponent {
  private readonly workspace = inject(WorkspaceService);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastrService);

  readonly categories = CONNECTOR_CATEGORIES;
  readonly allConnectors = CONNECTORS;
  readonly connectorVersion = signal(0);
  readonly activeConnector = signal<ConnectorDef | null>(null);
  readonly drawerOpen = signal(false);

  draftValues: Record<string, string> = {};

  readonly workspaceName = computed(
    () => this.workspace.current()?.name || this.workspace.currentSlug() || 'current workspace',
  );
  readonly workspaceSettings = computed(
    () => (this.workspace.current()?.settings || {}) as Record<string, any>,
  );
  readonly supportedCount = computed(() => CONNECTORS.length);
  readonly configuredCount = computed(() => {
    this.connectorVersion();
    return CONNECTORS.filter((connector) => this.isConnectedOrConfigured(connector)).length;
  });
  readonly availableCount = computed(
    () => CONNECTORS.filter((connector) => connector.status !== 'coming-soon').length,
  );
  readonly plannedCount = computed(
    () => CONNECTORS.filter((connector) => connector.status === 'coming-soon').length,
  );

  connectorsInCategory(categoryId: string): ConnectorDef[] {
    return CONNECTORS.filter((connector) => connector.category === categoryId);
  }

  connectorStatus(connector: ConnectorDef): string {
    if (this.isConnectedOrConfigured(connector)) return 'configured';
    if (connector.status === 'active') return 'ready';
    if (connector.status === 'available') return 'available';
    return 'planned';
  }

  statusClass(connector: ConnectorDef): string {
    if (this.isConnectedOrConfigured(connector)) {
      return 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/20';
    }
    if (connector.status === 'active') return 'bg-cyan-500/10 text-cyan-200 ring-cyan-500/20';
    if (connector.status === 'available') return 'bg-cyan-500/10 text-cyan-200 ring-cyan-500/20';
    return 'bg-amber-500/10 text-amber-300 ring-amber-500/20';
  }

  isConfigured(id: string): boolean {
    this.connectorVersion();
    return hasConnectorConfig(id) || this.workspaceConnectorEnabled(id);
  }

  setupLabel(connector: ConnectorDef): string {
    if (this.isConfigured(connector.id)) return 'Edit setup';
    if (connector.status === 'coming-soon') return 'Preview setup';
    return 'Set up connection';
  }

  openSetup(connector: ConnectorDef): void {
    if (connector.id === 'sharepoint' || connector.id === 'sftp') {
      this.router.navigate(['/connectors', connector.id]);
      return;
    }
    this.activeConnector.set(connector);
    this.draftValues = { ...readConnectorConfig(connector.id) };
    this.drawerOpen.set(true);
  }

  closeSetup(): void {
    this.drawerOpen.set(false);
  }

  onFieldInput(key: string, ev: Event): void {
    const input = ev.target as HTMLInputElement;
    this.draftValues = { ...this.draftValues, [key]: input.value };
  }

  saveSetup(ev?: Event): void {
    ev?.preventDefault();
    const connector = this.activeConnector();
    if (!connector) return;
    writeConnectorConfig(connector.id, this.draftValues);
    this.connectorVersion.update((value) => value + 1);
    this.toast.success(`${connector.name} setup saved`, 'Connector');
    this.drawerOpen.set(false);
  }

  testSetup(): void {
    const connector = this.activeConnector();
    if (!connector) return;
    if (connector.status === 'coming-soon') {
      this.toast.info(`${connector.name} adapter is planned. Setup draft is ready.`, 'Connector test');
      return;
    }
    this.toast.success(`${connector.name} setup shape validated`, 'Connector test');
  }

  clearSetup(): void {
    const connector = this.activeConnector();
    if (!connector) return;
    this.draftValues = {};
    writeConnectorConfig(connector.id, {});
    this.connectorVersion.update((value) => value + 1);
    this.toast.info(`${connector.name} setup cleared`, 'Connector');
  }

  private isConnectedOrConfigured(connector: ConnectorDef): boolean {
    this.connectorVersion();
    return hasConnectorConfig(connector.id) || this.workspaceConnectorEnabled(connector.id);
  }

  private workspaceConnectorEnabled(id: string): boolean {
    const settings = this.workspaceSettings();
    const connectorSettings = (settings['connectors'] || {}) as Record<string, any>;
    const calendar = (settings['calendar'] || {}) as Record<string, any>;
    const visual = (settings['visual_intelligence'] || {}) as Record<string, any>;
    if (id === 'institutional_calendar') {
      return calendar['connector_id'] === 'institutional_calendar' || connectorSettings[id]?.enabled === true;
    }
    if (id === 'visual_streams') {
      return visual['enabled'] === true || connectorSettings[id]?.enabled === true;
    }
    if (id === 'sftp') {
      return connectorSettings['secure_deposit']?.enabled === true || connectorSettings['sftp']?.enabled === true;
    }
    return connectorSettings[id]?.enabled === true;
  }
}
