import { Injectable, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { FlowCollectionsService } from './flow-collections.service';
import { collectionSourceItems, connectorSourceItems, type ConnectorSourceConfig } from './flow-data-sources.vm';

@Injectable({ providedIn: 'root' })
export class FlowDataSourcesService {
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly collections = inject(FlowCollectionsService);
  private request: Subscription | null = null;
  readonly connectors = signal<ConnectorSourceConfig[]>([]);
  readonly canInspect = signal(false);
  readonly state = signal<'loading' | 'loaded' | 'error'>('loading');
  readonly collectionState = this.collections.state;
  readonly items = computed(() => [
    ...connectorSourceItems(this.connectors()), ...collectionSourceItems(this.collections.collections()),
  ]);

  constructor() {
    this.load();
    this.workspace.registerContextReset(transition => {
      this.request?.unsubscribe(); this.connectors.set([]); this.canInspect.set(false); this.state.set('loading');
      queueMicrotask(() => { if (this.workspace.contextEpoch() === transition.nextEpoch) this.load(); });
    });
  }

  retry(): void { this.collections.retry(); this.load(); }

  private load(): void {
    const scope = this.workspace.captureRequestScope();
    this.request?.unsubscribe(); this.state.set('loading'); this.collections.ensureLoaded();
    this.request = this.api.get<{ connectors: ConnectorSourceConfig[]; can_configure: boolean }>('/connectors').subscribe({
      next: response => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        // A narrow projection deliberately discards secrets_set and any
        // future credential envelopes the setup API may expose.
        this.connectors.set((response.connectors ?? []).map(row => ({
          id: row.id, configured: row.configured, values: { database: row.values?.['database'] ?? '' },
        })));
        this.canInspect.set(response.can_configure === true); this.state.set('loaded');
      },
      error: () => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.connectors.set([]); this.canInspect.set(false); this.state.set('error');
      },
    });
  }
}
