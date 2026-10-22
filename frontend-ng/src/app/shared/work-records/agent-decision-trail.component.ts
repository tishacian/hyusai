import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import type { Run } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { ModelExecutionComponent } from '@app/shared/cockpit/model-execution.component';
import { agentDecisionTrail, agentToolLabel, type AgentChoice } from './agent-decision-trail';

/** Read-only, reusable explanation of recorded tool choices. Never initiates
 * model calls, changes a decision or treats planner prose as an action result. */
@Component({
  selector: 'app-agent-decision-trail', standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgTemplateOutlet, NavLinkDirective, ModelExecutionComponent],
  styleUrl: './agent-decision-trail.scss',
  template: `
    @if (choices().length) {
      <section class="agent-choices" data-testid="agent-decision-trail" [attr.aria-label]="i18n.t('experience.agent_choices.title')">
        <header class="agent-choices-heading"><h3>{{ i18n.t('experience.agent_choices.title') }}</h3><span class="agent-choices-count">{{ choices().length }}</span></header>
        <p class="agent-choices-intro">{{ i18n.t('experience.agent_choices.description') }}</p>
        @if (compact()) {
          @if (latest(); as choice) { <ng-container [ngTemplateOutlet]="choiceCard" [ngTemplateOutletContext]="{ $implicit: choice }" /> }
          @if (previous().length) {
            <details class="agent-choices-history"><summary>{{ i18n.t(previous().length === 1 ? 'experience.agent_choices.previous_one' : 'experience.agent_choices.previous', { count: previous().length }) }}</summary>
              <ol class="agent-choices-list">@for (choice of previous(); track choice.id) {
                <li><ng-container [ngTemplateOutlet]="choiceCard" [ngTemplateOutletContext]="{ $implicit: choice }" /></li>
              }</ol>
            </details>
          }
        } @else {
          <ol class="agent-choices-list">@for (choice of choices(); track choice.id) {
            <li><ng-container [ngTemplateOutlet]="choiceCard" [ngTemplateOutletContext]="{ $implicit: choice }" /></li>
          }</ol>
        }
      </section>
    }
    <ng-template #choiceCard let-choice>
      <article class="agent-choice" [attr.data-state]="choice.state" [attr.data-choice-id]="choice.id">
        <div class="agent-choice-top"><span class="agent-choice-number">{{ choice.number }}</span><div class="agent-choice-title">
          <span class="agent-choice-eyebrow">{{ i18n.t('experience.agent_choices.choice') }}</span><h4>{{ heading(choice) }}</h4>
        </div><span class="agent-choice-state">{{ i18n.t('experience.agent_choices.state.' + choice.state) }}</span></div>
        @if (choice.normalized) { <p class="agent-choice-reserve">{{ i18n.t('experience.agent_choices.normalized') }}</p> }
        @if (choice.rationale) { <p class="agent-choice-rationale">{{ choice.rationale }}</p> }
        @else if (choice.state !== 'deciding') { <p class="agent-choice-muted">{{ i18n.t('experience.agent_choices.reason_unknown') }}</p> }
        @if (choice.invocationId && showLinks()) { <a class="agent-choice-link" [navLink]="{ type: 'skill_invocation', ref: choice.invocationId }">{{ i18n.t('experience.agent_choices.open_execution') }} →</a> }
        <details class="agent-choice-evidence"><summary>{{ i18n.t('experience.agent_choices.evidence') }}</summary>
          <div class="agent-choice-evidence-body">
            @if (choice.model) { <app-model-execution [resolution]="choice.model" /> }
            @else { <p class="agent-choice-muted">{{ i18n.t('experience.agent_choices.model_unknown') }}</p> }
            @if (choice.context; as context) {
              <h5>{{ i18n.t('experience.agent_choices.context') }}</h5>
              @if (context.fields.length) { <ul class="agent-choice-context">@for (field of context.fields; track field.key) {
                <li><div><code>{{ field.key }}</code><span>{{ i18n.t(field.present ? 'experience.agent_choices.context_present' : 'experience.agent_choices.context_missing') }}</span></div>
                  @if (field.source) { <small>{{ i18n.t('experience.agent_choices.source') }} · {{ field.source }}</small> }
                </li>
              }</ul> } @else { <p class="agent-choice-muted">{{ i18n.t('experience.agent_choices.context_empty') }}</p> }
              @if (context.sha256) { <p class="agent-choice-hash"><span>{{ i18n.t('experience.agent_choices.context_hash') }}</span><code>{{ context.sha256 }}</code></p> }
            } @else { <p class="agent-choice-muted">{{ i18n.t('experience.agent_choices.context_unknown') }}</p> }
            @if (choice.purpose) { <p class="agent-choice-purpose"><span>{{ i18n.t('experience.agent_choices.tool_purpose') }}</span>{{ choice.purpose }}</p> }
            <p class="agent-choice-muted agent-choice-explanation">{{ i18n.t('experience.agent_choices.explanation_notice') }}</p>
          </div>
        </details>
      </article>
    </ng-template>
  `,
})
export class AgentDecisionTrailComponent {
  readonly i18n = inject(I18nService);
  readonly run = input<Run | null>(null);
  /** Translation keys supplied by a business application, without specialising the projection. */
  readonly toolLabels = input<Record<string, string>>({});
  readonly compact = input(false);
  readonly showLinks = input(false);
  readonly choices = computed(() => agentDecisionTrail(this.run()));
  readonly latest = computed(() => this.choices().at(-1) ?? null);
  readonly previous = computed(() => this.choices().slice(0, -1));

  heading(choice: AgentChoice): string {
    if (choice.skill) return this.toolLabels()[choice.skill] ? this.i18n.t(this.toolLabels()[choice.skill]) : agentToolLabel(choice.skill);
    return this.i18n.t('experience.agent_choices.state.' + choice.state);
  }
}
