import {
  ChangeDetectionStrategy, Component, DestroyRef, OnChanges, OnInit,
  SimpleChanges, computed, inject, input, signal,
} from '@angular/core';
import { DatePipe } from '@angular/common';
import { I18nService } from '@app/core/i18n.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { WorkspaceService } from '@app/core/workspace.service';
import { EndpointsService } from './endpoints.service';
import type { MLAlert } from './endpoints.vm';
import { mlAlertEventKey, mlAlertStateKey, summarizeMLAlerts } from './ml-alert-inbox.vm';

@Component({
  selector: 'app-ml-alert-inbox',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, NavLinkDirective],
  styleUrl: './ml-alert-inbox.component.scss',
  template: `
    @if (enabled() || failed() || loading()) {
      <section class="ml-inbox" [class.ml-inbox--compact]="presentation()==='compact'"
        [attr.data-tone]="failed()?'unknown':summary().severe?'alert':'neutral'"
        [attr.aria-label]="i18n.t('models.alert_inbox.title')" data-testid="ml-alert-inbox">
        <header class="ml-inbox__header">
          <div class="ml-inbox__identity">
            <span class="ml-inbox__dot" aria-hidden="true"></span>
            <h2>{{i18n.t('models.alert_inbox.title')}}</h2>
            <span class="ml-inbox__scope">{{i18n.t(systemId()?'models.alert_inbox.scope_system':'models.alert_inbox.scope_workspace')}}</span>
          </div>
          <div class="ml-inbox__summary" role="status">
            @if (loading()) { <span>{{i18n.t('models.endpoints.loading')}}</span> }
            @else if (failed()) { <span>{{i18n.t('models.alert_inbox.unavailable')}}</span> }
            @else {
              <strong>{{i18n.t(summary().unread?'models.alert_inbox.unread':'models.alert_inbox.no_unread',{count:summary().unread})}}</strong>
              @if (summary().severe) { <span class="ml-inbox__severity">{{i18n.t('models.alert_inbox.severe',{count:summary().severe})}}</span> }
              @if (summary().partial) {
                <span class="ml-inbox__window-full">{{i18n.t('models.alert_inbox.window',{count:summary().loaded})}}</span>
                <span class="ml-inbox__window-short">{{i18n.t('models.alert_inbox.window_compact',{count:summary().loaded})}}</span>
              }
              @if (!alertsEnabled()) { <span>{{i18n.t('models.alert_inbox.paused')}}</span> }
            }
          </div>
          <div class="ml-inbox__actions">
            @if (failed()) { <button type="button" (click)="reload()">{{i18n.t('common.retry')}}</button> }
            @if (!loading() && !failed() && summary().unread) {
              <button type="button" data-testid="ml-alert-inbox-toggle" [attr.aria-expanded]="detailsVisible()" [attr.aria-controls]="detailId"
                (click)="expanded.set(!detailsVisible())">{{i18n.t(detailsVisible()?'models.alert_inbox.hide':'models.alert_inbox.inspect')}}</button>
            }
            <a [navLink]="{leaf:'model-endpoints'}">{{i18n.t('models.alert_inbox.open')}}</a>
          </div>
        </header>
        @if (detailsVisible() && !loading() && !failed()) {
          <div class="ml-inbox__detail" [id]="detailId" data-testid="ml-alert-inbox-details">
            <p class="ml-inbox__coverage">{{i18n.t('models.alert_inbox.coverage',{loaded:summary().loaded,total:summary().total})}}</p>
            @if (!alertsEnabled()) { <p class="ml-inbox__coverage">{{i18n.t('models.endpoints.alerts_disabled')}}</p> }
            <ol>
              @for (item of summary().items; track item.id) {
                <li [attr.data-state]="item.state">
                  <a [navLink]="{leaf:'model-doc',ref:item.model_id}">{{label(item.event)}}</a>
                  <span class="ml-inbox__state">{{stateLabel(item.state)}}</span>
                  <time [attr.datetime]="item.created_at">{{item.created_at | date:'short'}}</time>
                </li>
              }
            </ol>
            @if (summary().unread > summary().items.length) {
              <p class="ml-inbox__coverage">{{i18n.t('models.alert_inbox.more',{count:summary().unread-summary().items.length})}}</p>
            }
          </div>
        }
      </section>
    }
  `,
})
export class MLAlertInboxComponent implements OnInit, OnChanges {
  private static nextId = 0;
  readonly detailId = `ml-alert-details-${++MLAlertInboxComponent.nextId}`;
  readonly i18n = inject(I18nService);
  private readonly api = inject(EndpointsService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroyRef = inject(DestroyRef);
  readonly presentation = input<'full' | 'compact'>('full');
  /** The API scopes this to MLModel.system_id, not all Flow model bindings. */
  readonly systemId = input<string | null>(null);
  readonly enabled = signal(false);
  readonly alertsEnabled = signal(false);
  readonly loading = signal(false);
  readonly failed = signal(false);
  readonly total = signal(0);
  readonly items = signal<MLAlert[]>([]);
  readonly expanded = signal<boolean | null>(null);
  readonly summary = computed(() => summarizeMLAlerts(this.items(), this.total()));
  readonly detailsVisible = computed(() => this.expanded() ?? this.presentation() === 'full');
  private destroyed = false;
  private initialized = false;
  private generation = 0;

  constructor() {
    const unregister = this.workspace.registerContextReset(() => {
      ++this.generation;
      this.reset();
      queueMicrotask(() => { if (!this.destroyed) void this.reload(); });
    });
    this.destroyRef.onDestroy(() => { this.destroyed = true; ++this.generation; unregister(); });
  }

  ngOnInit(): Promise<void> {
    this.initialized = true;
    return this.reload();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (this.initialized && changes['systemId']) void this.reload();
  }

  async reload(): Promise<void> {
    const generation = ++this.generation;
    const scope = this.workspace.captureRequestScope();
    const systemId = this.systemId()?.trim() || '';
    const current = () => !this.destroyed && generation === this.generation
      && this.workspace.isRequestScopeCurrent(scope) && (this.systemId()?.trim() || '') === systemId;
    this.reset();
    this.loading.set(true);
    try {
      const features = await this.api.features();
      if (!current()) return;
      this.enabled.set(features.enabled);
      this.alertsEnabled.set(features.alerts_enabled === true);
      if (!features.enabled) return;
      const result = await this.api.alerts(systemId ? 'system' : 'workspace', systemId);
      if (!current()) return;
      this.total.set(result.total);
      this.items.set(result.items);
    } catch {
      if (current()) this.failed.set(true);
    } finally {
      if (current()) this.loading.set(false);
    }
  }

  private reset(): void {
    this.enabled.set(false); this.alertsEnabled.set(false); this.failed.set(false);
    this.loading.set(false); this.items.set([]); this.total.set(0); this.expanded.set(null);
  }

  label(event: string): string {
    const key = mlAlertEventKey(event);
    return key ? this.i18n.t(key) : event.replace(/_/g, ' ');
  }

  stateLabel(state: string): string {
    const key = mlAlertStateKey(state);
    return key ? this.i18n.t(key) : state.replace(/_/g, ' ');
  }
}
