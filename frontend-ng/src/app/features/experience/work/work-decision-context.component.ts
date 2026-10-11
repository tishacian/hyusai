import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import type { Run } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { workDecisionDate, workDecisionRows } from './work-decision';

@Component({
  selector: 'app-work-decision-context', standalone: true,
  imports: [NavLinkDirective], changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="decision-context" [attr.aria-label]="i18n.t('workMandate.review_scope')">
      <p class="eyebrow">{{ i18n.t('workMandate.review_scope') }}</p>
      <p>{{ i18n.t('workMandate.exact_decision') }}</p>
      <dl>
        <dt>{{ i18n.t('workMandate.decision') }}</dt><dd>{{ run().hitl?.decision_title || run().hitl?.prompt }}</dd>
        @if (run().hitl?.node_id; as node) { <dt>{{ i18n.t('workMandate.operation') }}</dt><dd>{{ node }}</dd> }
        @if (run().flow_sha256; as version) { <dt>{{ i18n.t('workMandate.executed_version') }}</dt><dd><code>{{ version }}</code></dd> }
        @if (run().hitl?.expires_at; as deadline) { <dt>{{ i18n.t('workMandate.deadline') }}</dt><dd>{{ date(deadline) }}</dd> }
      </dl>
      <details>
        <summary>{{ i18n.t('workMandate.submitted_context') }}</summary>
        @if (rows().length) {
          <dl class="payload">@for (row of rows(); track row.label) { <dt>{{ row.label }}</dt><dd>{{ row.value }}</dd> }</dl>
        } @else { <p>{{ i18n.t('workMandate.no_context') }}</p> }
      </details>
      <p class="next">{{ i18n.t('workMandate.after_approval') }}</p>
      @if (showRunLink()) { <a [navLink]="{type:'run',ref:run().id,lens:'operate',facet:'checkpoints'}">{{ i18n.t('workMandate.run_proof') }}</a> }
    </section>
  `,
  styles: [`:host{display:block}.decision-context{display:flex;flex-direction:column;gap:14px;padding:20px;border:1px solid var(--ck-stroke-2);border-left:3px solid var(--ck-signal-warn);border-radius:6px;background:var(--ck-bg-panel-hi);color:var(--ck-fg-1);font-size:14px;line-height:1.5}p{margin:0}.eyebrow{font-size:12px;font-weight:600;color:var(--ck-signal-warn)}dl{display:grid;grid-template-columns:minmax(110px,1fr) minmax(0,3fr);gap:10px 18px;margin:0}dt,.next{color:var(--ck-fg-3)}dd{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}code{font-size:12px}summary{cursor:pointer;color:var(--ck-signal-cool)}summary:focus-visible,a:focus-visible{outline:2px solid var(--ck-signal-cool);outline-offset:3px}.payload{padding-top:14px;font-size:12px}a{color:var(--ck-signal-cool)}@media(max-width:600px){.decision-context{padding:16px}dl{grid-template-columns:1fr;gap:4px}dd{padding-bottom:8px}}`],
})
export class WorkDecisionContextComponent {
  readonly i18n = inject(I18nService);
  readonly run = input.required<Run>();
  readonly showRunLink = input(true);
  readonly rows = computed(() => workDecisionRows(this.run()));
  date(value: string): string {
    const parsed = workDecisionDate(value);
    return Number.isFinite(parsed.getTime())
      ? new Intl.DateTimeFormat(this.i18n.locale(), { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
      : value;
  }
}
