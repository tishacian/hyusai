import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, signal, untracked } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { CkBackLinkComponent, NavLinkDirective } from '@app/shared/cockpit';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { DataTableComponent } from '@app/shared/ui/data-table.component';
import { pgFailure, pgTableKey, type PgCatalog as Catalog, type PgDescription as Description, type PgFailure, type PgPreview as Preview, type PgTable } from './postgresql.types';
import { PgTablePickerComponent } from './pg-table-picker.component';
import { DatasetDto } from '@app/features/data/data.service';

interface Config {
  id: string; values: Record<string, string>; secrets_set: Record<string, boolean>; configured: boolean;
}
interface TestResult { status: string; checked_at: string; }
/** The card an error belongs to, so it shows next to the action that failed. */
type Step = 'page' | 'connection' | 'explorer' | 'dataset';
interface Failure extends PgFailure { step: Step; retry: (() => void) | null; }
export type StepTone = 'ok' | 'warn' | 'neg' | 'neutral';
export interface StepState { tone: StepTone; label: string; }

@Component({
  selector: 'app-postgresql-connector', standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, NavLinkDirective, CkBackLinkComponent, IconComponent, SectionHeaderComponent, DataTableComponent, PgTablePickerComponent],
  templateUrl: './postgresql-connector.component.html',
  styleUrl: './postgresql-connector.component.css',
})
export class PostgresqlConnectorComponent {
  protected readonly i18n = inject(I18nService);
  protected readonly workspace = inject(WorkspaceService);
  private readonly http = inject(HttpClient);
  private epoch = 0;
  private lastScope = '';
  private selectionEpoch = 0;
  private importRequest: { signature: string; id: string } | null = null;
  private readonly base = '/api/v1/connectors/postgresql';
  protected readonly config = signal<Config | null>(null);
  protected readonly canConfigure = signal(false);
  protected readonly loading = signal(false);
  protected readonly saving = signal(false);
  protected readonly testing = signal(false);
  protected readonly discovering = signal(false);
  protected readonly reading = signal(false);
  protected readonly importing = signal(false);
  protected readonly editOpen = signal(false);
  protected readonly dirty = signal(false);
  protected readonly failure = signal<Failure | null>(null);
  protected readonly saved = signal(false);
  protected readonly testResult = signal<TestResult | null>(null);
  protected readonly catalog = signal<Catalog | null>(null);
  protected readonly description = signal<Description | null>(null);
  protected readonly selectedColumns = signal<string[]>([]);
  protected readonly preview = signal<Preview | null>(null);
  protected readonly imported = signal<DatasetDto | null>(null);
  protected readonly busy = computed(() => this.loading() || this.saving() || this.testing() || this.discovering() || this.reading() || this.importing());
  protected readonly schema = signal('');
  protected readonly table = signal('');
  protected readonly selectedKey = computed(() => this.table() ? `${this.schema()}.${this.table()}` : '');
  protected readonly supportedColumns = computed(() => this.description()?.columns.filter(c => c.supported).map(c => c.name) ?? []);
  protected readonly readable = computed(() => !!this.description() && this.selectedColumns().length > 0 && !this.dirty() && !this.busy());
  protected readonly connectionReady = computed(() => this.hasSetup() && this.canConfigure() && !this.dirty() && !this.busy());
  protected readonly importReady = computed(() => this.readable() && !!this.preview() && !!this.catalog()?.datasets_enabled && !this.imported());
  protected readonly connectionState = computed<StepState>(() => {
    const result = this.testResult();
    if (!this.hasSetup()) return { tone: 'warn', label: this.i18n.t('connectors.pg.state.to_configure') };
    if (this.dirty()) return { tone: 'warn', label: this.i18n.t('connectors.pg.state.unsaved') };
    if (result?.status === 'connected') return { tone: 'ok', label: this.i18n.t('connectors.pg.state.verified', { at: this.clock(result.checked_at) }) };
    if (result) return { tone: 'neg', label: this.i18n.t('connectors.pg.state.not_verified') };
    return { tone: 'neutral', label: this.i18n.t('connectors.pg.state.saved') };
  });
  protected readonly explorerState = computed<StepState>(() => {
    const catalog = this.catalog();
    if (!catalog) return { tone: 'neutral', label: this.i18n.t('connectors.pg.state.to_explore') };
    if (this.preview()) return { tone: 'ok', label: this.i18n.t('connectors.pg.state.previewed') };
    return { tone: 'neutral', label: this.i18n.t('connectors.pg.discovered', { count: catalog.tables.length }) };
  });
  protected readonly datasetState = computed<StepState>(() => {
    const dataset = this.imported();
    if (dataset) return { tone: 'ok', label: this.i18n.t('connectors.pg.state.created', { version: dataset.version }) };
    if (this.catalog() && !this.catalog()?.datasets_enabled) return { tone: 'warn', label: this.i18n.t('connectors.pg.state.disabled') };
    if (this.importReady()) return { tone: 'neutral', label: this.i18n.t('connectors.pg.state.ready') };
    return { tone: 'neutral', label: this.i18n.t('connectors.pg.state.preview_first') };
  });
  protected host = '';
  protected port = '5432';
  protected database = '';
  protected username = '';
  protected password = '';
  protected datasetName = '';

  constructor() {
    const destroy = inject(DestroyRef);
    destroy.onDestroy(() => { this.epoch++; });
    const unregister = this.workspace.registerContextReset(() => this.reset());
    destroy.onDestroy(unregister);
    effect(() => {
      const id = this.workspace.current()?.id;
      const context = this.workspace.contextEpoch();
      const scope = `${id}/${context}`;
      if (id && context >= 0 && scope !== this.lastScope) untracked(() => {
        this.lastScope = scope; this.reset(); void this.load();
      });
    });
  }

  private reset(): void {
    this.epoch++;
    this.clearExplorer();
    this.config.set(null); this.canConfigure.set(false); this.failure.set(null); this.saved.set(false);
    this.testResult.set(null); this.dirty.set(false); this.editOpen.set(false);
    this.host = this.database = this.username = this.password = ''; this.port = '5432';
    this.loading.set(false); this.saving.set(false); this.testing.set(false);
  }

  private clearExplorer(): void {
    this.catalog.set(null); this.schema.set(''); this.clearSelection();
    this.discovering.set(false);
  }

  private clearSelection(): void {
    this.selectionEpoch++;
    this.table.set(''); this.description.set(null); this.selectedColumns.set([]);
    this.preview.set(null); this.imported.set(null); this.importRequest = null; this.datasetName = '';
    this.reading.set(false); this.importing.set(false);
  }

  protected async load(): Promise<void> {
    const epoch = this.epoch;
    this.loading.set(true); this.failure.set(null);
    try {
      const result = await firstValueFrom(this.http.get<{ connectors: Config[]; can_configure: boolean }>('/api/v1/connectors'));
      if (epoch !== this.epoch) return;
      const config = result.connectors.find(c => c.id === 'postgresql') ?? null;
      this.config.set(config); this.canConfigure.set(result.can_configure);
      this.applyConfig(config); this.editOpen.set(!this.hasSetup());
    } catch (e) { if (epoch === this.epoch) this.fail(e, 'page', () => void this.load()); }
    finally { if (epoch === this.epoch) this.loading.set(false); }
  }

  private applyConfig(config: Config | null): void {
    this.host = config?.values['host'] ?? ''; this.port = config?.values['port'] || '5432';
    this.database = config?.values['database'] ?? ''; this.username = config?.values['username'] ?? '';
    this.password = ''; this.dirty.set(false);
  }

  private hasSetup(): boolean {
    const config = this.config();
    return !!config && ['host', 'database', 'username'].every(key => !!config.values[key]) && !!config.secrets_set['password'];
  }

  protected edited(): void {
    this.dirty.set(true); this.saved.set(false); this.testResult.set(null); this.clearExplorer(); this.failure.set(null);
  }

  protected cancelEdit(): void { this.applyConfig(this.config()); this.editOpen.set(!this.config()?.configured); }

  protected canSave(): boolean {
    return this.canConfigure() && !this.busy() && !!this.host.trim() && !!this.database.trim() && !!this.username.trim()
      && Number.isInteger(Number(this.port)) && Number(this.port) > 0 && Number(this.port) <= 65535
      && (!!this.password || !!this.config()?.secrets_set['password']);
  }

  protected async save(): Promise<void> {
    if (!this.canSave()) return;
    const epoch = this.epoch;
    const values: Record<string, string> = { host: this.host.trim(), port: this.port, database: this.database.trim(), username: this.username.trim() };
    if (this.password) values['password'] = this.password;
    this.password = ''; this.saving.set(true); this.failure.set(null); this.testResult.set(null); this.clearExplorer();
    try {
      const config = await firstValueFrom(this.http.put<Config>(this.base, { values }));
      if (epoch !== this.epoch) return;
      this.config.set(config); this.applyConfig(config); this.editOpen.set(false); this.saved.set(true);
    } catch (e) { if (epoch === this.epoch) this.fail(e, 'connection'); }
    finally { delete values['password']; if (epoch === this.epoch) this.saving.set(false); }
  }

  protected async test(): Promise<void> {
    if (!this.connectionReady()) return;
    const epoch = this.epoch;
    this.testing.set(true); this.failure.set(null); this.testResult.set(null);
    try {
      const result = await firstValueFrom(this.http.post<TestResult>(`${this.base}/test`, {}));
      if (epoch === this.epoch) this.testResult.set(result);
    } catch (e) { if (epoch === this.epoch) this.fail(e, 'connection', () => void this.test()); }
    finally { if (epoch === this.epoch) this.testing.set(false); }
  }

  protected async discover(): Promise<void> {
    if (!this.connectionReady()) return;
    const epoch = this.epoch;
    this.clearExplorer(); this.discovering.set(true); this.failure.set(null);
    try {
      const result = await firstValueFrom(this.http.get<Catalog>(`${this.base}/catalog`));
      if (epoch !== this.epoch) return;
      this.catalog.set(result);
    } catch (e) { if (epoch === this.epoch) this.fail(e, 'explorer', () => void this.discover()); }
    finally { if (epoch === this.epoch) this.discovering.set(false); }
  }

  protected pick(table: PgTable): void {
    if (this.busy() || pgTableKey(table) === this.selectedKey()) return;
    this.schema.set(table.schema); void this.chooseTable(table.name);
  }

  protected async chooseTable(value: string): Promise<void> {
    this.clearSelection(); this.table.set(value); this.failure.set(null);
    if (!value) return;
    const epoch = this.epoch, selection = this.selectionEpoch;
    this.reading.set(true);
    try {
      const result = await firstValueFrom(this.http.get<Description>(`${this.base}/table`, { params: { schema: this.schema(), table: value } }));
      if (epoch !== this.epoch || selection !== this.selectionEpoch) return;
      this.description.set(result); this.selectedColumns.set(result.columns.filter(c => c.supported).map(c => c.name));
      this.datasetName = value;
    } catch (e) { if (epoch === this.epoch && selection === this.selectionEpoch) this.fail(e, 'explorer', () => void this.chooseTable(value)); }
    finally { if (epoch === this.epoch && selection === this.selectionEpoch) this.reading.set(false); }
  }

  protected toggleColumn(name: string): void {
    this.setColumns(this.selectedColumns().includes(name) ? this.selectedColumns().filter(c => c !== name) : [...this.selectedColumns(), name]);
  }

  /** Every supported column, in table order. */
  protected selectAllColumns(): void { this.setColumns(this.supportedColumns()); }
  protected clearColumns(): void { this.setColumns([]); }

  private setColumns(columns: string[]): void {
    const order = this.supportedColumns();
    this.selectedColumns.set(order.filter(name => columns.includes(name)));
    this.preview.set(null); this.imported.set(null); this.importRequest = null; this.failure.set(null);
  }

  private selection(): Record<string, unknown> {
    return { schema: this.schema(), table: this.table(), columns: this.selectedColumns(), fingerprint: this.description()!.fingerprint };
  }

  protected async read(): Promise<void> {
    if (!this.readable()) return;
    const epoch = this.epoch, selection = this.selectionEpoch;
    this.reading.set(true); this.failure.set(null); this.preview.set(null);
    try {
      const preview = await firstValueFrom(this.http.post<Preview>(`${this.base}/preview`, { ...this.selection(), limit: 25 }));
      if (epoch === this.epoch && selection === this.selectionEpoch) this.preview.set(preview);
    } catch (e) { if (epoch === this.epoch && selection === this.selectionEpoch) this.fail(e, 'explorer', () => void this.read()); }
    finally { if (epoch === this.epoch && selection === this.selectionEpoch) this.reading.set(false); }
  }

  protected async createDataset(): Promise<void> {
    if (!this.importReady() || !this.datasetName.trim()) return;
    const epoch = this.epoch, selection = this.selectionEpoch;
    const body = { ...this.selection(), name: this.datasetName.trim() };
    const signature = JSON.stringify(body);
    if (this.importRequest?.signature !== signature) this.importRequest = { signature, id: crypto.randomUUID() };
    this.importing.set(true); this.failure.set(null);
    try {
      const result = await firstValueFrom(this.http.post<{ dataset: DatasetDto }>(`${this.base}/import`, { ...body, request_id: this.importRequest.id }));
      if (epoch === this.epoch && selection === this.selectionEpoch) this.imported.set(result.dataset);
    } catch (e) { if (epoch === this.epoch && selection === this.selectionEpoch) this.fail(e, 'dataset', () => void this.createDataset()); }
    finally { if (epoch === this.epoch && selection === this.selectionEpoch) this.importing.set(false); }
  }

  protected formattedTime(value: string): string { return new Intl.DateTimeFormat(this.i18n.locale(), { dateStyle: 'short', timeStyle: 'medium', timeZone: 'Europe/Paris' }).format(new Date(value)); }
  protected clock(value: string): string { return new Intl.DateTimeFormat(this.i18n.locale(), { timeStyle: 'short', timeZone: 'Europe/Paris' }).format(new Date(value)); }

  protected failureAt(step: Step): Failure | null {
    const failure = this.failure();
    return failure?.step === step ? failure : null;
  }

  protected retryFailure(): void {
    const retry = this.failure()?.retry;
    if (retry && !this.busy()) retry();
  }

  private fail(error: unknown, step: Step, retry: (() => void) | null = null): void {
    this.failure.set({ ...pgFailure(error), step, retry });
  }
}
