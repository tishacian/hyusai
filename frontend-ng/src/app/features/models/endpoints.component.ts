import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { CurrencyPipe, DatePipe, DecimalPipe, PercentPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { NavLinkDirective } from '@app/shared/cockpit';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { EndpointsService } from './endpoints.service';
import { Endpoint, EndpointScope, EndpointsFeatures, MLAlert, MLChannel, latencyUpperBound, measuredCost } from './endpoints.vm';

@Component({
  selector: 'app-model-endpoints', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, NavLinkDirective, DatePipe, DecimalPipe, CurrencyPipe, PercentPipe],
  template: `
    <header class="mb-5 flex flex-wrap justify-between gap-3">
      <div><h1 class="text-xl font-semibold">{{ i18n.t('models.endpoints.title') }}</h1>
        <p class="text-sm text-slate-500">{{ i18n.t('models.endpoints.description') }}</p></div>
      <a [navLink]="{ surface: 'models' }" class="ck-btn-soft p-2">{{ i18n.t('models.title') }}</a>
    </header>
    @if (error()) { <p role="alert" class="ck-surface p-3 mb-3">{{ i18n.t('models.endpoints.error') }}</p> }
    @if (features() && !features()!.enabled) {
      <p class="ck-surface p-5">{{ i18n.t('models.endpoints.disabled') }}</p>
    }
    @if (features()?.enabled) {
      <form (ngSubmit)="reload()" class="flex flex-wrap items-end gap-3 mb-4">
        <label>{{ i18n.t('models.endpoints.scope') }}
          <select name="scope" [(ngModel)]="scope" class="ck-input block">
            @for (option of features()!.scopes; track option) { <option [value]="option">{{ scopeLabel(option) }}</option> }
          </select>
        </label>
        @if (scope === 'system') {
          <label>{{ i18n.t('models.endpoints.system') }}<input name="system" [(ngModel)]="systemId" required class="ck-input block" /></label>
        }
        <label>{{ i18n.t('models.endpoints.window') }}
          <select name="period" [(ngModel)]="period" class="ck-input block">
            <option value="24h">{{ i18n.t('models.endpoints.day') }}</option>
            <option value="7d">{{ i18n.t('models.endpoints.week') }}</option>
          </select>
        </label>
        <button class="ck-btn-soft p-2" [disabled]="loading() || (scope === 'system' && !systemId.trim())">{{ i18n.t('models.list.refresh') }}</button>
      </form>
      <p class="text-xs text-slate-500 mb-3">{{ i18n.t('models.endpoints.quantiles') }}</p>
      @if (loading()) { <p role="status">{{ i18n.t('models.endpoints.loading') }}</p> }
      @if (!loading() && !items().length && !error()) { <p class="ck-surface p-5">{{ i18n.t('models.endpoints.empty') }}</p> }
      @if (items().length) {
        <div class="overflow-auto ck-surface rounded">
          <table class="w-full text-sm"><caption class="sr-only">{{ i18n.t('models.endpoints.title') }}</caption>
            <thead><tr>
              <th scope="col" class="p-3 text-left">{{ i18n.t('models.endpoints.model') }}</th>
              <th scope="col" class="p-3 text-left">{{ i18n.t('models.endpoints.traffic') }}</th>
              <th scope="col" class="p-3 text-left">{{ i18n.t('models.endpoints.latency') }}</th>
              <th scope="col" class="p-3 text-left">{{ i18n.t('models.endpoints.cost') }}</th>
              <th scope="col" class="p-3 text-left">{{ i18n.t('models.endpoints.monitoring') }}</th>
            </tr></thead>
            <tbody>@for (item of items(); track item.id) {
              <tr class="border-t align-top">
                <td class="p-3"><a [navLink]="{ leaf: 'model-doc', ref: item.id }" class="underline">{{ item.name }}</a>
                  <p>{{ i18n.t('models.endpoints.served') }} {{ item.served_version }}</p>
                  @if (scope === 'platform') { <small>{{ item.workspace_id }}</small> }
                  <details class="mt-2"><summary>{{ i18n.t('models.endpoints.keys') }} ({{ item.keys.length }})</summary>
                    @for (key of item.keys; track key.id) {
                      <p>{{ key.name }} · {{ i18n.t('models.endpoints.created') }} {{ key.created_at | date:'short' }}<br />
                        {{ i18n.t('models.endpoints.last_used') }} {{ (key.last_used_at | date:'short') || '—' }}<br />
                        {{ i18n.t('models.endpoints.expires') }} {{ (key.expires_at | date:'short') || '—' }}</p>
                    }
                    @if (item.skill_slug) { <p>{{ item.skill_slug }}</p> }
                  </details>
                </td>
                <td class="p-3"><p>{{ item.metrics[period].requests | number }} {{ i18n.t('models.endpoints.requests') }}</p>
                  <p>{{ item.metrics[period].rows | number }} {{ i18n.t('models.endpoints.rows') }}</p>
                  <p>{{ item.metrics[period].errors | number }} {{ i18n.t('models.endpoints.errors') }} · {{ (item.metrics[period].error_rate | percent:'1.0-2') || '—' }}</p>
                  <small>{{ i18n.t('models.endpoints.until') }} {{ item.metrics[period].until | date:'short' }}</small>
                </td>
                <td class="p-3"><p>{{ i18n.t('models.endpoints.p50') }} {{ latency(item.metrics[period].p50_ms) }}</p>
                  <p>{{ i18n.t('models.endpoints.p95') }} {{ latency(item.metrics[period].p95_ms) }}</p></td>
                <td class="p-3">
                  @if (cost(item.metrics[period]).value !== null) {
                    <p>{{ cost(item.metrics[period]).value | currency:'USD':'symbol':'1.2-6' }}</p>
                  } @else { <p>{{ i18n.t('models.endpoints.unknown') }}</p> }
                  @if (cost(item.metrics[period]).partial) { <p>{{ i18n.t('models.endpoints.partial') }} ({{ item.metrics[period].measured_requests }}/{{ item.metrics[period].requests }})</p> }
                  <small>{{ i18n.t('models.endpoints.tariff') }} {{ (item.metrics[period].tariff_cost_per_1000_rows_usd | currency:'USD':'symbol':'1.2-6') || '—' }} ({{ item.metrics[period].tariff_requests }}/{{ item.metrics[period].requests }})</small>
                </td>
                <td class="p-3"><p [class.text-amber-700]="item.monitor_badge === 'watch'" [class.text-red-700]="item.monitor_badge === 'alert'">{{ badgeLabel(item.monitor_badge) }}</p>
                  @if (item.last_audit) { <small>{{ item.last_audit.event }}<br />{{ item.last_audit.at | date:'short' }}</small> }
                </td>
              </tr>
            }</tbody>
          </table>
        </div>
        <nav class="flex gap-3 mt-3" [attr.aria-label]="i18n.t('models.endpoints.pagination')">
          <button class="ck-btn-soft p-2" [disabled]="offset() === 0 || loading()" (click)="page(-50)">{{ i18n.t('models.endpoints.previous') }}</button>
          <span>{{ offset() + 1 }}–{{ offset() + items().length }} / {{ total() }}</span>
          <button class="ck-btn-soft p-2" [disabled]="offset() + items().length >= total() || loading()" (click)="page(50)">{{ i18n.t('models.endpoints.next') }}</button>
        </nav>
      }
      <p class="text-xs text-slate-500 mt-4">{{ i18n.t('models.endpoints.cost_source') }}</p>
      <section class="mt-6"><h2 class="text-lg font-semibold">{{ i18n.t('models.endpoints.alerts') }}</h2>
        @if (!features()!.alerts_enabled) { <p>{{ i18n.t('models.endpoints.alerts_disabled') }}</p> }
        @for (alert of alerts(); track alert.id) {
          <article class="ck-surface p-3 mt-2 flex justify-between gap-3">
            <p><a [navLink]="{ leaf: 'model-doc', ref: alert.model_id }" class="underline">{{ eventLabel(alert.event) }}</a> · {{ alert.state }} · {{ alert.created_at | date:'short' }}</p>
            @if (!alert.acknowledged_at && features()!.can_manage_channels && scope !== 'platform') {
              <button class="ck-btn-soft p-2" [disabled]="saving()" (click)="acknowledge(alert.id)">{{ i18n.t('models.endpoints.acknowledge') }}</button>
            }
          </article>
        }
      </section>
      @if (features()!.can_manage_channels) {
        <section class="mt-6"><h2 class="text-lg font-semibold">{{ i18n.t('models.endpoints.channels') }}</h2>
          <p class="text-sm text-slate-500">{{ i18n.t('models.endpoints.channel_scope') }}</p>
          @for (channel of channels(); track channel.id) {
            <p class="flex gap-3 my-2">{{ channel.name }} · {{ channel.kind }}
              <button class="ck-btn-soft px-2" [disabled]="saving()" (click)="toggle(channel)">{{ channel.enabled ? i18n.t('models.endpoints.disable') : i18n.t('models.endpoints.enable') }}</button>
            </p>
          }
          <form class="flex flex-wrap items-end gap-3 mt-3" (ngSubmit)="createChannel()">
            <label>{{ i18n.t('models.endpoints.channel_name') }}<input name="channelName" [(ngModel)]="channelName" required maxlength="120" class="ck-input block" /></label>
            <label>{{ i18n.t('models.endpoints.channel_kind') }}<select name="kind" [(ngModel)]="channelKind" class="ck-input block"><option value="email">{{ i18n.t('models.endpoints.email') }}</option><option value="webhook">{{ i18n.t('models.endpoints.webhook') }}</option></select></label>
            @if (channelKind === 'email') { <label>{{ i18n.t('models.endpoints.destination') }}<input name="email" [(ngModel)]="email" type="email" required class="ck-input block" /></label> }
            @else {
              <label>{{ i18n.t('models.endpoints.url_ref') }}<input name="urlRef" [(ngModel)]="urlRef" required class="ck-input block" /></label>
              <label>{{ i18n.t('models.endpoints.key_ref') }}<input name="keyRef" [(ngModel)]="keyRef" required class="ck-input block" /></label>
            }
            <button class="ck-btn-soft p-2" [disabled]="saving()">{{ i18n.t('models.endpoints.add_channel') }}</button>
          </form>
          <p class="text-xs text-slate-500 mt-2">{{ i18n.t('models.endpoints.secret_hint') }}</p>
        </section>
      }
    }
  `,
})
export class EndpointsComponent implements OnInit {
  readonly i18n = inject(I18nService);
  private readonly api = inject(EndpointsService);
  readonly features = signal<EndpointsFeatures | null>(null);
  readonly items = signal<Endpoint[]>([]); readonly alerts = signal<MLAlert[]>([]); readonly channels = signal<MLChannel[]>([]);
  readonly loading = signal(false); readonly saving = signal(false); readonly error = signal(false);
  readonly total = signal(0); readonly offset = signal(0);
  scope: EndpointScope = 'workspace'; systemId = ''; period: '24h' | '7d' = '24h';
  channelName = ''; channelKind: 'email' | 'webhook' = 'email'; email = ''; urlRef = ''; keyRef = '';
  readonly latency = latencyUpperBound; readonly cost = measuredCost;
  private generation = 0;
  private readonly workspace = inject(WorkspaceService);
  private readonly destroyRef = inject(DestroyRef);
  private destroyed = false;
  constructor() {
    const unregister = this.workspace.registerContextReset(() => {
      ++this.generation; this.features.set(null); this.items.set([]); this.alerts.set([]); this.channels.set([]);
      this.total.set(0); this.offset.set(0); this.loading.set(false); this.saving.set(false); this.error.set(false);
      this.scope = 'workspace'; this.systemId = ''; this.channelName = this.email = this.urlRef = this.keyRef = '';
      queueMicrotask(() => { if (!this.destroyed) void this.ngOnInit(); });
    });
    this.destroyRef.onDestroy(() => { this.destroyed = true; ++this.generation; unregister(); });
  }
  private currentScope(): () => boolean {
    const scope = this.workspace.captureRequestScope();
    return () => !this.destroyed && this.workspace.isRequestScopeCurrent(scope);
  }
  async ngOnInit(): Promise<void> {
    const current = this.currentScope();
    try { const features = await this.api.features(); if (!current()) return;
      this.features.set(features); if (features.enabled) await this.reload(); }
    catch { if (current()) this.error.set(true); }
  }
  async reload(reset = true): Promise<void> {
    if (this.scope === 'system' && !this.systemId.trim()) return;
    const generation = ++this.generation;
    const current = this.currentScope();
    if (reset) this.offset.set(0);
    this.loading.set(true); this.error.set(false); this.items.set([]); this.alerts.set([]);
    try {
      const [endpoints, alerts, channels] = await Promise.all([
        this.api.endpoints(this.scope, this.scope === 'system' ? this.systemId.trim() : '', this.offset()),
        this.api.alerts(this.scope, this.scope === 'system' ? this.systemId.trim() : ''),
        this.features()?.can_manage_channels ? this.api.channels() : Promise.resolve({items: []}),
      ]);
      if (!current() || generation !== this.generation) return;
      this.items.set(endpoints.items); this.total.set(endpoints.total); this.alerts.set(alerts.items); this.channels.set(channels.items);
    } catch { if (current() && generation === this.generation) this.error.set(true); }
    finally { if (current() && generation === this.generation) this.loading.set(false); }
  }
  page(delta: number): void { this.offset.update(offset => Math.max(0, offset + delta)); void this.reload(false); }
  async acknowledge(id: string): Promise<void> {
    if (this.saving() || !this.features()?.can_manage_channels || this.scope === 'platform') return;
    const current = this.currentScope(); this.saving.set(true);
    try { await this.api.acknowledge(id); if (current()) await this.reload(false); }
    catch { if (current()) this.error.set(true); } finally { if (current()) this.saving.set(false); }
  }
  async toggle(channel: MLChannel): Promise<void> {
    if (this.saving() || !this.features()?.can_manage_channels) return;
    const current = this.currentScope(); const {id, ...body} = channel; this.saving.set(true);
    try { await this.api.saveChannel({...body, enabled: !channel.enabled}, id); if (current()) await this.reload(false); }
    catch { if (current()) this.error.set(true); } finally { if (current()) this.saving.set(false); }
  }
  async createChannel(): Promise<void> {
    if (this.saving() || !this.features()?.can_manage_channels) return;
    const current = this.currentScope(); this.saving.set(true); this.error.set(false);
    try {
      await this.api.saveChannel({name: this.channelName.trim(), kind: this.channelKind, enabled: true,
        destination_email: this.channelKind === 'email' ? this.email.trim() : null,
        webhook_url_ref: this.channelKind === 'webhook' ? this.urlRef.trim() : null,
        signing_key_ref: this.channelKind === 'webhook' ? this.keyRef.trim() : null});
      if (!current()) return;
      this.channelName = this.email = this.urlRef = this.keyRef = ''; await this.reload(false);
    } catch { if (current()) this.error.set(true); } finally { if (current()) this.saving.set(false); }
  }
  scopeLabel(scope: EndpointScope): string {
    return this.i18n.t(scope === 'platform' ? 'models.endpoints.platform' : scope === 'system' ? 'models.endpoints.system' : 'models.endpoints.workspace');
  }
  badgeLabel(badge: Endpoint['monitor_badge']): string {
    return this.i18n.t(badge === 'ok' ? 'models.endpoints.ok' : badge === 'watch' ? 'models.endpoints.watch' : badge === 'alert' ? 'models.endpoints.alert' : 'models.endpoints.unknown');
  }
  eventLabel(event: string): string {
    return this.i18n.t(event === 'monitor_transition' ? 'models.endpoints.transition' : event === 'monitor_failed' ? 'models.endpoints.monitor_failed' : event === 'key_expiring' ? 'models.endpoints.key_expiring' : 'models.endpoints.quota');
  }
}
