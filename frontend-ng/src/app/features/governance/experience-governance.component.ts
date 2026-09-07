import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { Subscription, catchError, forkJoin, map, of } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import { NavLinkDirective, PageFrameComponent } from '@app/shared/cockpit';
import {
  StudioApiService,
  type StudioDrift,
} from '../experience/studio/studio-api.service';
import type { StudioExperience } from '../experience/studio/studio-model';
import {
  driftCountFor,
  experienceGovernanceChannel,
  filterExperienceAudit,
  filterExperienceInventory,
  projectAudience,
  type ExperienceAuditRow,
  type ExperienceGovernanceChannel,
  type ExperienceGovernanceDeployment,
  type ExperienceGovernanceRow,
} from './experience-governance.models';

interface ExperienceAuditResponse {
  logs?: ExperienceAuditRow[];
  total?: number;
}

@Component({
  selector: 'app-experience-governance',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, NavLinkDirective, EmptyStateComponent, IconComponent, PageFrameComponent],
  template: `
    <ck-page-frame
      [eyebrow]="i18n.t('governance.experience.eyebrow')"
      [title]="i18n.t('governance.experience.title')"
      [description]="i18n.t('governance.experience.description')"
    >
      <button
        actions
        type="button"
        class="xp-gov-button"
        (click)="load()"
        [disabled]="loading()"
      >
        <app-icon name="refresh-cw" [size]="13" [class.animate-spin]="loading()" />
        {{ i18n.t('common.refresh') }}
      </button>

      <div class="xp-gov-stack" aria-live="polite">
        @if (inventoryError() && auditError() && driftError()) {
          <div class="xp-gov-alert" role="alert">{{ i18n.t('governance.experience.error.all') }}</div>
        }

        <dl class="xp-gov-summary" [attr.aria-label]="i18n.t('governance.experience.summary.aria')">
          <div>
            <dt>{{ i18n.t('governance.experience.summary.apps') }}</dt>
            <dd>{{ applications().length }}</dd>
          </div>
          <div>
            <dt>{{ i18n.t('governance.experience.summary.live') }}</dt>
            <dd>{{ countChannel('live') }}</dd>
          </div>
          <div>
            <dt>{{ i18n.t('governance.experience.summary.pilot') }}</dt>
            <dd>{{ countChannel('pilot') }}</dd>
          </div>
          <div>
            <dt>{{ i18n.t('governance.experience.summary.drift') }}</dt>
            <dd>{{ driftState() === 'ready' ? drifts().length : '—' }}</dd>
          </div>
        </dl>

        <section class="xp-gov-panel" aria-labelledby="xp-governance-inventory-title">
          <header class="xp-gov-panel-head">
            <div>
              <h2 id="xp-governance-inventory-title">{{ i18n.t('governance.experience.inventory.title') }}</h2>
              <p>{{ i18n.t('governance.experience.inventory.description') }}</p>
            </div>
            <div class="xp-gov-filters">
              <label>
                <span>{{ i18n.t('governance.experience.filter.search') }}</span>
                <input
                  type="search"
                  [ngModel]="inventoryQuery()"
                  (ngModelChange)="inventoryQuery.set($event)"
                  [placeholder]="i18n.t('governance.experience.filter.search.placeholder')"
                />
              </label>
              <label>
                <span>{{ i18n.t('governance.experience.filter.channel') }}</span>
                <select
                  [ngModel]="channelFilter()"
                  (ngModelChange)="setChannelFilter($event)"
                >
                  @for (channel of channels; track channel) {
                    <option [value]="channel">{{ channelLabel(channel) }}</option>
                  }
                </select>
              </label>
            </div>
          </header>

          @if (inventoryError()) {
            <div class="xp-gov-alert" role="alert">{{ i18n.t('governance.experience.error.inventory') }}</div>
          } @else {
            @if (driftError()) {
              <div class="xp-gov-alert" role="alert">{{ i18n.t('governance.experience.error.drift') }}</div>
            }
          }
          @if (!inventoryError() && loading() && applications().length === 0) {
            <p class="xp-gov-muted">{{ i18n.t('common.loading') }}</p>
          } @else if (!inventoryError() && filteredApplications().length === 0) {
            <app-empty-state
              icon="layers"
              [title]="i18n.t('governance.experience.inventory.empty.title')"
              [description]="i18n.t('governance.experience.inventory.empty.description')"
            />
          } @else if (!inventoryError()) {
            <div class="xp-gov-table-wrap">
              <table class="xp-gov-table">
                <caption class="sr-only">{{ i18n.t('governance.experience.inventory.title') }}</caption>
                <thead>
                  <tr>
                    <th scope="col">{{ i18n.t('governance.experience.column.application') }}</th>
                    <th scope="col">{{ i18n.t('governance.experience.column.release') }}</th>
                    <th scope="col">{{ i18n.t('governance.experience.column.channels') }}</th>
                    <th scope="col">{{ i18n.t('governance.experience.column.audiences') }}</th>
                    <th scope="col">{{ i18n.t('governance.experience.column.health') }}</th>
                    <th scope="col"><span class="sr-only">{{ i18n.t('governance.experience.column.actions') }}</span></th>
                  </tr>
                </thead>
                <tbody>
                  @for (app of filteredApplications(); track app.id) {
                    <tr>
                      <td>
                        <strong>{{ app.name }}</strong>
                        <span class="xp-gov-code">/work/{{ app.slug }}</span>
                      </td>
                      <td>
                        @if (app.latest_release_number) {
                          <span class="xp-gov-release">R{{ app.latest_release_number }}</span>
                        } @else {
                          <span class="xp-gov-muted">{{ i18n.t('governance.experience.release.none') }}</span>
                        }
                      </td>
                      <td>
                        @for (deployment of deploymentsFor(app); track deployment.channel) {
                          <div class="xp-gov-channel-line">
                            <span class="xp-gov-tag" [attr.data-tone]="deployment.channel">
                              {{ channelLabel(deployment.channel) }}
                            </span>
                            <span class="xp-gov-code">{{ shortId(deployment.release_id) }}</span>
                          </div>
                        } @empty {
                          <span class="xp-gov-tag">{{ channelLabel('draft') }}</span>
                        }
                      </td>
                      <td>
                        @for (deployment of deploymentsFor(app); track deployment.channel) {
                          <div class="xp-gov-audience">
                            <span>{{ channelLabel(deployment.channel) }}</span>
                            <strong>{{ audienceText(deployment.audience) }}</strong>
                          </div>
                        } @empty {
                          <span class="xp-gov-muted">{{ i18n.t('governance.experience.audience.not_deployed') }}</span>
                        }
                      </td>
                      <td>
                        @if (driftState() !== 'ready') {
                          <span class="xp-gov-muted">
                            {{ i18n.t(driftState() === 'error'
                              ? 'common.perspective.state.unavailable'
                              : 'common.loading') }}
                          </span>
                        } @else if (driftCount(app) > 0) {
                          <details>
                            <summary class="xp-gov-drift">
                              {{ i18n.t('governance.experience.drift.count', { count: driftCount(app) }) }}
                            </summary>
                            <ul class="xp-gov-reasons">
                              @for (reason of driftReasons(app); track reason) { <li>{{ reason }}</li> }
                            </ul>
                          </details>
                        } @else {
                          <span class="xp-gov-ok">{{ i18n.t('governance.experience.drift.none') }}</span>
                        }
                      </td>
                      <td>
                        <div class="xp-gov-actions">
                          @if (workspace.experienceStudioV1Enabled()) {
                            <a [navLink]="{ leaf: 'create-app-edit', ref: app.id }">
                              {{ i18n.t(workspace.isAdmin() && driftCount(app) > 0
                                ? 'governance.experience.action.repair'
                                : 'governance.experience.action.inspect') }}
                            </a>
                          }
                          <a [routerLink]="navigation.surfaceUrlTree('runs')" [queryParams]="{ origin: originFor(app) }">
                            {{ i18n.t('governance.experience.action.runs') }}
                          </a>
                        </div>
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          }
        </section>

        <section class="xp-gov-panel" aria-labelledby="xp-governance-journal-title">
          <header class="xp-gov-panel-head">
            <div>
              <h2 id="xp-governance-journal-title">{{ i18n.t('governance.experience.journal.title') }}</h2>
              <p>{{ i18n.t('governance.experience.journal.description') }}</p>
            </div>
            <div class="xp-gov-filters xp-gov-filters-journal">
              <label>
                <span>{{ i18n.t('governance.experience.filter.application') }}</span>
                <select [ngModel]="auditApplication()" (ngModelChange)="auditApplication.set($event)">
                  <option value="">{{ i18n.t('governance.experience.filter.application.all') }}</option>
                  @for (app of applications(); track app.id) { <option [value]="app.id">{{ app.name }}</option> }
                </select>
              </label>
              <label>
                <span>{{ i18n.t('governance.experience.filter.event') }}</span>
                <select [ngModel]="auditEvent()" (ngModelChange)="auditEvent.set($event)">
                  <option value="">{{ i18n.t('governance.experience.filter.event.all') }}</option>
                  @for (event of eventTypes(); track event) { <option [value]="event">{{ eventLabel(event) }}</option> }
                </select>
              </label>
              <label>
                <span>{{ i18n.t('governance.experience.filter.journal_search') }}</span>
                <input
                  type="search"
                  [ngModel]="auditQuery()"
                  (ngModelChange)="auditQuery.set($event)"
                  [placeholder]="i18n.t('governance.experience.filter.journal_search.placeholder')"
                />
              </label>
            </div>
          </header>

          @if (auditError()) {
            <div class="xp-gov-alert" role="alert">{{ i18n.t('governance.experience.error.audit') }}</div>
          } @else if (!loading() && filteredAudit().length === 0) {
            <app-empty-state
              icon="activity"
              [title]="i18n.t('governance.experience.journal.empty.title')"
              [description]="i18n.t('governance.experience.journal.empty.description')"
            />
          } @else {
            <div class="xp-gov-table-wrap">
              <table class="xp-gov-table xp-gov-audit-table">
                <caption class="sr-only">{{ i18n.t('governance.experience.journal.title') }}</caption>
                <thead>
                  <tr>
                    <th scope="col">{{ i18n.t('governance.audit.column.time') }}</th>
                    <th scope="col">{{ i18n.t('governance.audit.column.event') }}</th>
                    <th scope="col">{{ i18n.t('governance.experience.column.application') }}</th>
                    <th scope="col">{{ i18n.t('governance.audit.column.actor') }}</th>
                    <th scope="col">{{ i18n.t('governance.experience.column.details') }}</th>
                  </tr>
                </thead>
                <tbody>
                  @for (log of filteredAudit(); track log.id) {
                    <tr>
                      <td><time [attr.datetime]="log.timestamp || null">{{ formatTime(log.timestamp) }}</time></td>
                      <td><span class="xp-gov-event">{{ eventLabel(log.event_type) }}</span></td>
                      <td>{{ applicationName(log) }}</td>
                      <td>{{ log.actor || '—' }}</td>
                      <td>
                        <span>{{ eventSummary(log) }}</span>
                        @if (hasDetails(log)) {
                          <details class="xp-gov-raw">
                            <summary>{{ i18n.t('governance.experience.details.open') }}</summary>
                            <pre>{{ formatDetails(log) }}</pre>
                          </details>
                        }
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          }
        </section>
      </div>
    </ck-page-frame>
  `,
  styles: [`
    .xp-gov-stack { display: grid; gap: 18px; }
    .xp-gov-button, .xp-gov-actions a {
      min-height: 32px; display: inline-flex; align-items: center; gap: 7px;
      padding: 6px 10px; border: 1px solid var(--ck-stroke-2); border-radius: 4px;
      background: var(--ck-bg-panel); color: var(--ck-fg-2); font: 600 11px var(--ck-font-mono);
      text-decoration: none;
    }
    .xp-gov-button:hover:not(:disabled), .xp-gov-actions a:hover { border-color: var(--ck-stroke-3); color: var(--ck-fg-1); }
    .xp-gov-button:disabled { opacity: .55; }
    .xp-gov-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 0; }
    .xp-gov-summary > div, .xp-gov-panel { border: 1px solid var(--ck-stroke-2); border-radius: 5px; background: var(--ck-bg-panel); }
    .xp-gov-summary > div { padding: 14px 16px; }
    .xp-gov-summary dt { color: var(--ck-fg-4); font: 600 10px var(--ck-font-mono); letter-spacing: .1em; text-transform: uppercase; }
    .xp-gov-summary dd { margin: 7px 0 0; color: var(--ck-fg-1); font: 500 24px var(--ck-font-mono); }
    .xp-gov-panel { min-width: 0; overflow: hidden; }
    .xp-gov-panel-head { display: flex; align-items: end; justify-content: space-between; gap: 18px; padding: 18px 20px; border-bottom: 1px solid var(--ck-stroke-2); }
    .xp-gov-panel h2 { margin: 0; color: var(--ck-fg-1); font-size: 17px; font-weight: 600; }
    .xp-gov-panel p { margin: 5px 0 0; color: var(--ck-fg-3); font-size: 12px; }
    .xp-gov-filters { display: flex; flex-wrap: wrap; align-items: end; justify-content: end; gap: 8px; }
    .xp-gov-filters label { display: grid; gap: 4px; color: var(--ck-fg-4); font: 600 9px var(--ck-font-mono); letter-spacing: .08em; text-transform: uppercase; }
    .xp-gov-filters input, .xp-gov-filters select {
      min-width: 150px; height: 32px; padding: 0 9px; border: 1px solid var(--ck-stroke-2); border-radius: 4px;
      background: var(--ck-bg-inset); color: var(--ck-fg-1); font: 11px var(--ck-font-mono); text-transform: none; letter-spacing: normal;
    }
    .xp-gov-filters-journal input { min-width: 210px; }
    .xp-gov-table-wrap { overflow-x: auto; }
    .xp-gov-table { width: 100%; min-width: 920px; border-collapse: collapse; }
    .xp-gov-table th { padding: 10px 14px; border-bottom: 1px solid var(--ck-stroke-2); color: var(--ck-fg-4); font: 600 9px var(--ck-font-mono); letter-spacing: .09em; text-align: left; text-transform: uppercase; }
    .xp-gov-table td { padding: 13px 14px; border-bottom: 1px solid var(--ck-stroke-1); color: var(--ck-fg-2); font-size: 12px; vertical-align: top; }
    .xp-gov-table tbody tr:last-child td { border-bottom: 0; }
    .xp-gov-table strong { color: var(--ck-fg-1); font-weight: 600; }
    .xp-gov-code { display: block; margin-top: 4px; color: var(--ck-fg-4); font: 10px var(--ck-font-mono); }
    .xp-gov-release, .xp-gov-event { color: var(--ck-signal-cool); font: 600 11px var(--ck-font-mono); }
    .xp-gov-channel-line, .xp-gov-audience { display: flex; align-items: center; gap: 7px; }
    .xp-gov-channel-line + .xp-gov-channel-line, .xp-gov-audience + .xp-gov-audience { margin-top: 6px; }
    .xp-gov-audience > span { min-width: 45px; color: var(--ck-fg-4); font: 9px var(--ck-font-mono); text-transform: uppercase; }
    .xp-gov-tag { display: inline-flex; padding: 2px 6px; border: 1px solid var(--ck-stroke-2); border-radius: 999px; color: var(--ck-fg-3); font: 600 9px var(--ck-font-mono); text-transform: uppercase; }
    .xp-gov-tag[data-tone='live'] { border-color: color-mix(in srgb, var(--ck-signal-pos) 45%, transparent); color: var(--ck-signal-pos); }
    .xp-gov-tag[data-tone='pilot'] { border-color: color-mix(in srgb, var(--ck-signal-warn) 45%, transparent); color: var(--ck-signal-warn); }
    .xp-gov-ok { color: var(--ck-signal-pos); }
    .xp-gov-drift { color: var(--ck-signal-warn); cursor: pointer; }
    .xp-gov-reasons { max-width: 300px; margin: 7px 0 0; padding-left: 16px; color: var(--ck-fg-3); }
    .xp-gov-actions { display: flex; flex-wrap: wrap; gap: 6px; min-width: 150px; }
    .xp-gov-actions a { min-height: 28px; padding: 4px 8px; font-size: 10px; }
    .xp-gov-alert { margin: 14px 18px; padding: 10px 12px; border: 1px solid color-mix(in srgb, var(--ck-signal-neg) 45%, transparent); border-radius: 4px; color: var(--ck-signal-neg); background: color-mix(in srgb, var(--ck-signal-neg) 7%, transparent); }
    .xp-gov-muted { color: var(--ck-fg-4); }
    .xp-gov-panel > .xp-gov-muted { padding: 18px 20px; }
    .xp-gov-audit-table time { white-space: nowrap; color: var(--ck-fg-3); font: 10px var(--ck-font-mono); }
    .xp-gov-raw { margin-top: 5px; }
    .xp-gov-raw summary { color: var(--ck-fg-4); cursor: pointer; font: 10px var(--ck-font-mono); }
    .xp-gov-raw pre { max-width: 460px; overflow: auto; margin: 6px 0 0; padding: 8px; border-radius: 3px; background: var(--ck-bg-inset); color: var(--ck-fg-3); font: 10px/1.5 var(--ck-font-mono); white-space: pre-wrap; }
    @media (max-width: 860px) {
      .xp-gov-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .xp-gov-panel-head { align-items: stretch; flex-direction: column; }
      .xp-gov-filters { justify-content: stretch; }
      .xp-gov-filters label, .xp-gov-filters input, .xp-gov-filters select { min-width: 0; flex: 1 1 170px; }
    }
  `],
})
export class ExperienceGovernanceComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly studio = inject(StudioApiService);
  readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);
  protected readonly navigation = inject(ZoomContextService);
  private requestSubscription: Subscription | null = null;
  private readonly workspaceView = new WorkspaceViewContext(
    this.workspace,
    () => this.resetView(),
    () => this.load(),
  );

  readonly channels: readonly ExperienceGovernanceChannel[] = ['all', 'live', 'pilot', 'draft'];
  readonly applications = signal<StudioExperience[]>([]);
  readonly audit = signal<ExperienceAuditRow[]>([]);
  readonly drifts = signal<StudioDrift[]>([]);
  readonly loading = signal(false);
  readonly inventoryError = signal(false);
  readonly auditError = signal(false);
  readonly driftState = signal<'loading' | 'ready' | 'error'>('loading');
  readonly driftError = computed(() => this.driftState() === 'error');
  readonly inventoryQuery = signal('');
  readonly channelFilter = signal<ExperienceGovernanceChannel>('all');
  readonly auditApplication = signal('');
  readonly auditEvent = signal('');
  readonly auditQuery = signal('');

  readonly filteredApplications = computed(() => filterExperienceInventory(
    this.applications(),
    this.inventoryQuery(),
    this.channelFilter(),
  ));
  readonly eventTypes = computed(() => [...new Set(this.audit().map((row) => row.event_type))].sort());
  readonly filteredAudit = computed(() => filterExperienceAudit(
    this.audit(),
    this.applications(),
    {
      eventType: this.auditEvent(),
      experienceId: this.auditApplication(),
      query: this.auditQuery(),
    },
  ));

  ngOnInit(): void {
    this.load();
  }

  ngOnDestroy(): void {
    this.workspaceView.destroy();
  }

  load(): void {
    this.requestSubscription?.unsubscribe();
    const request = this.workspaceView.beginRequest();
    this.loading.set(true);
    this.inventoryError.set(false);
    this.auditError.set(false);
    this.driftState.set('loading');

    const applications = this.studio.listExperiences().pipe(
      map((value) => ({ value, failed: false })),
      catchError(() => of({ value: [] as StudioExperience[], failed: true })),
    );
    const audit = this.api.get<ExperienceAuditResponse>('/experiences/audit', { limit: '500' }).pipe(
      map((value) => ({ value: value.logs ?? [], failed: false })),
      catchError(() => of({ value: [] as ExperienceAuditRow[], failed: true })),
    );
    const drifts = this.studio.listDriftedBindings().pipe(
      map((value) => ({ value, failed: false })),
      catchError(() => of({ value: [] as StudioDrift[], failed: true })),
    );

    const subscription = forkJoin({ applications, audit, drifts }).subscribe((result) => {
      if (!this.workspaceView.isCurrent(request)) return;
      this.applications.set(result.applications.value);
      this.audit.set(result.audit.value);
      this.drifts.set(result.drifts.value);
      this.inventoryError.set(result.applications.failed);
      this.auditError.set(result.audit.failed);
      this.driftState.set(result.drifts.failed ? 'error' : 'ready');
      this.loading.set(false);
    });
    this.requestSubscription = subscription.closed ? null : subscription;
  }

  setChannelFilter(value: string): void {
    if (this.channels.includes(value as ExperienceGovernanceChannel)) {
      this.channelFilter.set(value as ExperienceGovernanceChannel);
    }
  }

  countChannel(channel: Exclude<ExperienceGovernanceChannel, 'all'>): number {
    return this.applications().filter((row) => experienceGovernanceChannel(row) === channel).length;
  }

  channelLabel(channel: string): string {
    const key = `governance.experience.channel.${channel}`;
    const label = this.i18n.t(key);
    return label === key ? channel : label;
  }

  deploymentsFor(row: ExperienceGovernanceRow): ExperienceGovernanceDeployment[] {
    return [...(row.deployments ?? [])].sort((a, b) => (
      a.channel === b.channel ? 0 : a.channel === 'live' ? -1 : 1
    ));
  }

  audienceText(value: unknown): string {
    const audience = projectAudience(value);
    if (audience.kind === 'open') return this.i18n.t('governance.experience.audience.workspace');
    const roles = audience.roles.map((role) => {
      const key = `governance.access.role.${role}`;
      const label = this.i18n.t(key);
      return label === key ? role : label;
    });
    const groups = audience.groups.map((group) => this.i18n.t('governance.experience.audience.group', { group }));
    return [...roles, ...groups].join(', ');
  }

  shortId(value: string | undefined): string {
    return value ? value.slice(0, 8) : '—';
  }

  driftCount(row: ExperienceGovernanceRow): number {
    return driftCountFor(row, this.drifts().map((item) => item.binding.binding_key));
  }

  driftReasons(row: ExperienceGovernanceRow): string[] {
    const keys = new Set(row.binding_keys ?? []);
    return this.drifts()
      .filter((item) => keys.has(item.binding.binding_key))
      .flatMap((item) => item.reasons.map((reason) => `${item.binding.binding_key} · ${reason}`));
  }

  originFor(row: ExperienceGovernanceRow): string {
    return `experience:${row.slug}`;
  }

  eventLabel(event: string): string {
    const suffix = event.replace(/^experience\./, '').replaceAll('.', '_');
    const key = `governance.experience.event.${suffix}`;
    const label = this.i18n.t(key);
    return label === key ? event : label;
  }

  applicationName(log: ExperienceAuditRow): string {
    const details = log.details ?? {};
    const id = details['experience_id'];
    if (typeof id === 'string') {
      const byId = this.applications().find((row) => row.id === id);
      if (byId) return byId.name;
    }
    if (log.agent_id) {
      const byAgent = this.applications().find((row) => row.id === log.agent_id);
      if (byAgent) return byAgent.name;
    }
    const binding = details['binding_key'];
    if (typeof binding === 'string') {
      const related = this.applications().filter((row) => (row.binding_keys ?? []).includes(binding));
      if (related.length > 0) return related.map((row) => row.name).join(', ');
      return binding;
    }
    return '—';
  }

  eventSummary(log: ExperienceAuditRow): string {
    const details = log.details ?? {};
    const values = [
      typeof details['channel'] === 'string' ? this.channelLabel(details['channel']) : null,
      typeof details['release_number'] === 'number' ? `R${details['release_number']}` : null,
      typeof details['revision'] === 'number' ? `rev. ${details['revision']}` : null,
      typeof details['binding_key'] === 'string' ? details['binding_key'] : null,
      typeof details['run_id'] === 'string' ? `Run ${this.shortId(details['run_id'])}` : null,
    ].filter((value): value is string => !!value);
    return values.join(' · ') || '—';
  }

  hasDetails(log: ExperienceAuditRow): boolean {
    return Object.keys(log.details ?? {}).length > 0;
  }

  formatDetails(log: ExperienceAuditRow): string {
    return JSON.stringify(log.details ?? {}, null, 2);
  }

  formatTime(value: string | null | undefined): string {
    if (!value) return '—';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return parsed.toLocaleString(this.i18n.locale() === 'fr' ? 'fr-FR' : 'en-GB', {
      dateStyle: 'short',
      timeStyle: 'short',
    });
  }

  private resetView(): void {
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    this.applications.set([]);
    this.audit.set([]);
    this.drifts.set([]);
    this.loading.set(false);
    this.inventoryError.set(false);
    this.auditError.set(false);
    this.driftState.set('loading');
    this.auditApplication.set('');
  }
}
