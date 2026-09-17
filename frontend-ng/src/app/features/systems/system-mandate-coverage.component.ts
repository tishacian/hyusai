import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { MandateApiService } from '@app/features/mandate/mandate-api.service';
import type { MandateEvent, RunMandate, SystemMandate } from '@app/features/mandate/mandate.models';
import { MANDATE_FACETS, mandateCoverageCell, mandateCoverageCounts, mandateFacetEvents, type MandateCoverageRun, type MandateFacet } from './system-mandate-coverage.vm';

@Component({
  selector: 'app-system-mandate-coverage',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NavLinkDirective, RouterLink],
  template: `
    <section class="coverage" aria-labelledby="mandate-coverage-title" data-testid="system-mandate-coverage">
      <header class="coverage-heading">
        <div><h2 id="mandate-coverage-title">{{ t('title') }}</h2><p>{{ t('subtitle') }}</p></div>
        <button type="button" class="ck-btn-quiet" (click)="load()" [disabled]="loading()">{{ t('refresh') }}</button>
      </header>
      @if (loading()) { <p role="status">{{ t('loading') }}</p> }
      @else if (error()) { <p role="alert">{{ t('unavailable') }}</p> }
      @else if (data(); as mandate) {
        @if (recentRuns().length === 0) {
          <div class="coverage-empty"><h3>{{ t('empty') }}</h3><p>{{ t('empty_hint') }}</p>
            <a class="ck-btn-quiet" [navLink]="{leaf: 'system-flow', ref: systemId()}">{{ t('open_flow') }}</a>
          </div>
        } @else {
          <div class="coverage-summary">
            <div><strong>{{ counts().total }}</strong><span>{{ i18n.t('mandate_system.matrix_caption', {runs: recentRuns().length, facets: facets.length}) }}</span></div>
            <div><strong class="coverage-accent">{{ counts().recorded }}</strong><span>{{ t('with_record') }}</span></div>
            <div><strong>{{ counts().missing }}</strong><span>{{ t('no_record') }}</span></div>
          </div>
          <div class="coverage-layout">
            <section class="coverage-panel">
              <header><h3>{{ t('matrix_title') }}</h3><p>{{ t('matrix_hint') }}</p></header>
              <div class="coverage-scroll" tabindex="0" [attr.aria-label]="t('matrix_title')">
                <table>
                  <caption>{{ i18n.t('mandate_system.recent', {count: recentRuns().length}) }}</caption>
                  <thead><tr><th scope="col">{{ t('control') }}</th>
                    @for (run of recentRuns(); track run.run_id) {
                      <th scope="col"><button type="button" [class.selected]="selectedRunId() === run.run_id" (click)="selectRun(run.run_id)" [attr.aria-pressed]="selectedRunId() === run.run_id">{{ run.run_id.slice(0, 8) }}</button></th>
                    }
                  </tr></thead>
                  <tbody>
                    @for (facet of facets; track facet) {
                      <tr><th scope="row">{{ t(facet) }}</th>
                        @for (run of recentRuns(); track run.run_id) {
                          <td><button type="button" class="coverage-cell" [attr.data-state]="cell(run, facet).state" [class.selected]="selectedRunId() === run.run_id && selectedFacet() === facet" [attr.aria-pressed]="selectedRunId() === run.run_id && selectedFacet() === facet" [attr.aria-label]="cellLabel(run, facet)" [title]="cellLabel(run, facet)" (click)="selectRun(run.run_id, facet)">
                            <span aria-hidden="true">{{ cell(run, facet).state === 'not_recorded' ? '—' : cell(run, facet).state === 'breached' ? '!' : '+' }}</span>
                            <span class="cell-count">{{ cell(run, facet).count || '' }}</span>
                          </button></td>
                        }
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
              <div class="coverage-legend"><span><b>+</b> {{ t('record') }}</span><span><b>!</b> {{ t('breached') }}</span><span><b>—</b> {{ t('not_recorded') }}</span></div>
              <p class="coverage-footnote">{{ t('no_assumption') }}</p>
            </section>
            <aside class="coverage-panel proof-panel" aria-live="polite" [attr.aria-busy]="runLoading()">
              <header><p class="coverage-eyebrow">{{ t('selected') }} · {{ selectedRunId().slice(0, 8) }}</p>
                <h3>{{ t('proof_chain') }}</h3>
                @if (selectedFacet(); as facet) { <p>{{ i18n.t('mandate_system.selected_facet', {facet: t(facet)}) }}</p><button type="button" class="coverage-text-button" (click)="selectRun(selectedRunId())">{{ t('clear_facet') }}</button> }
              </header>
              @if (runLoading()) { <p role="status">{{ t('loading') }}</p> }
              @else if (runError()) { <p role="alert">{{ t('run_unavailable') }}</p><button type="button" class="ck-btn-quiet" (click)="selectRun(selectedRunId(), selectedFacet())">{{ i18n.t('common.retry') }}</button> }
              @else if (selectedRun(); as run) {
                <div class="coverage-versions">
                  <div><span>{{ mandate.configuration.policy_binding === 'frozen' ? i18n.t('mandate.published_configuration') : t('current') }}</span><strong>{{ modeLabel(mandate.configuration.mode) }}</strong><small>{{ versionLabel(mandate.configuration.version) }}</small></div>
                  <div><span>{{ t('recorded') }}</span><strong>{{ run.applied.spec ? modeLabel(run.applied.mode) : t('no_snapshot') }}</strong><small>{{ run.applied.spec ? versionLabel(run.applied.version) : '—' }}</small></div>
                </div>
                @if (events().length) {
                  <ol class="proof-events">
                    @for (event of events(); track event.id) {
                      <li [attr.data-state]="event.status"><span class="proof-marker" aria-hidden="true"></span><div><strong>{{ eventLabel(event) }}</strong><p>{{ facetLabel(event.facet) }}</p><small>{{ eventTime(event.at) }}</small><a class="proof-event-link" [routerLink]="eventUrl(event.id)">{{ t('open_event') }}</a></div></li>
                    }
                  </ol>
                } @else { <p>{{ t('no_facet_events') }}</p> }
                <p class="coverage-footnote">{{ t('approval_note') }}</p>
              }
              <a class="ck-cta coverage-run-link" [navLink]="{type: 'run', ref: selectedRunId(), lens: 'govern'}">{{ t('open_run') }}</a>
            </aside>
          </div>
        }
      }
    </section>
  `,
  styles: [`
    :host { display:block; margin-bottom:24px; color:var(--ck-fg-1); }
    .coverage { display:flex; flex-direction:column; gap:20px; }
    .coverage h2,.coverage h3,.coverage p { margin:0; }
    .coverage h2 { font-size:26px; font-weight:650; line-height:1.2; letter-spacing:-.025em; }
    .coverage h3 { font-size:17px; font-weight:600; line-height:1.4; }
    .coverage p { color:var(--ck-fg-3); font-size:13px; line-height:1.6; }
    .coverage-heading { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }
    .coverage-heading p { margin-top:8px; }
    .coverage button,.coverage a { border-radius:var(--radius-md,6px); font:inherit; }
    .coverage button:focus-visible,.coverage a:focus-visible,.coverage-scroll:focus-visible { outline:2px solid var(--ck-signal-cool); outline-offset:3px; }
    .coverage button:disabled { opacity:.6; cursor:wait; }
    .coverage-heading button { flex-shrink:0; padding:10px 14px; font-size:12px; }
    .coverage-summary { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); border:1px solid var(--ck-stroke-2); border-radius:var(--radius-lg,10px); background:var(--ck-bg-panel); padding:20px 24px; gap:24px; }
    .coverage-summary>div { display:flex; gap:14px; align-items:center; }
    .coverage-summary strong { font-size:32px; line-height:1; font-weight:650; font-variant-numeric:tabular-nums; }
    .coverage-summary span { font-size:12px; color:var(--ck-fg-3); line-height:1.5; }
    .coverage-accent { color:var(--ck-signal-cool); }
    .coverage-layout { display:grid; grid-template-columns:minmax(0,1.65fr) minmax(290px,1fr); gap:20px; align-items:start; }
    .coverage-panel { padding:22px; background:var(--ck-bg-panel); border:1px solid var(--ck-stroke-2); border-radius:var(--radius-lg,10px); min-width:0; }
    .coverage-panel header { display:flex; flex-direction:column; gap:8px; padding-bottom:18px; }
    .coverage-scroll { overflow-x:auto; }
    table { border-collapse:separate; border-spacing:6px; width:100%; font-size:12px; }
    caption { text-align:left; color:var(--ck-fg-3); padding:0 6px 14px; font-size:11px; }
    th { text-align:left; font-weight:500; padding:6px 0; line-height:1.4; }
    tbody th { min-width:135px; }
    thead th { color:var(--ck-fg-3); font-size:11px; }
    thead button { background:transparent; border:0; padding:8px 2px; color:inherit; cursor:pointer; font-family:var(--font-mono,monospace)!important; }
    thead button.selected { color:var(--ck-signal-cool); font-weight:700; text-decoration:underline; text-underline-offset:5px; }
    td { min-width:64px; }
    .coverage-cell { width:100%; min-height:42px; display:flex; align-items:center; justify-content:center; gap:8px; background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-2); color:var(--ck-fg-3); cursor:pointer; }
    .coverage-cell[data-state=recorded] { background:var(--ck-status-info-bg); color:var(--ck-signal-cool); border-color:transparent; }
    .coverage-cell[data-state=breached] { background:var(--ck-status-warn-bg); color:var(--ck-signal-warn); border-color:transparent; }
    .coverage-cell.selected { outline:2px solid var(--ck-signal-cool); outline-offset:1px; }
    .cell-count { font-size:11px; }
    .coverage-legend { display:flex; gap:12px; flex-wrap:wrap; padding-top:18px; color:var(--ck-fg-3); font-size:11px; }
    .coverage-legend b { display:inline-block; min-width:14px; }
    .coverage .coverage-footnote { margin-top:18px; font-size:12px; }
    .coverage .coverage-eyebrow { color:var(--ck-signal-cool); font-size:11px; font-weight:600; }
    .coverage-versions { display:grid; grid-template-columns:1fr 1fr; gap:16px; padding:16px 0; border-top:1px solid var(--ck-stroke-1); border-bottom:1px solid var(--ck-stroke-1); }
    .coverage-versions>div { display:flex; flex-direction:column; gap:7px; }
    .coverage-versions span,.coverage-versions small { font-size:11px; color:var(--ck-fg-3); }
    .coverage-versions strong { font-size:13px; font-weight:600; }
    .proof-events { list-style:none; display:flex; flex-direction:column; gap:20px; padding:24px 0 0; margin:0; }
    .proof-events li { display:flex; gap:12px; align-items:flex-start; }
    .proof-events strong { font-size:13px; font-weight:600; }
    .proof-events small { font-size:11px; color:var(--ck-fg-3); }
    .proof-event-link { display:block; color:var(--ck-signal-cool); font-size:12px!important; padding-top:6px; text-decoration:underline; text-underline-offset:3px; }
    .proof-marker { flex-shrink:0; width:10px; height:10px; border-radius:50%; border:2px solid var(--ck-signal-cool); margin-top:5px; }
    li[data-state=blocked] .proof-marker,li[data-state=rejected] .proof-marker { border-color:var(--ck-signal-neg); }
    li[data-state=awaiting_human] .proof-marker,li[data-state=observed] .proof-marker { border-color:var(--ck-signal-warn); }
    .coverage-run-link { display:flex; padding:12px 14px; font-size:13px!important; justify-content:center; text-align:center; margin-top:22px; }
    .coverage-text-button { color:var(--ck-signal-cool); background:none; border:0; padding:4px 0; cursor:pointer; align-self:flex-start; font-size:12px!important; }
    .coverage-empty { padding:24px; border:1px solid var(--ck-stroke-2); background:var(--ck-bg-panel); border-radius:var(--radius-lg,10px); display:flex; gap:12px; flex-direction:column; align-items:flex-start; }
    .coverage-empty a { padding:10px 14px; font-size:13px; }
    @media(max-width:1100px) { .coverage-layout { grid-template-columns:1fr; } }
    @media(max-width:640px) { .coverage-heading { flex-direction:column; } .coverage-summary { gap:16px; padding:18px; } .coverage-summary>div { flex-direction:column; align-items:flex-start; gap:8px; } .coverage-summary strong { font-size:26px; } .coverage-panel { padding:16px; } .coverage h2 { font-size:23px; } }
  `],
})
export class SystemMandateCoverageComponent {
  readonly systemId = input.required<string>();
  private readonly api = inject(MandateApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly navigation = inject(ZoomContextService);
  readonly i18n = inject(I18nService);
  readonly data = signal<SystemMandate | null>(null);
  readonly loading = signal(false);
  readonly error = signal(false);
  readonly selectedRunId = signal('');
  readonly selectedRun = signal<RunMandate | null>(null);
  readonly selectedFacet = signal<MandateFacet | null>(null);
  readonly runLoading = signal(false);
  readonly runError = signal(false);
  readonly facets = MANDATE_FACETS;
  readonly recentRuns = computed(() => (this.data()?.recent_runs ?? []).slice(0, 4));
  readonly counts = computed(() => mandateCoverageCounts(this.recentRuns()));
  readonly events = computed(() => mandateFacetEvents(this.selectedRun()?.events ?? [], this.selectedFacet()));
  readonly cell = mandateCoverageCell;
  private systemRequest?: Subscription;
  private runRequest?: Subscription;
  private generation = 0;

  constructor() {
    const unregister = this.workspace.registerContextReset(() => this.reset());
    this.destroyRef.onDestroy(() => { unregister(); this.reset(); });
    effect(() => { this.systemId(); this.workspace.contextEpoch(); untracked(() => this.load()); });
  }

  t(key: string) { return this.i18n.t(`mandate_system.${key}`); }
  modeLabel(mode: string | null) { return this.t(`mode.${['compat', 'shadow', 'enforce'].includes(mode ?? '') ? mode : 'unknown'}`); }
  versionLabel(version: number | null) { return version == null ? '—' : this.i18n.t('mandate_system.version', {version}); }
  facetLabel(facet: string) { return this.t([...this.facets, 'human', 'delegation'].includes(facet) ? facet : 'other'); }
  eventLabel(event: MandateEvent) { return this.t(`event.${event.status}`); }
  eventTime(value: string | null) {
    if (!value) return this.t('no_time');
    const date = new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`);
    return Number.isNaN(date.getTime()) ? this.t('no_time')
      : new Intl.DateTimeFormat(this.i18n.locale(), {dateStyle: 'medium', timeStyle: 'short'}).format(date);
  }
  eventUrl(eventId: string) {
    const tree = this.navigation.objectUrlTree('run', this.selectedRunId(), {lens: 'govern'});
    tree.queryParams = {...tree.queryParams, mandateEvent: eventId};
    return tree;
  }
  cellLabel(run: MandateCoverageRun, facet: MandateFacet) {
    const cell = mandateCoverageCell(run, facet);
    return this.i18n.t('mandate_system.cell', {facet: this.t(facet), run: run.run_id.slice(0, 8), state: this.t(cell.state === 'recorded' ? 'record' : cell.state), count: cell.count});
  }

  load(): void {
    this.reset();
    const id = this.systemId();
    if (!id) return;
    const generation = this.generation;
    const scope = this.workspace.captureRequestScope();
    this.loading.set(true);
    this.systemRequest = this.api.system(id, scope).subscribe({
      next: data => {
        if (generation !== this.generation || !this.workspace.isRequestScopeCurrent(scope) || id !== this.systemId()) return;
        this.loading.set(false);
        if (data.system_id !== id) { this.error.set(true); return; }
        this.data.set(data);
        const requested = this.route.snapshot.queryParamMap.get('mandateRun');
        const selected = data.recent_runs.slice(0, 4).find(run => run.run_id === requested) ?? data.recent_runs[0];
        const facet = this.route.snapshot.queryParamMap.get('mandateFacet') as MandateFacet | null;
        if (selected) this.selectRun(selected.run_id, this.facets.includes(facet as MandateFacet) ? facet : null, false);
      },
      error: () => {
        if (generation !== this.generation || !this.workspace.isRequestScopeCurrent(scope) || id !== this.systemId()) return;
        this.error.set(true); this.loading.set(false);
      },
    });
  }

  selectRun(runId: string, facet: MandateFacet | null = null, updateUrl = true): void {
    if (!runId || !this.recentRuns().some(run => run.run_id === runId)) return;
    this.runRequest?.unsubscribe();
    this.selectedRunId.set(runId); this.selectedFacet.set(facet);
    this.selectedRun.set(null); this.runError.set(false); this.runLoading.set(true);
    if (updateUrl) void this.router.navigate([], {relativeTo: this.route, queryParams: {mandateRun: runId, mandateFacet: facet}, queryParamsHandling: 'merge', replaceUrl: true});
    const id = this.systemId();
    const generation = this.generation;
    const scope = this.workspace.captureRequestScope();
    this.runRequest = this.api.run(runId, scope).subscribe({
      next: run => {
        if (generation !== this.generation || !this.workspace.isRequestScopeCurrent(scope) || id !== this.systemId() || this.selectedRunId() !== runId) return;
        this.runLoading.set(false);
        if (run.run_id !== runId || run.system_id !== id) { this.runError.set(true); return; }
        this.selectedRun.set(run);
      },
      error: () => {
        if (generation !== this.generation || !this.workspace.isRequestScopeCurrent(scope) || id !== this.systemId() || this.selectedRunId() !== runId) return;
        this.runError.set(true); this.runLoading.set(false);
      },
    });
  }

  private reset(): void {
    this.generation++;
    this.systemRequest?.unsubscribe(); this.runRequest?.unsubscribe();
    this.data.set(null); this.selectedRun.set(null); this.selectedRunId.set(''); this.selectedFacet.set(null);
    this.loading.set(false); this.runLoading.set(false); this.error.set(false); this.runError.set(false);
  }
}
