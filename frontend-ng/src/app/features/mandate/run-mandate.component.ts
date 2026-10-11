import { JsonPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { switchMap, takeWhile, timer } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit/nav-link.directive';
import { MandateApiService } from './mandate-api.service';
import { mandateInitialEvent, mandateLane, mandateRunSummary, mandateSnapshotNote, type MandateEvent, type RunMandate } from './mandate.models';

@Component({
  selector: 'app-run-mandate', standalone: true, imports: [JsonPipe, NavLinkDirective],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
  <section class="run-mandate" [class.compact]="compact()" [attr.aria-label]="i18n.t('mandate.run.title')">
    <header><div><span class="eyebrow">{{i18n.t('mandate.run.title')}}</span>
      @if(data(); as value){<h2 [class.stop]="summary() === 'blocked'" [class.wait]="summary() === 'awaiting_human'">{{headline()}}</h2>}
      @else{<h2>{{i18n.t(error() ? 'mandate.run.title' : 'mandate.run.loading')}}</h2>}
    </div>
    @if(advancedLinks()){<a [navLink]="{type:'run',ref:runId()}">{{i18n.t('mandate.open_run')}}</a>}</header>
    @if(error()){<p role="alert">{{i18n.t('mandate.run.load_failed')}}</p><button type="button" (click)="reload.update(increment)">{{i18n.t('common.retry')}}</button>}
    @else if(data(); as value){
      @if(snapshotNote(); as note){<p class="snapshot-note">{{i18n.t(note)}}</p>}
      @if(!value.events.length){<p class="muted">{{i18n.t('mandate.run.no_evidence_hint')}}</p>}
      @else{
        @if(compact()){
          @if(selected(); as event){<p class="summary-reason"><strong>{{eventLabel(event)}}</strong> · {{i18n.t('mandate.status.' + event.status)}}@if(event.rule){<span>{{ruleLabel(event.rule)}}</span>}</p>}
        }@else{<p class="intro">{{i18n.t('mandate.run.intro')}}</p>}
        <details class="inspection" [open]="!compact()">
          <summary>{{i18n.t('mandate.run.inspect')}}</summary>
          <div class="applied">
            <div><span>{{i18n.t(value.applied.spec ? value.applied.policy_binding === 'frozen' ? 'mandate.run.frozen_applied' : 'mandate.run.applied' : value.limitations.includes('no_policy_at_first_start') ? 'mandate.run.no_policy' : 'mandate.run.snapshot_missing')}}</span>
              <strong>{{i18n.t('mandate.mode.' + (value.applied.mode || 'unknown'))}}@if(value.applied.version != null){ · {{i18n.t('mandate.version',{version:value.applied.version!})}} } </strong>
            </div>
            @if(advancedLinks()){<a [navLink]="{type:'system',ref:value.system_id,facet:'context'}">{{i18n.t('mandate.open_system')}}</a>}
          </div>
          <div class="investigation-grid">
            <div class="boundary" [attr.aria-label]="i18n.t('mandate.boundary')">
              @for(lane of lanes();track lane.id;let index=$index){
                <section class="lane"><div class="lane-heading"><span class="step">{{index + 1}}</span><h3>{{i18n.t('mandate.run.' + lane.id)}}</h3><span class="count">{{lane.events.length}}</span></div>
                  <div class="lane-events">
                    @for(event of lane.events;track event.id){
                      <button type="button" class="event" [class.selected]="selected()?.id === event.id" [class.blocked]="event.status === 'blocked' || event.status === 'rejected'" [class.held]="event.status === 'awaiting_human'" [class.delegation]="event.facet === 'delegation'" [attr.aria-pressed]="selected()?.id === event.id" (click)="select(event)">
                        <span class="event-mark" aria-hidden="true"></span><span class="event-label"><strong>{{eventLabel(event)}}</strong>@if(event.node_id){<span class="node">{{event.node_id}}</span>}<span class="status">{{i18n.t('mandate.status.' + event.status)}}</span></span>
                      </button>
                    }@empty{<p class="empty-lane">{{i18n.t('mandate.run.no_lane_event')}}</p>}
                  </div>
                </section>
              }
            </div>
            <aside class="evidence" aria-live="polite">
              @if(selected(); as event){
                <span class="eyebrow">{{i18n.t('mandate.run.selected')}}</span><h3>{{eventLabel(event)}}</h3>
                <span class="status-label" [class.stop]="event.status === 'blocked' || event.status === 'rejected'" [class.wait]="event.status === 'awaiting_human'">{{i18n.t('mandate.status.' + event.status)}}</span>
                <div class="rule"><h4>{{i18n.t('mandate.run.rule')}}</h4><p>{{ruleLabel(event.rule)}}</p></div>
                <dl>
                  @if(event.node_id){<div><dt>{{i18n.t('mandate.run.node')}}</dt><dd>{{event.node_id}}</dd></div>}
                  @if(event.at){<div><dt>{{i18n.t('mandate.run.recorded_at')}}</dt><dd>{{dateLabel(event.at)}}</dd></div>}
                  @if(event.decision_id){<div><dt>{{i18n.t('mandate.run.decision')}}</dt><dd>{{event.decision_id}}</dd></div>}
                </dl>
                @if(event.invocation_id && advancedLinks()){<a [navLink]="{type:'skill_invocation',ref:event.invocation_id,runId:runId()}">{{i18n.t('mandate.open_invocation')}}</a>}
                @if(event.child_run_id && advancedLinks()){<a [navLink]="{type:'run',ref:event.child_run_id}">{{i18n.t('mandate.open_child_run')}}</a>}
                @if(event.kind === 'hitl_approval'){<p class="muted">{{i18n.t('mandate.run.human_separate')}}</p>}
                <details><summary>{{i18n.t('mandate.run.technical')}}</summary><pre>{{event | json}}</pre></details>
              }
            </aside>
          </div>
          <p class="footnote">{{i18n.t('mandate.run.recorded_hint')}}</p>
        </details>
      }
    }
  </section>`,
  styleUrl: './run-mandate.component.css',
})
export class RunMandateComponent {
  readonly runId = input.required<string>();
  readonly compact = input(false);
  readonly i18n = inject(I18nService);
  private readonly api = inject(MandateApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly profile = inject(NavigationProfileService);
  readonly advancedLinks = computed(() => {const profile=this.profile.effective();return !profile.active || profile.advancedAccess === 'link' || profile.advancedAccess === 'admin_only' && profile.admin;});
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  readonly data = signal<RunMandate | null>(null);
  readonly error = signal(false);
  readonly selectedId = signal<string | null>(null);
  readonly reload = signal(0);
  readonly increment = (value: number) => value + 1;
  readonly summary = computed(() => this.data() ? mandateRunSummary(this.data()!) : 'not_recorded');
  readonly snapshotNote = computed(() => this.data() ? mandateSnapshotNote(this.data()!) : null);
  readonly selected = computed(() => mandateInitialEvent(this.data()?.events || [], this.selectedId()));
  readonly lanes = computed(() => (['sources','operations','review'] as const).map(id => ({id,events:(this.data()?.events || []).filter(event => mandateLane(event) === id)})));
  readonly headline = computed(() => this.i18n.t({blocked:'mandate.run.stopped',awaiting_human:'mandate.run.awaiting',recorded:'mandate.run.recorded',not_recorded:'mandate.run.no_evidence'}[this.summary()], {count:this.data()?.events.length || 0}));
  constructor() {
    effect(onCleanup => {
      this.reload(); const id = this.runId(); const scope = this.workspace.captureRequestScope();
      this.data.set(null); this.error.set(false);
      this.selectedId.set(this.compact() ? null : this.route.snapshot.queryParamMap.get('mandateEvent'));
      if (!id || !scope.workspaceId) return;
      const subscription = timer(0,5000).pipe(
        switchMap(() => this.api.run(id,scope)),
        takeWhile(value => ['pending','running','waiting_subflows','hitl_pending','debug_pending'].includes(value.status),true),
      ).subscribe({
        next: value => {if(this.workspace.isRequestScopeCurrent(scope) && this.runId() === id && value.run_id === id) this.data.set(value);},
        error: () => {if(this.workspace.isRequestScopeCurrent(scope) && this.runId() === id) {this.data.set(null);this.error.set(true);}},
      });
      onCleanup(() => subscription.unsubscribe());
    });
    effect(onCleanup => {
      if(this.compact()) return;
      const subscription = this.route.queryParamMap.subscribe(params => this.selectedId.set(params.get('mandateEvent')));
      onCleanup(() => subscription.unsubscribe());
    });
  }
  eventLabel(event: MandateEvent): string {
    const key = `mandate.facet.${event.facet}`; const label = this.i18n.t(key);
    return label === key ? this.i18n.t('mandate.facet.unknown') : label;
  }
  dateLabel(value: string | null): string {
    if(!value) return '—';
    const date=new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`);
    return Number.isNaN(date.valueOf()) ? '—' : new Intl.DateTimeFormat(this.i18n.locale(),{dateStyle:'medium',timeStyle:'short'}).format(date);
  }
  ruleLabel(rule: string | null): string {
    if(!rule) return this.i18n.t('mandate.run.unknown_rule');
    const normalized=rule.replace(/^source\[\d+\]:/, '');const [code,...detail]=normalized.split(':');const key=`mandate.rule.${code}`;
    const label=this.i18n.t(key);return label === key ? rule : label + (detail.length ? ` · ${detail.join(':')}` : '');
  }
  select(event: MandateEvent): void {
    this.selectedId.set(event.id);
    if(!this.compact()) void this.router.navigate([], {relativeTo:this.route,queryParams:{mandateEvent:event.id},queryParamsHandling:'merge',replaceUrl:true});
  }
}
