import { ChangeDetectionStrategy, Component, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { CkObjectHeaderComponent } from '@app/shared/cockpit/object-header.component';
import { NavLinkDirective } from '@app/shared/cockpit';
import { DataTableComponent } from '@app/shared/ui/data-table.component';
import { DataService, type DatasetDto } from './data.service';
import { DataOpsApi } from './dataops.api';
import { executionDatasets, newPrepDraft, type PrepCompilation, type PrepDraft, type PrepExecution, type PrepPreview } from './dataops.models';
import { DataPrepEditorComponent } from './data-prep-editor.component';

@Component({
  selector: 'app-data-preparation', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CkObjectHeaderComponent, NavLinkDirective, DataTableComponent, DataPrepEditorComponent], styleUrl: './dataops-editor.scss',
  template: `
    <ck-object-header [eyebrow]="i18n.t('data.title')" [title]="i18n.t('dataops.title')" [subtitle]="i18n.t('dataops.subtitle')">
      <div actions><a class="dp-button" [navLink]="{surface: 'data'}">{{ i18n.t('data.title') }}</a></div>
    </ck-object-header>
    <main class="dp-page">
      @if (error()) { <p class="dp-error" role="alert">{{ i18n.t(error()) }}</p> }
      <fieldset [disabled]="busy()" style="border: 0; padding: 0; min-width: 0"><app-data-prep-editor [value]="draft()" [datasets]="datasets()" (valueChange)="change($event)" /></fieldset>
      <div class="dp-row dp-section"><button type="button" class="dp-button" [disabled]="busy()" (click)="compile()">{{ i18n.t('dataops.compile') }}</button>
        <button type="button" class="dp-button" [disabled]="busy()" (click)="preview()">{{ i18n.t('dataops.preview') }}</button>
        <button type="button" class="dp-button" [disabled]="busy() || !compiled() || active()" (click)="execute()">{{ i18n.t('dataops.execute') }}</button>
      </div>
      @if (compiled(); as compiled) { <details class="dp-section"><summary>{{ i18n.t('dataops.sql') }}</summary><pre class="dp-code">{{ compiled.sql }}</pre><p class="dp-note">{{ i18n.t('dataops.fingerprint') }}: {{ compiled.fingerprint }}</p></details> }
      @if (sample(); as sample) { <section class="dp-section"><p class="dp-note">{{ i18n.t('dataops.sample_notice') }}</p><ck-data-table [columns]="sample.schema" [rows]="sample.rows" [rowCount]="sample.rows.length" [caption]="i18n.t('dataops.preview')" [maxHeight]="'400px'" /></section> }
      @if (execution(); as execution) { <section class="dp-section" aria-live="polite"><h2>{{ i18n.t('dataops.execution') }}</h2><p>{{ execution.id }} · {{ i18n.t('dataops.status.' + execution.status) }}</p>
        @if (execution.error) { <p class="dp-error">{{ execution.error }}</p> }
        @if (active()) { <button type="button" class="dp-button" [disabled]="busy()" (click)="cancel()">{{ i18n.t('dataops.cancel') }}</button> }
        @for (dataset of outputs(); track dataset) { <a class="dp-button" [navLink]="{type: 'dataset', ref: dataset}">{{ i18n.t('dataops.outputs') }} · {{ dataset }}</a> }
      </section> }
    </main>
  `,
})
export class DataPreparationComponent implements OnInit, OnDestroy {
  readonly i18n = inject(I18nService); private readonly api = inject(DataOpsApi); private readonly data = inject(DataService);
  readonly draft = signal(newPrepDraft()); readonly datasets = signal<DatasetDto[]>([]); readonly compiled = signal<PrepCompilation | null>(null);
  readonly sample = signal<PrepPreview | null>(null); readonly execution = signal<PrepExecution | null>(null); readonly busy = signal(false); readonly error = signal('');
  private timer: ReturnType<typeof setTimeout> | undefined; private destroyed = false;
  private requestKey = crypto.randomUUID();
  async ngOnInit(): Promise<void> { try { const [datasets] = await Promise.all([this.data.refresh(), this.api.catalog()]); if (!this.destroyed) this.datasets.set(datasets); } catch { this.error.set('dataops.error.load'); } }
  ngOnDestroy(): void { this.destroyed = true; clearTimeout(this.timer); }
  change(draft: PrepDraft): void { this.requestKey = crypto.randomUUID(); this.draft.set(draft); this.compiled.set(null); this.sample.set(null); this.error.set(''); }
  active(): boolean { return ['queued', 'running', 'pending', 'created'].includes(this.execution()?.status ?? ''); }
  outputs(): string[] { return executionDatasets(this.execution()); }
  private async action(work: () => Promise<void>): Promise<void> { if (this.busy()) return; this.busy.set(true); this.error.set(''); try { await work(); } catch (error) { this.error.set(error instanceof Error && error.message.startsWith('dataops.') ? error.message : 'dataops.error.request'); } finally { this.busy.set(false); } }
  compile(): Promise<void> { return this.action(async () => { this.compiled.set(await this.api.compile(this.draft())); }); }
  preview(): Promise<void> { return this.action(async () => { this.sample.set(await this.api.preview(this.draft())); }); }
  execute(): Promise<void> { return this.action(async () => { this.execution.set(await this.api.execute(this.draft(), this.requestKey)); this.poll(); }); }
  cancel(): Promise<void> { return this.action(async () => { const id = this.execution()?.id; if (id) this.execution.set(await this.api.cancel(id)); }); }
  private poll(): void { clearTimeout(this.timer); if (this.destroyed || !this.active()) return; this.timer = setTimeout(async () => { try { const id = this.execution()?.id; if (id) { const result = await this.api.execution(id); if (!this.destroyed) { this.execution.set(result); this.poll(); } } } catch { this.error.set('dataops.error.load'); } }, 1500); }
}
