import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { forkJoin, of } from 'rxjs';
import { catchError, map, switchMap, take, tap } from 'rxjs/operators';
import { CanonicalApiService, type Run, type System } from '@app/core/canonical-api.service';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { ExperienceRuntimeService } from '../runtime/experience-runtime.service';
import { WorkApiService } from './work-api.service';
import {
  DESK_MCP_LANES,
  FACTORY_ASK_CHIPS,
  askFactory,
  composeDesk,
  donutSlices,
  hanaLaneFromPreview,
  laneFromPreview,
  orderCoverage,
  supplierShares,
  terrainShares,
  type DeskLane,
  type DeskLaneId,
  type DeskPreview,
  type FactoryAskIntent,
  type FactoryAskReply,
} from './pr-to-po-desk';
import {
  FACTORY_BINDING_KEY,
  FACTORY_EXPERIENCE_SLUG,
  canStartFactoryCycle,
  factoryFlowHref,
  factoryRunHref,
  factoryRunOrigin,
  factoryRuntimeContext,
  factorySystemHref,
} from './pr-to-po-runtime';

@Component({
  selector: 'app-pr-to-po-board',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, RouterLink, EmptyStateComponent],
  styleUrl: './work.scss',
  template: `
    <div
      class="xp-work xp-work-desk"
      data-theme="dark"
      data-desk="nawa"
      [attr.data-reading]="terrainLoading() ? 'true' : null"
    >
      <header class="xp-work-bar xp-desk-bar">
        <div class="xp-work-brand">
          <p class="xp-work-eyebrow">{{ workspace.current()?.name }} · {{ i18n.t('experience.pr_to_po.desk.eyebrow') }}</p>
          <h1>{{ i18n.t('experience.pr_to_po.title') }}</h1>
          <p>{{ i18n.t('experience.pr_to_po.subtitle') }}</p>
        </div>
        <div class="xp-work-hitl-actions">
          <a routerLink="/work" class="xp-work-btn">{{ i18n.t('experience.work.title') }}</a>
          <a
            routerLink="/connectors/mcp"
            [queryParams]="workspaceQuery()"
            class="xp-work-btn"
          >
            {{ i18n.t('experience.pr_to_po.desk.sources') }}
          </a>
          <button type="button" class="xp-work-btn" (click)="reload()" [disabled]="loading() || terrainLoading()">
            {{ i18n.t('experience.pr_to_po.refresh') }}
          </button>
          <button
            type="button"
            class="xp-work-btn xp-work-btn-primary"
            (click)="loadTerrain()"
            [disabled]="terrainLoading()"
          >
            {{ terrainLoading() ? i18n.t('experience.pr_to_po.desk.reading') : i18n.t('experience.pr_to_po.desk.read') }}
          </button>
          <button
            type="button"
            class="xp-work-btn"
            (click)="startRun()"
            [disabled]="!bindingReady() || starting()"
          >
            {{ starting() ? i18n.t('experience.pr_to_po.starting') : i18n.t('experience.pr_to_po.start') }}
          </button>
        </div>
      </header>

      <section class="xp-work-main xp-desk-main">
        @if (error(); as err) {
          <p class="xp-work-error">{{ err }}</p>
        }

        <section class="xp-desk-lineage">
          <p class="xp-desk-kicker">{{ i18n.t('experience.pr_to_po.lineage.eyebrow') }}</p>
          <ol>
            <li>
              <span>{{ i18n.t('experience.pr_to_po.lineage.application') }}</span>
              <strong>{{ i18n.t('experience.pr_to_po.title') }}</strong>
              <code>{{ experienceSlug }}</code>
            </li>
            <li>
              <span>{{ i18n.t('experience.pr_to_po.lineage.system') }}</span>
              @if (system(); as sys) {
                <a [routerLink]="systemHref(sys.id)">{{ sys.name }}</a>
              } @else {
                <strong>—</strong>
              }
              <code>{{ bindingKey }}</code>
            </li>
            <li>
              <span>{{ i18n.t('experience.pr_to_po.lineage.run') }}</span>
              @if (startedRun(); as run) {
                <a [routerLink]="runHref(run.id)">{{ runStatusLabel(run.status) }}</a>
                <code>{{ shortId(run.id) }}</code>
              } @else if (starting()) {
                <strong>{{ i18n.t('experience.pr_to_po.lineage.starting') }}</strong>
              } @else {
                <strong>{{ i18n.t('experience.pr_to_po.lineage.no_run') }}</strong>
              }
            </li>
          </ol>
          <nav>
            @if (system(); as sys) {
              <a [routerLink]="systemHref(sys.id)">{{ i18n.t('experience.pr_to_po.lineage.open_system') }}</a>
              <a [routerLink]="flowHref(sys.id)">{{ i18n.t('experience.pr_to_po.lineage.open_flow') }}</a>
            }
            @if (startedRun(); as run) {
              <a [routerLink]="runHref(run.id)">{{ i18n.t('experience.pr_to_po.lineage.open_run') }}</a>
            }
          </nav>
        </section>

        <section class="xp-desk-hero">
          <p class="xp-desk-kicker">{{ i18n.t('experience.pr_to_po.desk.chain') }}</p>
          <h2>{{ i18n.t(briefing().headlineKey, briefing().headlineParams) }}</h2>
          <p class="xp-desk-voice">{{ i18n.t(briefing().voiceKey, briefing().voiceParams) }}</p>
          <p>{{ i18n.t(briefing().nextKey) }}</p>
          @if (readAt(); as when) {
            <p class="xp-desk-asof">{{ i18n.t('experience.pr_to_po.desk.as_of', { time: when }) }}</p>
          }
        </section>

        <section class="xp-desk-ask">
          <form (submit)="submitAsk($event)">
            <label for="factory-ask">{{ i18n.t('experience.pr_to_po.desk.ask.label') }}</label>
            <div class="xp-desk-ask-row">
              <input
                id="factory-ask"
                type="text"
                [value]="askDraft()"
                [placeholder]="i18n.t('experience.pr_to_po.desk.ask.placeholder')"
                (input)="setAskDraft($event)"
              />
              <button type="submit" class="xp-work-btn xp-work-btn-primary">
                {{ i18n.t('experience.pr_to_po.desk.ask.submit') }}
              </button>
            </div>
          </form>
          <p class="xp-desk-note">{{ i18n.t('experience.pr_to_po.desk.ask.hint') }}</p>
          <div class="xp-desk-chips">
            @for (chip of askChips; track chip) {
              <button type="button" class="xp-desk-chip" (click)="askChip(chip)">
                {{ i18n.t('experience.pr_to_po.desk.ask.chip.' + chip) }}
              </button>
            }
          </div>
          @if (askReply(); as reply) {
            <p class="xp-desk-reply">{{ i18n.t(reply.key, reply.params) }}</p>
          }
        </section>

        <ol class="xp-desk-line">
          @for (station of briefing().stations; track station.id; let i = $index) {
            <li [attr.data-status]="station.status" [style.--desk-beat]="i">
              <span>{{ i18n.t('experience.pr_to_po.desk.station.' + station.id) }}</span>
              <strong>{{ i18n.t('experience.pr_to_po.desk.station_status.' + station.status) }}</strong>
              @if (station.via) {
                <em>{{ station.via }}</em>
              }
            </li>
          }
        </ol>

        @if (briefing().facts.length) {
          <section class="xp-desk-dossier">
            <h3>{{ i18n.t('experience.pr_to_po.desk.dossier') }}</h3>
            <p>{{ i18n.t('experience.pr_to_po.desk.factory_note') }}</p>
            <dl>
              @for (fact of briefing().facts; track fact.id) {
                <div>
                  <dt>{{ i18n.t('experience.pr_to_po.desk.fact.' + fact.id) }}</dt>
                  <dd>
                    <strong>{{ fact.value }}</strong>
                    @if (fact.via) {
                      <span>{{ i18n.t('experience.pr_to_po.desk.via', { tool: fact.via }) }}</span>
                    }
                  </dd>
                </div>
              }
            </dl>
          </section>
        }

        <ul class="xp-desk-kpis">
          @for (kpi of briefing().kpis; track kpi.id) {
            <li [attr.data-tone]="kpi.tone" [attr.data-focus]="focusLane() === kpi.id">
              <button type="button" (click)="toggleFocus(kpi.id)">
                <span>{{ i18n.t('experience.pr_to_po.desk.kpi.' + kpi.id) }}</span>
                <strong>{{ kpi.value }}</strong>
              </button>
            </li>
          }
        </ul>

        <section class="xp-desk-charts">
          <article class="xp-desk-chart">
            <h3>{{ i18n.t('experience.pr_to_po.desk.charts.terrain') }}</h3>
            @if (terrain().length) {
              <div class="xp-desk-donut-wrap">
                <svg viewBox="0 0 80 80" class="xp-desk-donut" aria-hidden="true">
                  @for (slice of terrain(); track slice.id) {
                    <circle
                      cx="40"
                      cy="40"
                      r="28"
                      pathLength="100"
                      [attr.data-lane]="slice.id"
                      [attr.stroke-dasharray]="slice.pct + ' ' + (100 - slice.pct)"
                      [attr.stroke-dashoffset]="slice.offset"
                      (click)="toggleFocus(slice.id)"
                    />
                  }
                </svg>
                <ul>
                  @for (slice of terrain(); track slice.id) {
                    <li>
                      <button type="button" [attr.data-lane]="slice.id" (click)="toggleFocus(slice.id)">
                        <i></i>
                        <span>{{ i18n.t('experience.pr_to_po.desk.kpi.' + slice.id) }}</span>
                        <strong>{{ slice.value }}</strong>
                      </button>
                    </li>
                  }
                </ul>
              </div>
            } @else {
              <p class="xp-desk-note">{{ i18n.t('experience.pr_to_po.desk.charts.empty') }}</p>
            }
          </article>
          <article class="xp-desk-chart">
            <h3>{{ i18n.t('experience.pr_to_po.desk.charts.suppliers') }}</h3>
            @if (suppliers().length) {
              <ul class="xp-desk-bars">
                @for (bar of suppliers(); track bar.id; let i = $index) {
                  <li [style.--desk-beat]="i">
                    <div>
                      <span>{{ shareLabel(bar.id) }}</span>
                      <strong>{{ bar.pct }}%</strong>
                    </div>
                    <b [style.width.%]="bar.pct"></b>
                  </li>
                }
              </ul>
            } @else {
              <p class="xp-desk-note">{{ i18n.t('experience.pr_to_po.desk.charts.empty') }}</p>
            }
          </article>
          <article class="xp-desk-chart">
            <h3>{{ i18n.t('experience.pr_to_po.desk.charts.coverage') }}</h3>
            <p class="xp-desk-note">
              {{
                i18n.t('experience.pr_to_po.desk.charts.coverage_value', {
                  pos: coverage().pos,
                  prs: coverage().prs,
                })
              }}
            </p>
            <div class="xp-desk-meter" [attr.aria-valuenow]="coverage().pct">
              <b [style.width.%]="coverage().pct"></b>
            </div>
          </article>
        </section>

        @if (terrainLoading() && lanes().length === 0) {
          <app-empty-state icon="sparkles" size="lg" [title]="i18n.t('experience.pr_to_po.desk.reading')" />
        }

        @if (visibleLanes().length) {
          <h3 class="xp-desk-raw">{{ i18n.t('experience.pr_to_po.desk.raw') }}</h3>
        }
        <div class="xp-desk-grid">
          @for (lane of visibleLanes(); track lane.id) {
            <article
              class="xp-desk-card"
              [attr.data-status]="lane.status"
              [attr.data-focus]="focusLane() === lane.id"
              [style.--desk-beat]="$index"
            >
              <header>
                <div>
                  <p class="xp-desk-step">{{ i18n.t('experience.pr_to_po.desk.lane.' + lane.id) }}</p>
                  @if (lane.tool) {
                    <p class="xp-desk-tool">{{ i18n.t('experience.pr_to_po.desk.via', { tool: lane.tool }) }}</p>
                  }
                </div>
                <span class="xp-desk-status">{{ i18n.t('experience.pr_to_po.desk.status.' + lane.status) }}</span>
              </header>
              @if (lane.id === 'hana' && lane.source) {
                <p class="xp-desk-note">
                  {{
                    lane.source === 'hana_live'
                      ? i18n.t('experience.pr_to_po.desk.hana_live')
                      : i18n.t('experience.pr_to_po.desk.hana_demo')
                  }}
                </p>
              }
              @if (lane.detail && !lane.detail.startsWith('mcp_')) {
                <p class="xp-desk-note">{{ lane.detail }}</p>
              }
              @if (lane.columns.length) {
                <div class="xp-desk-table-wrap">
                  <table>
                    <thead>
                      <tr>
                        @for (col of lane.columns; track col) {
                          <th>{{ col }}</th>
                        }
                      </tr>
                    </thead>
                    <tbody>
                      @for (row of lane.rows; track $index) {
                        <tr>
                          @for (cell of row; track $index) {
                            <td [title]="cell">{{ cell || '—' }}</td>
                          }
                        </tr>
                      }
                    </tbody>
                  </table>
                </div>
                <p class="xp-desk-count">{{ i18n.t('experience.pr_to_po.desk.rows', { count: lane.rowCount }) }}</p>
              } @else if (!terrainLoading()) {
                <p class="xp-desk-note">{{ i18n.t('experience.pr_to_po.desk.status.' + lane.status) }}</p>
              }
            </article>
          }
        </div>

        <section class="xp-work-hitl xp-desk-hitl">
          <h3>{{ i18n.t('experience.pr_to_po.desk.hitl_title') }}</h3>
          @if (loading()) {
            <app-empty-state icon="sparkles" size="lg" [title]="i18n.t('common.loading')" />
          } @else if (items().length === 0) {
            <p class="xp-work-note">{{ i18n.t('experience.pr_to_po.empty') }}</p>
          } @else {
            @for (run of items(); track run.id) {
              <article>
                <h3>{{ i18n.t('experience.pr_to_po.run', { id: shortId(run.id) }) }}</h3>
                <p>{{ run.hitl?.prompt }}</p>
                <dl>
                  <dt>{{ i18n.t('experience.pr_to_po.supplier') }}</dt>
                  <dd>{{ packageField(run, 'supplier') }}</dd>
                  <dt>{{ i18n.t('experience.pr_to_po.format') }}</dt>
                  <dd>{{ packageField(run, 'format') }}</dd>
                  <dt>{{ i18n.t('experience.pr_to_po.summary') }}</dt>
                  <dd>{{ packageField(run, 'summary') || packageField(run, 'justification_summary') }}</dd>
                </dl>
                <details>
                  <summary>{{ i18n.t('experience.pr_to_po.package') }}</summary>
                  <pre>{{ packageJson(run) }}</pre>
                </details>
                <label>
                  <span>{{ i18n.t('experience.pr_to_po.note') }}</span>
                  <textarea
                    [value]="notes()[run.id] || ''"
                    (input)="setNote(run.id, $event)"
                  ></textarea>
                </label>
                <div class="xp-work-hitl-actions">
                  <a [routerLink]="runHref(run.id)" class="xp-work-btn">{{ i18n.t('experience.pr_to_po.lineage.open_run') }}</a>
                  <button type="button" class="xp-work-btn xp-work-btn-primary" (click)="decide(run, 'accept')">
                    {{ i18n.t('experience.pr_to_po.approve') }}
                  </button>
                  <button type="button" class="xp-work-btn" (click)="decide(run, 'reject')">
                    {{ i18n.t('experience.pr_to_po.reject') }}
                  </button>
                </div>
              </article>
            }
          }
        </section>
      </section>
    </div>
  `,
})
export class PrToPoBoardComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly runtime = inject(ExperienceRuntimeService);
  private readonly workApi = inject(WorkApiService);
  readonly i18n = inject(I18nService);
  readonly workspace = inject(WorkspaceService);
  readonly experienceSlug = FACTORY_EXPERIENCE_SLUG;
  readonly bindingKey = FACTORY_BINDING_KEY;

  readonly loading = signal(false);
  readonly terrainLoading = signal(false);
  readonly starting = signal(false);
  readonly bindingReady = signal(false);
  readonly error = signal<string | null>(null);
  readonly system = signal<System | null>(null);
  readonly startedRun = signal<Run | null>(null);
  readonly items = signal<Run[]>([]);
  readonly notes = signal<Record<string, string>>({});
  readonly lanes = signal<DeskLane[]>([]);
  readonly readAt = signal<string>('');
  readonly systemId = computed(() => this.system()?.id ?? null);
  readonly workspaceQuery = computed(() => {
    const slug = this.workspace.currentSlug();
    return slug ? { workspace: slug } : {};
  });
  readonly visibleLanes = computed(() => this.lanes());
  readonly briefing = computed(() => composeDesk(this.lanes(), this.items().length));
  readonly terrain = computed(() => donutSlices(terrainShares(this.briefing().kpis)));
  readonly suppliers = computed(() => supplierShares(this.lanes()));
  readonly coverage = computed(() => orderCoverage(this.lanes()));
  readonly focusLane = signal<DeskLaneId | null>(null);
  readonly askDraft = signal('');
  readonly askReply = signal<FactoryAskReply | null>(null);
  readonly askChips = FACTORY_ASK_CHIPS;

  ngOnInit(): void {
    this.load();
    this.loadTerrain();
  }

  reload(): void {
    this.load();
    this.loadTerrain();
  }

  load(): void {
    this.loading.set(true);
    this.error.set(null);
    const context = factoryRuntimeContext();
    this.runtime
      .resolve(context, FACTORY_BINDING_KEY)
      .pipe(
        switchMap((resolved) => {
          const ready = canStartFactoryCycle(resolved);
          this.bindingReady.set(ready);
          if (!ready) {
            this.system.set(null);
            this.error.set(this.i18n.t('experience.pr_to_po.lineage.app_offline'));
            return of({ hitl: [] as Run[], latest: null as Run | null });
          }
          return this.workApi.listPendingValidations(FACTORY_EXPERIENCE_SLUG).pipe(
            switchMap((validations) => {
              const hitl$ =
                validations.kind === 'ok'
                  ? this.hydrateRuns(validations.items)
                  : this.canonical
                      .listRuns({ origin: factoryRunOrigin(), status: 'hitl_pending' })
                      .pipe(switchMap((runs) => this.hydrateRuns(runs)));
              const latest$ = this.canonical
                .listRuns({ origin: factoryRunOrigin() })
                .pipe(map((runs) => runs[0] ?? null));
              return forkJoin({ hitl: hitl$, latest: latest$ });
            }),
          );
        }),
        switchMap(({ hitl, latest }) => {
          const fromRun = latest?.system_id || hitl[0]?.system_id || null;
          return this.linkedSystem$(fromRun).pipe(map((system) => ({ hitl, latest, system })));
        }),
        catchError(() => {
          this.bindingReady.set(false);
          this.error.set(this.i18n.t('experience.pr_to_po.lineage.app_offline'));
          return of({ hitl: [] as Run[], latest: null as Run | null, system: null as System | null });
        }),
      )
      .subscribe(({ hitl, latest, system }) => {
        this.system.set(system);
        this.items.set(hitl.filter((run) => run.status === 'hitl_pending'));
        if (latest) this.startedRun.set(latest);
        this.loading.set(false);
      });
  }

  loadTerrain(): void {
    if (!this.workspace.mcpConnectorEnabled()) {
      this.lanes.set([]);
      return;
    }
    this.terrainLoading.set(true);
    const mcp$ = DESK_MCP_LANES.map((lane) =>
      this.api.get<DeskPreview>(`/mcp/servers/${encodeURIComponent(lane.serverId)}/preview`).pipe(
        map((body) => laneFromPreview(lane.id, lane.serverId, body)),
        catchError((err: { error?: { detail?: unknown } }) =>
          of(laneFromPreview(lane.id, lane.serverId, null, this.previewDetail(err))),
        ),
      ),
    );
    const hana$ = this.workspace.sapHanaConnectorEnabled()
      ? this.api.get<DeskPreview>('/hana/preview').pipe(
          map((body) => hanaLaneFromPreview(body)),
          catchError((err: { error?: { detail?: unknown } }) => of(hanaLaneFromPreview(null, this.previewDetail(err)))),
        )
      : of(null);
    forkJoin({ mcp: forkJoin(mcp$), hana: hana$ }).subscribe({
      next: ({ mcp, hana }) => {
        this.lanes.set(hana ? [...mcp, hana] : mcp);
        this.readAt.set(new Date().toLocaleTimeString());
        this.terrainLoading.set(false);
      },
      error: () => {
        this.terrainLoading.set(false);
      },
    });
  }

  startRun(): void {
    if (!this.bindingReady()) {
      this.error.set(this.i18n.t('experience.pr_to_po.lineage.app_offline'));
      return;
    }
    this.starting.set(true);
    this.error.set(null);
    const context = factoryRuntimeContext();
    this.runtime
      .invoke(context, FACTORY_BINDING_KEY, {})
      .pipe(
        switchMap((started) => {
          if (!started?.id) return of(null);
          return this.canonical.getRun(started.id);
        }),
        switchMap((run) => {
          if (!run) return of(null);
          this.startedRun.set(run);
          if (!run.system_id) return of(run);
          return this.canonical.getSystem(run.system_id).pipe(
            tap((system) => {
              if (system) this.system.set(system);
            }),
            map(() => run),
          );
        }),
      )
      .subscribe({
        next: (run) => {
          this.starting.set(false);
          if (!run) {
            this.error.set(this.i18n.t('experience.pr_to_po.lineage.start_failed'));
            return;
          }
          this.runtime
            .poll(context, run.id)
            .pipe(take(8))
            .subscribe((updated) => {
              if (updated) this.startedRun.set(updated);
            });
          this.load();
        },
        error: () => {
          this.starting.set(false);
          this.error.set(this.i18n.t('experience.pr_to_po.lineage.start_failed'));
        },
      });
  }

  toggleFocus(id: string): void {
    const lane = id as DeskLaneId;
    this.focusLane.update((current) => (current === lane ? null : lane));
  }

  setAskDraft(event: Event): void {
    this.askDraft.set((event.target as HTMLInputElement).value);
  }

  submitAsk(event: Event): void {
    event.preventDefault();
    this.applyAsk(askFactory(this.askDraft(), this.briefing(), this.lanes()));
  }

  askChip(intent: FactoryAskIntent): void {
    this.applyAsk(askFactory(intent, this.briefing(), this.lanes()));
  }

  shareLabel(id: string): string {
    return id === 'other' ? this.i18n.t('experience.pr_to_po.desk.charts.other') : id;
  }

  private applyAsk(reply: FactoryAskReply): void {
    this.askReply.set(reply);
    if (reply.focus) this.focusLane.set(reply.focus);
  }

  setNote(runId: string, event: Event): void {
    const value = (event.target as HTMLTextAreaElement).value;
    this.notes.update((current) => ({ ...current, [runId]: value }));
  }

  decide(run: Run, action: 'accept' | 'reject'): void {
    const note = (this.notes()[run.id] || '').trim();
    this.workApi.decide(run.id, action, note).subscribe((updated) => {
      if (!updated) {
        this.error.set(this.i18n.t('experience.work.validations.error'));
        return;
      }
      this.items.update((rows) => rows.filter((item) => item.id !== run.id));
    });
  }

  shortId(id: string): string {
    return id.slice(0, 8);
  }

  runStatusLabel(status: string): string {
    const key = `runs.status.${status}`;
    const label = this.i18n.t(key);
    return label === key ? this.i18n.t('runs.status.unknown') : label;
  }

  systemHref(systemId: string): string {
    return factorySystemHref(systemId);
  }

  flowHref(systemId: string): string {
    return factoryFlowHref(systemId);
  }

  runHref(runId: string): string {
    return factoryRunHref(runId);
  }

  packageField(run: Run, key: string): string {
    const upstream = run.hitl?.upstream;
    const value = upstream && typeof upstream === 'object' ? upstream[key] : undefined;
    return value == null ? '—' : typeof value === 'string' ? value : JSON.stringify(value);
  }

  packageJson(run: Run): string {
    return JSON.stringify(run.hitl?.upstream ?? {}, null, 2);
  }

  private hydrateRuns(runs: Run[]) {
    const ids = runs.map((run) => run.id).filter(Boolean).slice(0, 8);
    if (!ids.length) return of([] as Run[]);
    return forkJoin(ids.map((id) => this.canonical.getRun(id))).pipe(
      map((rows) => rows.filter((row): row is Run => !!row)),
    );
  }

  private linkedSystem$(systemId: string | null) {
    if (systemId) return this.canonical.getSystem(systemId);
    return this.api.get<{ system_id?: string }>(`/system-bindings/${encodeURIComponent(FACTORY_BINDING_KEY)}`).pipe(
      switchMap((row) => (row.system_id ? this.canonical.getSystem(row.system_id) : of(null))),
      catchError(() => of(null)),
    );
  }

  private previewDetail(err: { error?: { detail?: unknown } }): string {
    const detail = err?.error?.detail;
    return typeof detail === 'string' ? detail : '';
  }
}
