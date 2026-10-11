import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, signal, untracked } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit/nav-link.directive';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { auditCsv, auditEventKey, auditParams, appendAuditPage, type AuditFilters, type AuditLog, type AuditPage } from './audit-trail.vm';

@Component({
  selector: 'app-audit-logs',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, DatePipe, NavLinkDirective, SectionHeaderComponent, EmptyStateComponent],
  template: `
    <app-section-header [breadcrumb]="i18n.t('governance.breadcrumb')" [title]="i18n.t('governance.audit.title')"
      icon="scroll-text" [subtitle]="i18n.t('governance.audit.subtitle')">
      <button type="button" class="audit-button" (click)="exportCsv()" [disabled]="exporting() || loading() || !logs().length">
        {{ i18n.t(exporting() ? 'governance.audit.exporting' : 'governance.audit.export_csv') }}
      </button>
      <button type="button" class="audit-button" (click)="reload()">{{ i18n.t('common.refresh') }}</button>
    </app-section-header>

    <form class="audit-filters" (ngSubmit)="reload()">
      <label>{{ i18n.t('governance.audit.search.placeholder') }}
        <input name="search" type="search" [(ngModel)]="filters.search" maxlength="255" />
      </label>
      <label>{{ i18n.t('governance.audit.filter.actor') }}
        <input name="actor" [(ngModel)]="filters.actor" maxlength="255" />
      </label>
      <label>{{ i18n.t('governance.audit.filter.kind') }}
        <input name="kind" [(ngModel)]="filters.eventType" list="audit-kinds" />
        <datalist id="audit-kinds">@for (kind of kinds(); track kind) { <option [value]="kind"></option> }</datalist>
      </label>
      <label>{{ i18n.t('governance.audit.filter.since') }}
        <input name="since" type="datetime-local" [(ngModel)]="filters.since" />
      </label>
      <label>{{ i18n.t('governance.audit.filter.until') }}
        <input name="until" type="datetime-local" [(ngModel)]="filters.until" />
      </label>
      <label>{{ i18n.t('governance.audit.filter.trace') }}
        <input name="trace" [(ngModel)]="filters.trace" maxlength="36" />
      </label>
      <label>{{ i18n.t('governance.audit.column.severity') }}
        <select name="severity" [(ngModel)]="filters.severity">
          <option value="">{{ i18n.t('governance.audit.severity.all') }}</option>
          @for (severity of severities; track severity) {
            <option [value]="severity">{{ severityLabel(severity) }}</option>
          }
        </select>
      </label>
      <label class="audit-toggle">
        <input name="navigation" type="checkbox" role="switch" [(ngModel)]="filters.navigation" (ngModelChange)="reload()" />
        {{ i18n.t('governance.audit.show_navigation') }}
      </label>
      <button class="audit-button" type="submit">{{ i18n.t('governance.audit.apply') }}</button>
    </form>
    <p role="status" class="audit-status">
      {{ i18n.t(loading() ? 'governance.audit.loading' : 'governance.audit.showing', { shown: logs().length, total: total() }) }}
    </p>
    @if (error()) { <p role="alert">{{ i18n.t('governance.audit.error') }}</p> }
    <section class="ck-surface audit-table" [attr.aria-busy]="loading()">
      @if (!loading() && !logs().length && !error()) {
        <app-empty-state icon="scroll-text" [title]="i18n.t('governance.audit.empty.title')"
          [description]="i18n.t('governance.audit.empty.description')" />
      }
      @if (logs().length) {
        <div class="audit-scroll">
          <table>
            <thead><tr>
              <th scope="col">{{ i18n.t('governance.audit.column.time') }}</th>
              <th scope="col">{{ i18n.t('governance.audit.column.event') }}</th>
              <th scope="col">{{ i18n.t('governance.audit.column.actor') }}</th>
              <th scope="col">{{ i18n.t('governance.audit.column.resource') }}</th>
              <th scope="col">{{ i18n.t('governance.audit.column.severity') }}</th>
            </tr></thead>
            <tbody>@for (log of logs(); track log.id) {
              <tr>
                <td>{{ log.timestamp | date: 'dd/MM/yyyy HH:mm:ss' }}</td>
                <td><strong>{{ i18n.t(eventKey(log.event_type)) }}</strong><code>{{ log.event_type }}</code>
                  @if (log.details) { <span class="audit-details">{{ detailsText(log) }}</span> }
                </td>
                <td>{{ log.actor || '—' }}</td>
                <td>
                  <code>{{ log.trace_id || log.agent_id || '—' }}</code>
                  @if (log.run_id) {
                    <a [navLink]="{ type: 'run', ref: log.run_id, lens: 'operate' }">{{ i18n.t('governance.audit.open_run') }}</a>
                  }
                </td>
                <td>{{ severityLabel(log.severity || 'info') }}</td>
              </tr>
            }</tbody>
          </table>
        </div>
      }
      @if (nextCursor()) {
        <div class="audit-footer"><button type="button" class="audit-button" (click)="loadMore()" [disabled]="loading()">
          {{ i18n.t('governance.load_more') }}
        </button></div>
      }
    </section>
  `,
  styles: [`
    :host { display: block; color: var(--ck-fg-1); }
    .audit-filters { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; margin-bottom: 12px; }
    label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--ck-fg-2); }
    input, select, .audit-button { min-height: 36px; border: 1px solid var(--ck-stroke-2); border-radius: 6px;
      padding: 6px 10px; background: var(--ck-bg-inset); color: var(--ck-fg-1); font: inherit; }
    input { max-width: 100%; }
    .audit-button { font-size: 13px; cursor: pointer; }
    .audit-button:disabled { opacity: .5; cursor: default; }
    :is(input, select, button, a):focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 3px; }
    .audit-toggle { flex-direction: row; align-items: center; min-height: 36px; }
    .audit-toggle input { width: 18px; }
    .audit-status { font-size: 12px; color: var(--ck-fg-2); margin: 12px 0; }
    .audit-table { border-radius: 6px; overflow: hidden; }
    .audit-scroll { overflow-x: auto; }
    table { width: 100%; font-size: 13px; border-collapse: collapse; }
    th, td { padding: 12px 16px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--ck-stroke-1); }
    th { font-weight: 600; color: var(--ck-fg-2); }
    td:first-child { white-space: nowrap; }
    code { display: block; font-size: 11px; color: var(--ck-fg-2); overflow-wrap: anywhere; }
    .audit-details { display: block; font-size: 12px; color: var(--ck-fg-2); overflow-wrap: anywhere; max-width: 32rem; }
    a { display: inline-block; min-height: 24px; color: var(--ck-fg-1); text-decoration: underline; margin-top: 4px; }
    .audit-footer { display: flex; justify-content: end; padding: 12px; }
  `],
})
export class AuditLogsComponent {
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  readonly i18n = inject(I18nService);
  readonly logs = signal<AuditLog[]>([]);
  readonly total = signal(0);
  readonly nextCursor = signal<string | null>(null);
  readonly loading = signal(false);
  readonly exporting = signal(false);
  readonly error = signal(false);
  readonly kinds = signal<string[]>([]);
  readonly severities = ['info', 'warning', 'error', 'critical'];
  readonly eventKey = auditEventKey;
  filters: AuditFilters = { navigation: false, actor: '', eventType: '', since: '', until: '',
    trace: this.route.snapshot.queryParamMap.get('trace_id') || '', severity: '', search: '' };
  private applied = { ...this.filters };
  private requestId = 0;

  constructor() {
    effect(() => {
      this.workspace.current()?.slug;
      untracked(() => { this.kinds.set([]); this.reload(); });
    });
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(params => {
      const trace = params.get('trace_id') || '';
      if (trace !== this.filters.trace) { this.filters.trace = trace; this.reload(); }
    });
    this.destroyRef.onDestroy(() => { this.requestId++; });
  }

  reload(): void {
    this.applied = { ...this.filters };
    this.logs.set([]);
    this.total.set(0);
    this.nextCursor.set(null);
    void this.fetchPage();
  }

  loadMore(): void { if (!this.loading() && this.nextCursor()) void this.fetchPage(this.nextCursor()); }

  private async fetchPage(before?: string | null): Promise<void> {
    const id = ++this.requestId;
    const slug = this.workspace.current()?.slug;
    this.loading.set(true);
    this.error.set(false);
    try {
      const page: AuditPage = await firstValueFrom(this.api.get<AuditPage>('/audit', auditParams(this.applied, before), { workspaceSlug: slug }));
      if (id !== this.requestId || slug !== this.workspace.current()?.slug) return;
      this.logs.set(appendAuditPage(before ? this.logs() : [], page));
      this.total.set(page.total);
      this.nextCursor.set(page.has_more ? page.next_cursor || null : null);
      this.kinds.update(kinds => [...new Set([...kinds, ...page.logs.map(row => row.event_type)])].sort());
    } catch {
      if (id === this.requestId) this.error.set(true);
    } finally {
      if (id === this.requestId) this.loading.set(false);
    }
  }

  async exportCsv(): Promise<void> {
    if (this.exporting()) return;
    const slug = this.workspace.current()?.slug;
    const filters = { ...this.applied };
    const id = this.requestId;
    this.exporting.set(true);
    this.error.set(false);
    try {
      // ponytail: CSV assembled in memory; stream server-side for very large trails.
      let rows: AuditLog[] = [];
      let before: string | null = null;
      do {
        const page: AuditPage = await firstValueFrom(this.api.get<AuditPage>('/audit', auditParams(filters, before, 500), { workspaceSlug: slug }));
        if (slug !== this.workspace.current()?.slug || id !== this.requestId) return;
        rows = appendAuditPage(rows, page);
        before = page.has_more ? page.next_cursor || null : null;
      } while (before);
      const url = URL.createObjectURL(new Blob(['\uFEFF', auditCsv(rows)], { type: 'text/csv;charset=utf-8' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = `audit-${new Date().toISOString().slice(0, 10)}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    } catch { this.error.set(true); }
    finally { this.exporting.set(false); }
  }

  detailsText(log: AuditLog): string { return typeof log.details === 'string' ? log.details : JSON.stringify(log.details); }
  severityLabel(value: string): string {
    const key = 'governance.audit.severity.' + value;
    const label = this.i18n.t(key);
    return label === key ? value : label;
  }
}
