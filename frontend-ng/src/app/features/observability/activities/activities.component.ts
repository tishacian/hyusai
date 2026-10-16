import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subscription, firstValueFrom } from 'rxjs';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { navigationObjectUrl, navigationSurfaceUrl } from '@app/core/navigation.catalog';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { observabilityAnchor, periodCutoffMs } from '../observability-facets';
import { ActivitySeriesComponent } from './activity-series.component';
import { ActivityApiError, ActivityApiService } from './activity-api.service';
import { activityLink, commandIsPending, mergeActivityEvents, type ActivityCommand, type ActivityDetail, type ActivityEvent, type ActivityFeatures, type ActivityPage, type ActivityScope, type PlatformOverview } from './activity.models';
import type { SseFrame, StreamState } from './activity-stream';

@Component({
  selector: 'app-activities', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, ActivitySeriesComponent],
  templateUrl: './activities.component.html', styleUrl: './activities.component.css',
})
export class ActivitiesComponent implements OnInit, OnDestroy {
  readonly i18n = inject(I18nService);
  private readonly api = inject(ActivityApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly auth = inject(AuthStore);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  readonly features = signal<ActivityFeatures | null>(null);
  readonly discovering = signal(true);
  readonly page = signal<ActivityPage | null>(null);
  readonly detail = signal<ActivityDetail | null>(null);
  readonly platform = signal<PlatformOverview | null>(null);
  readonly events = signal<ActivityEvent[]>([]);
  readonly loading = signal(false);
  readonly detailLoading = signal(false);
  readonly error = signal('');
  readonly detailError = signal('');
  readonly streamState = signal<StreamState>('disconnected');
  readonly lastSeen = signal<string | null>(null);
  readonly submitting = signal(false);
  readonly confirmCancel = signal(false);
  readonly command = signal<ActivityCommand | null>(null);
  readonly commandUncertain = signal(false);
  readonly eventMore = signal(false);
  readonly eventsLoading = signal(false);
  readonly historyMode = signal(false);
  readonly systems = signal<Array<{ id: string; name: string }>>([]);
  readonly scope = signal<ActivityScope>('workspace');
  readonly offset = signal(0);
  readonly selectedId = signal('');
  readonly stale = computed(() => this.streamState() !== 'live');
  readonly canCancel = computed(() => !!this.detail()?.capabilities.cancel && !this.stale() && !this.submitting() && !this.commandUncertain() && !(this.command() && commandIsPending(this.command()!)));
  readonly statusCounts = computed(() => Object.entries(this.page()?.aggregates.by_status ?? {}));
  systemId = ''; kind = ''; status = ''; since = '7d'; asOf = new Date().toISOString();
  private routeSubscription?: Subscription;
  private unregister?: () => void;
  private unregisterAuth?: () => void;
  private request?: AbortController;
  private selectedRequest?: AbortController;
  private stream?: AbortController;
  private discovery?: AbortController;
  private refreshTimer?: ReturnType<typeof setTimeout>;
  private platformTimer?: ReturnType<typeof setTimeout>;
  private generation = 0;
  private eventsCursor = '';
  private commandKey: { activity: string; version: number; key: string } | null = null;
  private destroyed = false;
  private detailCheckedAt = 0;

  async ngOnInit(): Promise<void> {
    this.unregister = this.workspace.registerContextReset(() => { this.reset(); queueMicrotask(() => { if (!this.destroyed) void this.discover(); }); });
    this.unregisterAuth = this.auth.registerContextReset(() => this.reset());
    this.routeSubscription = this.route.queryParamMap.subscribe(params => {
      const requestedScope = params.get('scope');
      this.systemId = params.get('systemId') || params.get('system_id') || '';
      this.scope.set(requestedScope === 'platform' ? 'platform' : this.systemId || requestedScope === 'system' ? 'system' : 'workspace');
      this.kind = params.get('kind') || ''; this.status = params.get('status') || '';
      this.since = ['24h', '7d', '30d'].includes(params.get('since') || '') ? params.get('since')! : '7d';
      this.asOf = observabilityAnchor(params.get('as_of'), this.asOf);
      this.offset.set(Math.max(0, Number(params.get('offset')) || 0));
      this.selectedId.set(params.get('activityId') || '');
      if (this.features()?.enabled) void this.reload(true);
    });
    await this.discover();
  }

  private async discover(): Promise<void> {
    this.discovery?.abort(); this.discovery = new AbortController();
    this.discovering.set(true);
    try {
      const features = await this.api.features(this.discovery.signal);
      if (this.destroyed) return;
      this.features.set(features); this.error.set('');
      if (features.enabled) { void this.loadSystems(); await this.reload(true); }
    } catch (error) {
      if (this.aborted(error)) return;
      this.features.set(null);
      this.error.set(error instanceof ActivityApiError && error.status === 404 ? 'disabled' : error instanceof ActivityApiError && [401,403].includes(error.status) ? 'forbidden' : 'load_error');
    } finally { if (!this.destroyed) this.discovering.set(false); }
  }

  private async loadSystems(): Promise<void> {
    const scope = this.workspace.captureRequestScope();
    const principal = this.auth.captureRequestScope();
    try {
      const systems = await firstValueFrom(this.canonical.listSystems({ workspaceSlug: scope.workspaceSlug, propagateErrors: true }));
      if (!this.destroyed && this.workspace.isRequestScopeCurrent(scope) && this.auth.isRequestScopeCurrent(principal)) this.systems.set(systems.map(system => ({ id: system.id, name: system.name })));
    } catch { /* An existing System deep link remains usable if discovery is unavailable. */ }
  }

  refreshAnchor(): void { this.navigate({ as_of: new Date().toISOString(), offset: null }); }
  applyFilters(): void { this.navigate({ scope: this.scope(), systemId: this.systemId || null, kind: this.kind || null, status: this.status || null, since: this.since, offset: null, activityId: null }); }
  setScope(scope: ActivityScope): void {
    if (!this.features()?.scopes.includes(scope)) return;
    this.scope.set(scope);
    if (scope !== 'system') this.systemId = '';
    this.applyFilters();
  }
  nextPage(delta: number): void { this.navigate({ offset: Math.max(0, this.offset() + delta * 25) || null, activityId: null }); }
  select(id: string): void { this.navigate({ activityId: id }); }
  closeDetail(): void { this.navigate({ activityId: null }); }
  private navigate(queryParams: Record<string, string | number | null>): void {
    void this.router.navigate([], { relativeTo: this.route, queryParams, queryParamsHandling: 'merge' });
  }

  async reload(reconnect = false): Promise<void> {
    if (!this.features()?.enabled || this.destroyed) return;
    clearTimeout(this.platformTimer); this.platformTimer = undefined;
    if (!this.features()!.scopes.includes(this.scope())) { this.error.set('forbidden'); this.page.set(null); this.platform.set(null); return; }
    if (this.scope() === 'system' && !this.systemId) { this.page.set(null); this.error.set('select_system'); return; }
    const generation = ++this.generation;
    this.request?.abort(); this.request = new AbortController();
    if (reconnect) { this.stream?.abort(); this.stream = undefined; this.detail.set(null); this.events.set([]); }
    this.loading.set(true); this.error.set('');
    try {
      if (this.scope() === 'platform') {
        this.stream?.abort(); this.stream = undefined; this.detail.set(null); this.page.set(null);
        const data = await this.api.platform(this.request.signal);
        if (generation === this.generation) {
          this.platform.set(data);
          this.platformTimer = setTimeout(() => { if (!this.destroyed) void this.reload(); }, 15000);
        }
      } else {
        this.platform.set(null);
        const days = this.since === '24h' ? 1 : this.since === '30d' ? 30 : 7;
        const data = await this.api.list({ system_id: this.systemId || undefined, kind: this.kind || undefined, status: this.status || undefined,
          since: new Date(periodCutoffMs(this.since, Date.parse(this.asOf))).toISOString(), until: this.asOf, limit: 25, offset: this.offset() }, this.request.signal);
        if (generation !== this.generation) return;
        this.page.set(data); this.lastSeen.set(new Date().toISOString());
        if (!this.stream) this.connect(data.snapshot_cursor);
        if (this.selectedId()) await this.loadDetail(this.selectedId());
      }
    } catch (error) { if (!this.aborted(error) && generation === this.generation) this.handleError(error); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }

  private connect(cursor: string): void {
    const stream = new AbortController(); this.stream = stream;
    void this.api.follow({ cursor, signal: stream.signal,
      frame: frame => { if (!stream.signal.aborted) this.onFrame(frame); },
      state: state => { if (!stream.signal.aborted) { this.streamState.set(state); if (state === 'revoked') this.revoke(); } },
      resync: () => {
        if (stream.signal.aborted) return;
        this.streamState.set('reconnecting');
        clearTimeout(this.refreshTimer); this.refreshTimer = undefined;
        // Reconnect only after the authoritative read returns its new snapshot cursor.
        void this.reload(true);
      },
      pulse: () => { if (!stream.signal.aborted) this.lastSeen.set(new Date().toISOString()); },
    });
  }

  onFrame(frame: SseFrame): void {
    if (frame.event === 'heartbeat') {
      if (this.selectedId() && Date.now() - this.detailCheckedAt > 15000 && !this.detailLoading()) void this.loadDetail(this.selectedId());
      return;
    }
    const value = JSON.parse(frame.data);
    if (frame.event === 'snapshot') return;
    if (!['activity.updated', 'activity.snapshot'].includes(frame.event)) return;
    if (!value || typeof value.activity_id !== 'string' || !Number.isInteger(value.sequence) || typeof value.id !== 'string') throw new Error('INVALID_ACTIVITY_EVENT');
    if (value.activity_id === this.selectedId() && !this.historyMode()) this.events.update(events => mergeActivityEvents(events, [value as ActivityEvent]));
    this.scheduleRefresh();
  }
  private scheduleRefresh(): void {
    if (this.refreshTimer || this.destroyed) return;
    this.refreshTimer = setTimeout(() => { this.refreshTimer = undefined; void this.reload(); }, 750);
  }

  async loadDetail(id: string): Promise<void> {
    this.selectedRequest?.abort(); this.selectedRequest = new AbortController();
    const request = this.selectedRequest;
    this.detailLoading.set(true); this.detailError.set('');
    try {
      const detail = await this.api.detail(id, request.signal);
      if (id !== this.selectedId() || request.signal.aborted) return;
      const changed = this.detail()?.id !== id;
      this.detail.set(detail);
      this.detailCheckedAt = Date.now();
      if (changed) { this.confirmCancel.set(false); this.commandKey = null; this.commandUncertain.set(false); this.historyMode.set(false); this.eventMore.set(false); }
      if (!this.historyMode()) this.events.set(mergeActivityEvents(changed ? [] : this.events(), detail.events || []));
      this.command.set(detail.commands?.[0] ?? (changed ? null : this.command()));
    } catch (error) {
      if (this.aborted(error)) return;
      if (error instanceof ActivityApiError && [401, 403].includes(error.status)) this.revoke();
      else if (error instanceof ActivityApiError && error.status === 404) { this.detail.set(null); this.events.set([]); this.command.set(null); this.confirmCancel.set(false); this.detailError.set('detail_unavailable'); }
      else this.detailError.set('detail_error');
    } finally { if (request === this.selectedRequest) this.detailLoading.set(false); }
  }

  async moreEvents(): Promise<void> {
    if (!this.selectedId() || this.eventsLoading()) return;
    const id = this.selectedId(); this.eventsLoading.set(true);
    try {
      const page = await this.api.events(id, this.eventsCursor, this.selectedRequest?.signal);
      if (id !== this.selectedId()) return;
      this.events.update(events => mergeActivityEvents(events, page.items));
      this.eventsCursor = page.next_cursor; this.eventMore.set(page.has_more);
    } catch (error) { if (!this.aborted(error)) this.detailError.set('detail_error'); }
    finally { this.eventsLoading.set(false); }
  }

  async timelineHistory(): Promise<void> {
    this.eventsCursor = ''; this.events.set([]); this.historyMode.set(true);
    await this.moreEvents();
  }
  timelineLatest(): void {
    this.historyMode.set(false); this.eventMore.set(false);
    this.events.set(mergeActivityEvents([], this.detail()?.events || []));
  }

  async cancel(): Promise<void> {
    const detail = this.detail();
    if (!detail || this.stale() || this.submitting() || (!this.canCancel() && !this.commandUncertain())) return;
    if (!this.commandKey || this.commandKey.activity !== detail.id) this.commandKey = { activity: detail.id, version: detail.version, key: crypto.randomUUID() };
    this.submitting.set(true); this.detailError.set('');
    try {
      const command = await this.api.command(detail.id, this.commandKey.version, this.commandKey.key, this.selectedRequest?.signal);
      if (this.selectedId() !== detail.id) return;
      this.command.set(command); this.commandUncertain.set(false); this.confirmCancel.set(false);
      await this.loadDetail(detail.id);
    } catch (error) {
      if (this.aborted(error)) return;
      if (error instanceof ActivityApiError && error.status === 409) { this.commandKey = null; this.confirmCancel.set(false); this.detailError.set('conflict'); await this.loadDetail(detail.id); this.detailError.set('conflict'); }
      else if (error instanceof ActivityApiError && [401, 403, 404].includes(error.status)) this.revoke();
      else { this.commandUncertain.set(true); this.detailError.set('command_uncertain'); }
    } finally { this.submitting.set(false); }
  }

  private handleError(error: unknown): void {
    if (error instanceof ActivityApiError && [401, 403, 404].includes(error.status)) this.revoke();
    else this.error.set('load_error');
  }
  private revoke(): void {
    clearTimeout(this.platformTimer); this.platformTimer = undefined;
    this.stream?.abort(); this.stream = undefined; this.request?.abort(); this.selectedRequest?.abort();
    this.page.set(null); this.detail.set(null); this.platform.set(null); this.events.set([]); this.command.set(null);
    this.commandKey = null; this.commandUncertain.set(false);
    this.error.set('forbidden'); this.streamState.set('revoked'); this.confirmCancel.set(false);
  }
  private aborted(error: unknown): boolean { return error instanceof Error && error.name === 'AbortError'; }
  private reset(): void {
    this.generation++; this.request?.abort(); this.selectedRequest?.abort(); this.stream?.abort(); this.discovery?.abort();
    this.stream = undefined; clearTimeout(this.refreshTimer); this.refreshTimer = undefined;
    clearTimeout(this.platformTimer); this.platformTimer = undefined;
    this.features.set(null); this.page.set(null); this.detail.set(null); this.platform.set(null); this.events.set([]); this.command.set(null);
    this.systems.set([]);
    this.discovering.set(true);
    this.error.set(''); this.detailError.set(''); this.streamState.set('disconnected'); this.commandKey = null;
  }
  ngOnDestroy(): void { this.destroyed = true; this.reset(); this.routeSubscription?.unsubscribe(); this.unregister?.(); this.unregisterAuth?.(); }
  systemListed(id: string): boolean { return this.systems().some(system => system.id === id); }
  safeLink(link: Parameters<typeof activityLink>[0]) { const href = activityLink(link); return href ? this.router.parseUrl(href) : null; }
  readonly objectHref = navigationObjectUrl;
  readonly observabilityUrl = navigationSurfaceUrl('observability');
  cost(value: NonNullable<ReturnType<typeof this.detail>>['measurements']): string { if (!value.cost_known) return this.t('unknown'); if (value.cost_amount != null && value.currency) return this.number(value.cost_amount, ' ' + value.currency); return this.number(value.infrastructure_cost_usd ?? value.provider_cost_usd, ' USD'); }
  label(group: string, value: string): string {
    if (group === 'cost_basis' && ['provider_measured','catalogue_calculated','unknown'].includes(value)) return this.i18n.t('observability.flow.cost_basis.' + value);
    const key = `observability.activities.${group}.${value}`;
    const label = this.i18n.t(key);
    return label === key ? value : label;
  }
  t(key: string, params?: Record<string, string | number>): string { return this.i18n.t(`observability.activities.${key}`, params); }
  date(value: string | null): string { return value ? new Date(value).toLocaleString(this.i18n.locale()) : '—'; }
  number(value: unknown, suffix = ''): string { return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString(this.i18n.locale(), { maximumFractionDigits: 3 }) + suffix : this.t('unknown'); }
  entries(value: Record<string, number>): [string, number][] { return Object.entries(value); }
  coverage(value: string | boolean | null | undefined): string { return value == null ? this.t('unknown') : this.label('coverage', String(value)); }
}
