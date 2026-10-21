import { ChangeDetectionStrategy, Component, computed, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import { CkObjectHeaderComponent } from '@app/shared/cockpit/object-header.component';
import { NavLinkDirective } from '@app/shared/cockpit';
import { DataTableComponent } from '@app/shared/ui/data-table.component';
import { writeFailure } from '@app/shared/ui/load-state';
import { prepError } from '@app/features/orchestration/flow/flow-data-prep.vm';
import { DataService, type DatasetDto } from './data.service';
import { DataOpsApi } from './dataops.api';
import { newPrepDraft, type PrepCompilation, type PrepDraft, type PrepExecution, type PrepPreview } from './dataops.models';
import { DataPrepEditorComponent } from './data-prep-editor.component';
import {
  clearStoredDraft, executionIdFromQuery, plannedOutputKind, prepIsActive, prepPhase, preparedOutputs,
  readStoredDraft, sampleSize, writeStoredDraft,
} from './data-preparation.vm';

/**
 * Standalone data preparation (lot 6, US20 to US22). The draft lives in the
 * browser session and the execution id in the URL, so a reload finds both.
 */
@Component({
  selector: 'app-data-preparation', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CkObjectHeaderComponent, NavLinkDirective, DataTableComponent, DataPrepEditorComponent], styleUrl: './dataops-editor.scss',
  template: `
    <ck-object-header [eyebrow]="i18n.t('data.title')" [title]="i18n.t('dataops.title')" [subtitle]="i18n.t('dataops.subtitle')">
      <div actions><a class="dp-button" [navLink]="{surface: 'data'}">{{ i18n.t('data.title') }}</a></div>
    </ck-object-header>
    <main class="dp-page">
      @if (restoredAt(); as at) {
        <p class="dp-note dp-row" data-testid="prep-draft-restored">{{ i18n.t('dataops.prep.draft_restored', { time: time(at) }) }}
          <button type="button" class="dp-button" (click)="discardDraft()">{{ i18n.t('dataops.prep.draft_discard') }}</button></p>
      }
      @if (error()) { <p class="dp-error" role="alert" data-testid="prep-error">{{ error() }}</p> }
      <fieldset [disabled]="busy()" style="border: 0; padding: 0; min-width: 0"><app-data-prep-editor [value]="draft()" [datasets]="datasets()" [stepErrors]="stepErrors()" (valueChange)="change($event)" /></fieldset>
      <div class="dp-row dp-section"><button type="button" class="dp-button" [disabled]="busy()" (click)="compile()">{{ i18n.t('dataops.compile') }}</button>
        <button type="button" class="dp-button" [disabled]="busy()" (click)="preview()">{{ i18n.t('dataops.preview') }}</button>
        <button type="button" class="dp-button" [disabled]="busy() || !compiled() || active()" (click)="execute()">{{ i18n.t('dataops.execute') }}</button>
        @for (out of draft().spec.outputs; track out.port) {
          <span class="dp-note" data-testid="prep-planned-output">{{ i18n.t('dataops.prep.planned.' + planned(out.port), { name: out.name || out.port }) }}</span>
        }
      </div>
      @if (compiled(); as compiled) { <details class="dp-section"><summary>{{ i18n.t('dataops.sql') }}</summary><pre class="dp-code">{{ compiled.sql }}</pre><p class="dp-note">{{ i18n.t('dataops.fingerprint') }}: {{ compiled.fingerprint }}</p></details> }
      @if (previewCleared()) { <p class="dp-note" data-testid="prep-preview-cleared">{{ i18n.t('dataops.prep.preview_cleared') }}</p> }
      @if (sample(); as sample) { <section class="dp-section" data-testid="prep-preview">
        <p class="dp-note" data-testid="prep-sample-size">@if (size(); as size) {
          {{ size.of === null
            ? i18n.t('dataops.prep.sample_size_partial', { shown: sample.rows.length, rows: size.rows })
            : i18n.t('dataops.prep.sample_size', { shown: sample.rows.length, rows: size.rows, of: size.of }) }}
        } @else { {{ i18n.t('dataops.prep.sample_size_unknown', { shown: sample.rows.length }) }} }</p>
        <ck-data-table [columns]="sample.schema" [rows]="sample.rows" [rowCount]="sample.rows.length" [caption]="i18n.t('dataops.preview')" [maxHeight]="'400px'" /></section> }
      @if (executionLoading()) { <p class="dp-note dp-section" data-testid="prep-execution-loading" aria-busy="true">{{ i18n.t('dataops.prep.execution_loading') }}</p> }
      @if (followError()) {
        <p class="dp-error dp-row" role="alert" data-testid="prep-follow-error">{{ i18n.t(followError()) }}
          <button type="button" class="dp-button" (click)="follow()">{{ i18n.t('common.retry') }}</button></p>
      }
      @if (execution(); as execution) { <section class="dp-section" aria-live="polite" data-testid="prep-execution" [attr.data-phase]="phase()">
        <h2>{{ i18n.t('dataops.execution') }}</h2>
        <p class="dp-status"><span>{{ i18n.t('dataops.prep.phase.' + phase()) }}</span><span class="dp-note">{{ execution.id }}</span></p>
        @if (phase() === 'failed' && execution.error) { <p class="dp-error">{{ execution.error }}</p> }
        @if (phase() === 'incomplete') { <p class="dp-note" data-testid="prep-incomplete">{{ i18n.t('dataops.prep.incomplete') }}</p> }
        @if (phase() === 'cancelled' || phase() === 'timed_out' || phase() === 'failed') { <p class="dp-note">{{ i18n.t('dataops.prep.no_output') }}</p> }
        @if (active()) { <button type="button" class="dp-button" data-testid="prep-cancel" [disabled]="busy() || phase() === 'cancel_requested'" (click)="cancel()">{{ i18n.t('dataops.cancel') }}</button> }
        @if (outputs().length) { <ul class="dp-outputs">
          @for (out of outputs(); track out.datasetId) { <li data-testid="prep-output" [attr.data-kind]="out.kind">
            <a class="dp-button" [navLink]="{type: 'dataset', ref: out.datasetId}">{{ i18n.t('dataops.prep.output.' + out.kind, { name: out.name ?? out.datasetId, version: out.version ?? '?' }) }}</a>
          </li> }
        </ul> }
      </section> }
    </main>
  `,
})
export class DataPreparationComponent implements OnInit, OnDestroy {
  readonly i18n = inject(I18nService); private readonly api = inject(DataOpsApi); private readonly data = inject(DataService);
  private readonly workspace = inject(WorkspaceService); private readonly route = inject(ActivatedRoute); private readonly router = inject(Router);
  readonly draft = signal(newPrepDraft()); readonly datasets = signal<DatasetDto[]>([]); readonly compiled = signal<PrepCompilation | null>(null);
  readonly sample = signal<PrepPreview | null>(null); readonly execution = signal<PrepExecution | null>(null); readonly busy = signal(false); readonly error = signal('');
  readonly stepErrors = signal<Record<string, string>>({});
  readonly previewCleared = signal(false);
  readonly restoredAt = signal<number | null>(null);
  readonly executionLoading = signal(false);
  /** The last read of the execution failed: what is shown may be stale. */
  readonly followError = signal('');
  readonly phase = computed(() => prepPhase(this.execution()));
  readonly active = computed(() => prepIsActive(this.execution()));
  readonly outputs = computed(() => preparedOutputs(this.execution()));
  readonly size = computed(() => sampleSize(this.sample()));
  private timer: ReturnType<typeof setTimeout> | undefined; private destroyed = false;
  private requestKey = crypto.randomUUID();
  private get scope() { return this.workspace.captureRequestScope(); }
  private readonly view = new WorkspaceViewContext(this.workspace, () => this.resetScope(), () => void this.loadScope(false));
  private resetScope(): void {
    clearTimeout(this.timer);
    this.draft.set(newPrepDraft()); this.datasets.set([]); this.compiled.set(null); this.sample.set(null);
    this.execution.set(null); this.busy.set(false); this.error.set(''); this.stepErrors.set({});
    this.restoredAt.set(null); this.previewCleared.set(false); this.executionLoading.set(false); this.followError.set('');
    this.requestKey = crypto.randomUUID();
  }
  private readonly storage = sessionStore();

  async ngOnInit(): Promise<void> { await this.loadScope(true); }
  private async loadScope(resumeFromUrl: boolean): Promise<void> {
    const request = this.view.beginRequest();
    const stored = readStoredDraft(this.storage, this.scope.workspaceId);
    if (stored) { this.draft.set(stored.draft); this.restoredAt.set(stored.savedAt || null); }
    const executionId = executionIdFromQuery(this.route.snapshot.queryParamMap.get('execution'));
    if (resumeFromUrl && executionId) void this.resume(executionId);
    if (!resumeFromUrl) void this.router.navigate([], { relativeTo: this.route, queryParams: { execution: null }, queryParamsHandling: 'merge', replaceUrl: true });
    try { const [datasets] = await Promise.all([this.data.refresh(), this.api.catalog()]); if (this.view.isCurrent(request)) this.datasets.set(datasets); } catch { if (this.view.isCurrent(request)) this.error.set(this.i18n.t('dataops.error.load')); }
  }
  ngOnDestroy(): void { this.destroyed = true; this.view.destroy(); clearTimeout(this.timer); }

  change(draft: PrepDraft): void {
    this.requestKey = crypto.randomUUID(); this.draft.set(draft);
    if (this.sample()) this.previewCleared.set(true);
    this.compiled.set(null); this.sample.set(null); this.error.set(''); this.stepErrors.set({});
    writeStoredDraft(this.storage, this.scope.workspaceId, draft);
  }
  discardDraft(): void {
    clearStoredDraft(this.storage, this.scope.workspaceId);
    this.restoredAt.set(null); this.requestKey = crypto.randomUUID(); this.draft.set(newPrepDraft());
    this.compiled.set(null); this.sample.set(null); this.stepErrors.set({}); this.previewCleared.set(false);
  }
  planned(port: string): 'dataset' | 'version' { return plannedOutputKind(this.draft().spec, port); }
  time(at: number): string { return new Date(at).toLocaleTimeString(this.i18n.locale() === 'fr' ? 'fr-FR' : 'en-GB', { hour: '2-digit', minute: '2-digit' }); }

  private async action(work: (current: () => boolean) => Promise<void>): Promise<void> {
    if (this.busy()) return; this.busy.set(true); this.error.set(''); this.stepErrors.set({});
    const request = this.view.captureRequest();
    const current = () => this.view.isCurrent(request);
    try { await work(current); } catch (error) { if (current()) this.fail(error); } finally { if (current()) this.busy.set(false); }
  }
  /** A server error naming a step is shown on that step; any other stays at the top. */
  private fail(error: unknown): void {
    const { code, stepId } = prepError(error);
    const message = this.codeText(code);
    if (stepId && this.draft().spec.steps.some(step => step.id === stepId)) this.stepErrors.set({ [stepId]: message });
    else this.error.set(message);
  }
  private codeText(code: string): string {
    if (code.startsWith('dataops.')) return this.i18n.t(code);
    const key = 'dataops.error.' + code; const text = this.i18n.t(key);
    return text === key ? this.i18n.t('dataops.error.request') : text;
  }
  compile(): Promise<void> { return this.action(async current => { const result = await this.api.compile(this.draft()); if (current()) this.compiled.set(result); }); }
  preview(): Promise<void> { return this.action(async current => { this.previewCleared.set(false); const result = await this.api.preview(this.draft()); if (current()) this.sample.set(result); }); }
  execute(): Promise<void> {
    return this.action(async (current) => {
      let execution: PrepExecution;
      try { execution = await this.api.execute(this.draft(), this.requestKey); } catch (error) {
        if (!current()) return;
        // The same request key resubmits the same execution, so a retry cannot start a second one.
        if (writeFailure(error).s === 'unknown') { this.error.set(this.i18n.t('dataops.prep.execute_unknown')); return; }
        throw error;
      }
      if (!current()) return;
      this.execution.set(execution); this.followError.set('');
      void this.router.navigate([], { relativeTo: this.route, queryParams: { execution: execution.id }, queryParamsHandling: 'merge', replaceUrl: true });
      this.poll();
    });
  }
  cancel(): Promise<void> {
    return this.action(async (current) => {
      const id = this.execution()?.id; if (!id) return;
      try { const result = await this.api.cancel(id); if (!current()) return; this.execution.set(result); } catch (error) {
        if (!current()) return;
        const outcome = writeFailure(error);
        this.error.set(this.i18n.t(outcome.s === 'unknown' ? 'dataops.prep.cancel_unknown' : 'dataops.prep.cancel_failed'));
        this.follow(); return;
      }
      this.poll();
    });
  }
  /** Reads the execution again after a failed follow-up, then keeps polling while it runs. */
  follow(): void { const id = this.execution()?.id ?? executionIdFromQuery(this.route.snapshot.queryParamMap.get('execution')); if (id) void this.resume(id); }

  private async resume(id: string): Promise<void> {
    const request = this.view.captureRequest();
    clearTimeout(this.timer); this.executionLoading.set(!this.execution()); this.followError.set('');
    try {
      const result = await this.api.execution(id);
      if (!this.view.isCurrent(request)) return;
      this.execution.set(result); this.poll();
    } catch (error) {
      if (!this.view.isCurrent(request)) return;
      this.followError.set((error as { status?: number })?.status === 404 ? 'dataops.prep.execution_missing' : 'dataops.prep.follow_failed');
    } finally { if (this.view.isCurrent(request)) this.executionLoading.set(false); }
  }
  private poll(): void {
    clearTimeout(this.timer); if (this.destroyed || !this.active()) return;
    const request = this.view.captureRequest();
    this.timer = setTimeout(async () => {
      if (!this.view.isCurrent(request)) return;
      const id = this.execution()?.id; if (!id) return;
      try { const result = await this.api.execution(id); if (this.view.isCurrent(request)) { this.execution.set(result); this.followError.set(''); this.poll(); } }
      catch { if (this.view.isCurrent(request)) this.followError.set('dataops.prep.follow_failed'); }
    }, 1500);
  }
}

function sessionStore(): Storage | null {
  try { return typeof sessionStorage === 'undefined' ? null : sessionStorage; } catch { return null; }
}
