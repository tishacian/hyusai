import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { IconComponent } from '@app/shared/ui/icon.component';
import { DataTableComponent } from '@app/shared/ui/data-table.component';
import { pgFailure, pgTableKey, type PgCatalog, type PgDescription, type PgFailure, type PgPreview, type PgTable } from '@app/features/connectors/postgresql/postgresql.types';
import { PgTablePickerComponent } from '@app/features/connectors/postgresql/pg-table-picker.component';
import { CONNECTORS } from '@app/features/resources/resources.catalog';
import { FlowStore } from './flow.store';
import { FlowDataSourcesService } from './flow-data-sources.service';
import { sourceConnectorId, sourceResources, type SourceResource } from './flow-data-sources.vm';

@Component({
  selector: 'app-flow-data-source-inspector', standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NavLinkDirective, IconComponent, DataTableComponent, PgTablePickerComponent],
  styleUrl: './flow-data-source-inspector.component.scss',
  templateUrl: './flow-data-source-inspector.component.html',
})
export class FlowDataSourceInspectorComponent {
  readonly node = input.required<CanonicalFlowNode>();
  readonly locked = input(false);
  protected readonly i18n = inject(I18nService);
  protected readonly sources = inject(FlowDataSourcesService);
  private readonly store = inject(FlowStore);
  private readonly http = inject(HttpClient);
  private readonly workspace = inject(WorkspaceService);
  private epoch = 0;
  private selection = 0;
  protected readonly connectorId = computed(() => sourceConnectorId(this.node()));
  protected readonly resources = computed(() => sourceResources(this.node()));
  protected readonly database = computed(() => this.sources.connectors().find(c => c.id === this.connectorId())?.values['database'] ?? '');
  protected readonly configured = computed(() => this.sources.connectors().some(c => c.id === this.connectorId() && c.configured));
  protected readonly consumers = computed(() => this.store.nodes().filter(n => this.store.edges().some(e => e.from === this.node().id && e.to === n.id && (e.kind ?? 'data') === 'data')));
  protected readonly candidates = computed(() => this.store.nodes().filter(n => !['asset', 'source', 'sink'].includes(n.kind ?? 'task') && !this.consumers().some(c => c.id === n.id)));
  protected readonly catalog = signal<PgCatalog | null>(null);
  protected readonly description = signal<PgDescription | null>(null);
  protected readonly preview = signal<PgPreview | null>(null);
  protected readonly schema = signal('');
  protected readonly table = signal('');
  protected readonly busy = signal(false);
  protected readonly failure = signal<PgFailure | null>(null);
  protected readonly selectedKey = computed(() => this.table() ? `${this.schema()}.${this.table()}` : '');
  protected readonly resourceKeys = computed(() => this.resources().map(r => pgTableKey(r)));
  protected readonly selectedIsBound = computed(() => this.resources().some(r => r.schema === this.schema() && r.table === this.table()));
  protected readonly readable = computed(() => !this.busy() && !!this.description()?.columns.some(c => c.supported));
  private readonly inspectionScope = computed(() => `${this.node().id}/${this.connectorId()}/${this.workspace.contextEpoch()}`);

  constructor() {
    const destroy = inject(DestroyRef);
    destroy.onDestroy(() => { this.epoch++; });
    destroy.onDestroy(this.workspace.registerContextReset(() => this.reset()));
    effect(() => {
      this.inspectionScope();
      untracked(() => this.reset());
    });
  }

  protected connectorName(id: string): string { return CONNECTORS.find(def => def.id === id)?.name ?? id; }

  private reset(): void {
    this.epoch++; this.catalog.set(null); this.schema.set(''); this.clearSelection(); this.failure.set(null); this.busy.set(false);
  }

  private clearSelection(): void {
    this.selection++; this.table.set(''); this.description.set(null); this.preview.set(null); this.busy.set(false);
  }

  protected changeConnector(id: string): void {
    if (this.locked() || !this.sources.connectors().some(c => c.id === id && c.configured)) return;
    this.store.patchNode(this.node().id, { config: { connector_id: id, read_mode: id === 'postgresql' ? 'live' : 'reference', resources: [] } });
  }

  protected async discover(): Promise<void> {
    if (this.busy() || !this.sources.canInspect() || !this.configured() || this.connectorId() !== 'postgresql') return;
    this.reset(); const epoch = this.epoch; this.busy.set(true);
    try {
      const catalog = await firstValueFrom(this.http.get<PgCatalog>('/api/v1/connectors/postgresql/catalog'));
      if (epoch !== this.epoch) return;
      this.catalog.set(catalog);
    } catch (error) { if (epoch === this.epoch) this.fail(error); }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }

  protected pick(table: PgTable): void {
    if (this.busy() || pgTableKey(table) === this.selectedKey()) return;
    this.schema.set(table.schema); void this.chooseTable(table.name);
  }

  protected async chooseTable(value: string): Promise<void> {
    if (!this.sources.canInspect() || !this.catalog()) return;
    this.clearSelection(); this.table.set(value); this.failure.set(null);
    if (!value) return;
    const epoch = this.epoch, selection = this.selection; this.busy.set(true);
    try {
      const description = await firstValueFrom(this.http.get<PgDescription>('/api/v1/connectors/postgresql/table', { params: { schema: this.schema(), table: value } }));
      if (epoch === this.epoch && selection === this.selection) this.description.set(description);
    } catch (error) { if (epoch === this.epoch && selection === this.selection) this.fail(error); }
    finally { if (epoch === this.epoch && selection === this.selection) this.busy.set(false); }
  }

  protected async inspectResource(resource: SourceResource): Promise<void> {
    const scope = this.workspace.captureRequestScope(), nodeId = this.node().id;
    if (!this.catalog()) await this.discover();
    if (!this.workspace.isRequestScopeCurrent(scope) || this.node().id !== nodeId) return;
    if (!this.catalog()?.tables.some(t => t.schema === resource.schema && t.name === resource.table)) return;
    this.schema.set(resource.schema); await this.chooseTable(resource.table);
  }

  protected async read(): Promise<void> {
    if (!this.readable()) return;
    const epoch = this.epoch, selection = this.selection, description = this.description()!;
    this.busy.set(true); this.failure.set(null); this.preview.set(null);
    try {
      const preview = await firstValueFrom(this.http.post<PgPreview>('/api/v1/connectors/postgresql/preview', {
        schema: description.schema, table: description.table, fingerprint: description.fingerprint,
        columns: description.columns.filter(c => c.supported).map(c => c.name), limit: 25,
      }));
      if (epoch === this.epoch && selection === this.selection) this.preview.set(preview);
    } catch (error) { if (epoch === this.epoch && selection === this.selection) this.fail(error); }
    finally { if (epoch === this.epoch && selection === this.selection) this.busy.set(false); }
  }

  protected addResource(): void {
    if (this.locked() || !this.description() || this.selectedIsBound() || this.resources().length >= 64) return;
    this.store.updateNodeConfig(this.node().id, 'resources', [...this.resources(), { schema: this.schema(), table: this.table() }]);
  }

  protected removeResource(resource: SourceResource): void {
    if (this.locked()) return;
    this.store.updateNodeConfig(this.node().id, 'resources', this.resources().filter(r => r.schema !== resource.schema || r.table !== resource.table));
  }

  protected bindConsumer(id: string): void {
    if (this.locked() || !this.candidates().some(n => n.id === id)) return;
    this.store.connect({ from: this.node().id, to: id, from_port: 'source', kind: 'data' });
  }

  protected selectConsumer(id: string): void { this.store.setSelection(id); }
  protected time(value: string): string { return new Intl.DateTimeFormat(this.i18n.locale(), { dateStyle: 'short', timeStyle: 'medium', timeZone: 'Europe/Paris' }).format(new Date(value)); }

  private fail(error: unknown): void { this.failure.set(pgFailure(error)); }
}
