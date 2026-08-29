import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { forkJoin, of } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';
import { CanonicalApiService, type Run, type System } from '@app/core/canonical-api.service';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { WorkApiService } from './work-api.service';
import {
  DESK_MCP_LANES,
  composeDesk,
  hanaLaneFromPreview,
  laneFromPreview,
  type DeskLane,
  type DeskPreview,
} from './pr-to-po-desk';

const SYSTEM_NAME = 'PR to PO';

@Component({
  selector: 'app-pr-to-po-board',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, RouterLink, EmptyStateComponent],
  styleUrl: './work.scss',
  template: `
    <div class="xp-work xp-work-desk" data-theme="dark" data-desk="nawa">
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
            [disabled]="!system() || starting()"
          >
            {{ starting() ? i18n.t('experience.pr_to_po.starting') : i18n.t('experience.pr_to_po.start') }}
          </button>
        </div>
      </header>

      <section class="xp-work-main xp-desk-main">
        @if (error(); as err) {
          <p class="xp-work-error">{{ err }}</p>
        }

        <section class="xp-desk-hero">
          <p class="xp-desk-kicker">{{ i18n.t('experience.pr_to_po.desk.chain') }}</p>
          <h2>{{ i18n.t(briefing().headlineKey, briefing().headlineParams) }}</h2>
          <p>{{ i18n.t(briefing().nextKey) }}</p>
          @if (readAt(); as when) {
            <p class="xp-desk-asof">{{ i18n.t('experience.pr_to_po.desk.as_of', { time: when }) }}</p>
          }
        </section>

        <ol class="xp-desk-line">
          @for (station of briefing().stations; track station.id) {
            <li [attr.data-status]="station.status">
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
            <li [attr.data-tone]="kpi.tone">
              <span>{{ i18n.t('experience.pr_to_po.desk.kpi.' + kpi.id) }}</span>
              <strong>{{ kpi.value }}</strong>
            </li>
          }
        </ul>

        @if (terrainLoading() && lanes().length === 0) {
          <app-empty-state icon="sparkles" size="lg" [title]="i18n.t('experience.pr_to_po.desk.reading')" />
        }

        @if (visibleLanes().length) {
          <h3 class="xp-desk-raw">{{ i18n.t('experience.pr_to_po.desk.raw') }}</h3>
        }
        <div class="xp-desk-grid">
          @for (lane of visibleLanes(); track lane.id) {
            <article class="xp-desk-card" [attr.data-status]="lane.status">
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
  private readonly workApi = inject(WorkApiService);
  readonly i18n = inject(I18nService);
  readonly workspace = inject(WorkspaceService);

  readonly loading = signal(false);
  readonly terrainLoading = signal(false);
  readonly starting = signal(false);
  readonly error = signal<string | null>(null);
  readonly system = signal<System | null>(null);
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
    this.canonical
      .listSystems()
      .pipe(
        switchMap((systems) => {
          const found =
            systems.find((row) => row.settings?.['nawa_pr_to_po'] === true) ||
            systems.find((row) => row.name === SYSTEM_NAME) ||
            null;
          this.system.set(found);
          if (!found?.id) return of([] as Run[]);
          return this.canonical.listRuns({ system_id: found.id, status: 'hitl_pending' });
        }),
        switchMap((runs) => {
          if (!runs.length) return of([] as Run[]);
          return forkJoin(runs.map((run) => this.canonical.getRun(run.id).pipe(map((full) => full || run))));
        }),
        catchError(() => {
          this.error.set(this.i18n.t('experience.pr_to_po.missing'));
          return of([] as Run[]);
        }),
      )
      .subscribe((runs) => {
        this.items.set(runs.filter((run) => run.status === 'hitl_pending'));
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
    const system = this.system();
    const sha = system?.flow_sha256;
    if (!system?.id || !sha) {
      this.error.set(this.i18n.t('experience.pr_to_po.missing'));
      return;
    }
    this.starting.set(true);
    this.canonical
      .triggerRun(system.id, {
        trigger: 'manual',
        input_ref: {},
        expected_flow_sha256: sha,
      })
      .subscribe({
        next: () => {
          this.starting.set(false);
          this.load();
        },
        error: () => {
          this.starting.set(false);
          this.error.set(this.i18n.t('experience.pr_to_po.missing'));
        },
      });
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

  packageField(run: Run, key: string): string {
    const upstream = run.hitl?.upstream;
    const value = upstream && typeof upstream === 'object' ? upstream[key] : undefined;
    return value == null ? '—' : typeof value === 'string' ? value : JSON.stringify(value);
  }

  packageJson(run: Run): string {
    return JSON.stringify(run.hitl?.upstream ?? {}, null, 2);
  }

  private previewDetail(err: { error?: { detail?: unknown } }): string {
    const detail = err?.error?.detail;
    return typeof detail === 'string' ? detail : '';
  }
}
