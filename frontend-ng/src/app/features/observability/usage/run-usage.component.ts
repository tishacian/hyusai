import { ChangeDetectionStrategy, Component, OnDestroy, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { UsageApiService } from './usage-api.service';
import type { UsageCallPage, UsageSummary } from './usage.models';
import { UsageSummaryComponent } from './usage-summary.component';
import { UsageCallsComponent } from './usage-calls.component';

/** Read-only accounting for the canonical Run, shared by Run and Flow restitution. */
@Component({ selector: 'app-run-usage', standalone: true, imports: [FormsModule, UsageSummaryComponent, UsageCallsComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section [attr.aria-label]="i18n.t('observability.usage.title')" [attr.aria-busy]="loading()">
      <div class="section-heading"><h2>{{ i18n.t('observability.usage.title') }}</h2><div class="actions">
        <label>{{ i18n.t('observability.usage.scope') }} <select [ngModel]="scope()" (ngModelChange)="scope.set($event)"><option value="direct">{{ i18n.t('observability.usage.direct_run') }}</option><option value="tree">{{ i18n.t('observability.usage.run_tree') }}</option></select></label>
        <button type="button" (click)="reload()" [disabled]="loading()">{{ i18n.t('common.refresh') }}</button></div></div>
      @if (error()) { <p class="notice error" role="alert">{{ i18n.t('observability.usage.load_error') }}</p> }
      @if (loading() && !summary()) { <p class="notice" role="status">{{ i18n.t('observability.usage.loading') }}</p> }
      @if (summary(); as value) { <app-usage-summary [data]="value" /> }
      @if (calls(); as page) { <app-usage-calls [page]="page" [busy]="loading()" (pageChange)="loadPage($event)" /> }
    </section>
  `, styleUrl: './usage-shared.css' })
export class RunUsageComponent implements OnDestroy {
  readonly runId = input.required<string>();
  readonly i18n = inject(I18nService);
  private readonly api = inject(UsageApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly auth = inject(AuthStore);
  readonly summary = signal<UsageSummary | null>(null);
  readonly calls = signal<UsageCallPage | null>(null);
  readonly loading = signal(false);
  readonly error = signal(false);
  readonly scope = signal<'direct' | 'tree'>('direct');
  private controller?: AbortController;
  private generation = 0;
  private resetters: Array<() => void> = [];
  constructor() {
    effect(() => { const runId = this.runId(), scope = this.scope(); void this.load(runId, 0, scope); });
    const clear = () => { this.generation++; this.controller?.abort(); this.summary.set(null); this.calls.set(null); this.error.set(false); this.loading.set(false); };
    this.resetters.push(this.workspace.registerContextReset(clear), this.auth.registerContextReset(clear));
  }
  reload(): void { void this.load(this.runId()); }
  loadPage(offset: number): void { void this.load(this.runId(), offset); }
  private async load(runId: string, offset = 0, runScope = this.scope()): Promise<void> {
    this.controller?.abort(); const controller = this.controller = new AbortController(), generation = ++this.generation;
    this.loading.set(true); this.error.set(false);
    if (offset === 0) { this.summary.set(null); this.calls.set(null); }
    if (!runId) { this.loading.set(false); return; }
    try {
      const [summary, calls] = await Promise.all([this.api.summary({ run_id: runId, run_scope: runScope }, controller.signal), this.api.calls({ run_id: runId, run_scope: runScope, limit: 10, offset }, controller.signal)]);
      if (generation === this.generation && !controller.signal.aborted) { this.summary.set(summary); this.calls.set(calls); }
    } catch { if (generation === this.generation && !controller.signal.aborted) this.error.set(true); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  ngOnDestroy(): void { this.generation++; this.controller?.abort(); this.resetters.forEach(reset => reset()); }
}
