import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit/nav-link.directive';
import { formatSkillCost } from '../skills/skill-cost';
import { MandateApiService } from './mandate-api.service';
import { mandateReviewConfigured, type SystemMandate } from './mandate.models';

@Component({
  selector: 'app-system-mandate', standalone: true, imports: [NavLinkDirective],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
  <section class="mandate" [class.compact]="compact()" [attr.aria-label]="i18n.t('mandate.title')">
    <header><div><span class="eyebrow">{{i18n.t(data()?.configuration?.policy_binding === 'frozen' ? 'mandate.published_configuration' : 'mandate.configuration')}}@if(data()?.configuration?.policy_binding === 'frozen' && data()?.configuration?.published_version_number != null){ · {{i18n.t('mandate.version',{version:data()!.configuration.published_version_number!})}}}</span><h3>{{i18n.t('mandate.title')}}</h3></div>
      @if(data()?.configuration?.mode; as mode){<span class="mode">{{i18n.t('mandate.mode.' + mode)}}</span>}
    </header>
    @if(loading()){<p role="status">{{i18n.t('mandate.loading')}}</p>}
    @else if(error()){<p role="alert">{{i18n.t('mandate.load_failed')}}</p><button type="button" (click)="reload.update(increment)">{{i18n.t('common.retry')}}</button>}
    @else if(data(); as value){
      @if(value.configuration.state === 'invalid'){<p class="warning">{{i18n.t('mandate.invalid')}}</p>}
      @else if(!value.configuration.spec){<p>{{i18n.t('mandate.no_spec')}}</p>}
      @else {
        <p class="explanation">{{i18n.t(value.configuration.policy_binding === 'frozen' ? 'mandate.published_configuration_hint' : 'mandate.configuration_hint')}}</p>
        @if(compact()){
          <div class="quick-scope">
            @for(scope of summaryScopes();track scope.key){<p><strong>{{i18n.t(scope.key)}}</strong> {{scopePreview(scope)}}@if(scope.values.length > 2){ · +{{scope.values.length - 2}}}</p>}
            @if(reviewConfigured()){<p class="review-preview"><strong>{{i18n.t(blockingIntent() ? 'mandate.agreement' : 'mandate.review_configuration')}}</strong> {{i18n.t(value.configuration.spec.outbound?.expert_review_required ? 'mandate.review_required' : 'mandate.review_threshold',{value: percent(reviewThreshold() || 0)})}}</p>}
          </div>
          @if(value.configuration.mode && value.configuration.mode !== 'enforce'){<p class="muted">{{i18n.t('mandate.mode.' + value.configuration.mode + '_hint')}}</p>}
        }
        <details [open]="!compact()">
          <summary>{{i18n.t('mandate.details')}}</summary>
          <div class="rules">
            <div class="rule-group"><h4>{{i18n.t('mandate.can')}}</h4>
              @for(scope of scopes();track scope.key){
                <div class="scope"><span>{{i18n.t(scope.key)}}</span>
                  @if(scope.values.length){<ul>@for(value of scope.values;track $index){<li [title]="value">{{referenceLabel(scope.key, value)}}</li>}</ul>}
                  @else{<p class="muted">{{i18n.t(scope.empty)}}</p>}
                </div>
              }
            </div>
            <div class="rule-group"><h4>{{i18n.t(blockingIntent() && reviewConfigured() ? 'mandate.agreement' : 'mandate.review_configuration')}}</h4>
              <p>{{i18n.t(value.configuration.state !== 'explicit' ? 'mandate.review_derived' : reviewConfigured() && value.configuration.spec.outbound?.expert_review_required ? 'mandate.review_required' : 'mandate.review_other')}}</p>
              @if(reviewConfigured() && reviewThreshold() !== null){<p>{{i18n.t('mandate.review_threshold',{value: percent(reviewThreshold()!)})}}</p>}
              <h4>{{i18n.t('mandate.boundary')}}</h4>
              @if(value.configuration.configured_facets?.includes('inbound') && value.configuration.spec.inbound?.reject_cross_project_sources){<p>{{i18n.t('mandate.cross_project')}}</p>}
              @if(value.configuration.configured_facets?.includes('provenance') && value.configuration.spec.provenance?.require_citations){<p>{{i18n.t('mandate.citations')}}</p>}
              <dl class="budgets">
                @if(value.configuration.spec.valves?.max_cost_per_decision != null){<div><dt>{{i18n.t('mandate.cost_limit')}}</dt><dd>{{cost(value.configuration.spec.valves!.max_cost_per_decision!)}}</dd></div>}
                @if(value.configuration.spec.valves?.max_latency_ms != null){<div><dt>{{i18n.t('mandate.duration_limit')}}</dt><dd>{{i18n.t('mandate.seconds',{value: value.configuration.spec.valves!.max_latency_ms! / 1000})}}</dd></div>}
                @if(value.configuration.spec.valves?.token_budget != null){<div><dt>{{i18n.t('mandate.token_limit')}}</dt><dd>{{number(value.configuration.spec.valves!.token_budget!)}}</dd></div>}
              </dl>
              @if(!hasBudget()){<p class="muted">{{i18n.t('mandate.no_budget')}}</p>}
            </div>
          </div>
          <p class="mode-hint">{{i18n.t('mandate.mode.' + (value.configuration.mode || 'compat') + '_hint')}}</p>
        </details>
      }
      <footer><span class="muted">{{i18n.t('mandate.config_state.' + value.configuration.state)}}@if(value.configuration.version != null){ · {{i18n.t('mandate.version',{version:value.configuration.version!})}} } </span>
        @if(runId() && advancedLinks()){<a [navLink]="{type:'run',ref:runId()!}">{{i18n.t('mandate.open_run')}}</a>}
        @if(advancedLinks()){<a [navLink]="{type:'system',ref:systemId(),lens:value.editing_supported && value.permissions.can_edit ? 'build' : undefined,facet:'context'}">{{i18n.t(value.editing_supported && value.permissions.can_edit ? 'mandate_system.editor.edit' : 'mandate.open_system')}}</a>}
      </footer>
    }
  </section>`,
  styleUrl: './system-mandate.component.css',
})
export class SystemMandateComponent {
  readonly systemId = input.required<string>();
  readonly runId = input<string | null>(null);
  readonly compact = input(false);
  readonly i18n = inject(I18nService);
  private readonly api = inject(MandateApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly profile = inject(NavigationProfileService);
  readonly advancedLinks = computed(() => { const profile = this.profile.effective(); return !profile.active || profile.advancedAccess === 'link' || profile.advancedAccess === 'admin_only' && profile.admin; });
  readonly blockingIntent = computed(() => {const config = this.data()?.configuration;return config?.state === 'explicit' && config.version === 2 && config.mode === 'enforce';});
  readonly reviewConfigured = computed(() => { const config = this.data()?.configuration; return config ? mandateReviewConfigured(config) : false; });
  readonly data = signal<SystemMandate | null>(null);
  readonly loading = signal(false);
  readonly error = signal(false);
  readonly reload = signal(0);
  readonly increment = (value: number) => value + 1;
  readonly scopes = computed(() => {
    const value = this.data()?.configuration; const spec = value?.spec;
    return [
      {key:'mandate.sources',values:spec?.inbound?.collection_allowlist || [],empty:'mandate.no_list'},
      {key:'mandate.skills',values:spec?.capabilities?.allowed_skills || [],empty:'mandate.no_list'},
      {key:'mandate.models',values:spec?.capabilities?.allowed_models || [],empty:'mandate.no_list'},
      {key:'mandate.actions',values:spec?.capabilities?.allowed_actions || [],empty:'mandate.no_list'},
      {key:'mandate.delegations',values:(spec?.capabilities?.allowed_delegations || []).map(rule => typeof rule === 'string' ? rule : rule.system_id),empty:value?.state === 'explicit' && value.version === 2 && value.mode === 'enforce' ? 'mandate.no_delegation' : 'mandate.no_list'},
    ];
  });
  readonly summaryScopes = computed(() => this.scopes().filter(scope => scope.values.length > 0).slice(0,2));
  readonly reviewThreshold = computed(() => {
    const spec = this.data()?.configuration.spec;
    const thresholds = [spec?.outbound?.gate_if_confidence_below, spec?.valves?.mandatory_hitl_if_confidence_below].filter((value): value is number => value != null);
    return thresholds.length ? Math.max(...thresholds) : null;
  });
  readonly hasBudget = computed(() => {
    const valves = this.data()?.configuration.spec?.valves;
    return valves?.max_cost_per_decision != null || valves?.max_latency_ms != null || valves?.token_budget != null;
  });
  constructor() {
    effect(onCleanup => {
      this.reload(); const id = this.systemId(); const scope = this.workspace.captureRequestScope();
      this.data.set(null); this.error.set(false); this.loading.set(Boolean(id));
      if (!id || !scope.workspaceId) { this.loading.set(false); return; }
      const subscription = this.api.system(id, scope).subscribe({
        next: value => { if (this.workspace.isRequestScopeCurrent(scope) && this.systemId() === id && value.system_id === id) {this.data.set(value);this.loading.set(false);} },
        error: () => { if (this.workspace.isRequestScopeCurrent(scope) && this.systemId() === id) {this.data.set(null);this.error.set(true);this.loading.set(false);} },
      });
      onCleanup(() => subscription.unsubscribe());
    });
  }
  number(value: number): string { return new Intl.NumberFormat(this.i18n.locale()).format(value); }
  referenceLabel(key: string, value: string): string {
    const labels = this.data()?.reference_labels;
    return (key === 'mandate.skills' ? labels?.skills?.[value]
      : key === 'mandate.delegations' ? labels?.delegations?.[value] : null) || value;
  }
  scopePreview(scope: { key: string; values: string[] }): string {
    return scope.values.slice(0, 2).map(value => this.referenceLabel(scope.key, value)).join(' · ');
  }
  percent(value: number): string { return new Intl.NumberFormat(this.i18n.locale(),{style:'percent',maximumFractionDigits:1}).format(value); }
  cost(value: number): string { return formatSkillCost(value, 'USD', this.i18n.locale()); }
}
