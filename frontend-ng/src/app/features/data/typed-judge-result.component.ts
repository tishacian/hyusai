import { readableQuote } from './judge-evidence';
import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { I18nService } from '@app/core/i18n.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { qualityMessage, type QualityMessage } from '../observability/quality-messages';
import { typedDecisionObservation, typedJudgeFailure, typedResult, type TypedAnswer } from './dataops.models';
@Component({
  selector: 'app-typed-judge-result', standalone: true, imports: [NgTemplateOutlet, NavLinkDirective], changeDetection: ChangeDetectionStrategy.OnPush, styleUrl: './dataops-editor.scss',
  template: `@if (result(); as evaluation) {
    <section class="dp-section" data-testid="typed-judge-result"><h2>{{ heading() || i18n.t('dataops.judge.result') }}</h2>
      <ng-content select="[judgeReviewContext]" />
      <div class="dp-row judge-statuses"><span>{{ t('execution') }}: {{ evaluation.status === 'failed' ? t('technical') : i18n.t('dataops.status.' + evaluation.status) }}</span><span>{{ t('verdict') }}: {{ i18n.t(qualityLabel()) }}</span></div>
      @if (failure(); as failure) {
        <div class="judge-failure" role="status" data-testid="judge-failure">
          <h3>{{ i18n.t('dataops.judge.failure.title') }}</h3>
          <p>{{ i18n.t(failure.message) }}</p>
          @if (failure.question) { <p class="dp-note">{{ i18n.t('dataops.judge.failure.question') }}: {{ failure.question }}</p> }
          <p class="dp-note">{{ i18n.t(failure.action) }} {{ i18n.t('dataops.judge.failure.no_approval') }}</p>
        </div>
      }
      <p class="dp-note">{{ i18n.t('dataops.judge.review_required') }}</p>
      @if (failedQuestions().length) {
        <details class="judge-questions" data-testid="judge-failed-questions"><summary>{{ i18n.t('dataops.judge.failure.questions') }} · {{ failedQuestions().length }}</summary>
          <ol>@for (question of failedQuestions(); track $index) { <li class="dp-note">{{ question }}</li> }</ol>
        </details>
      }
      <ng-template #technical>
      @if (compact()) { <p class="dp-note">{{ i18n.t('dataops.judge.evaluation') }}: {{ i18n.t('dataops.status.' + evaluation.status) }}</p> }
      <p class="dp-note">{{ i18n.t('dataops.judge.confidence') }}: {{ evaluation.confidence == null ? i18n.t('dataops.unknown') : evaluation.confidence }}</p>
      @if (evaluation.confidence != null && evaluation.calibration; as calibration) { <p class="dp-note">{{calibration.scope}}</p> }
      <p class="dp-note">{{ i18n.t('dataops.judge.coverage', {answered: coverage('questions_answered'), total: coverage('questions_total'), images: coverage('images_examined'), imagesTotal: coverage('images_total')}) }}</p>
      <p class="dp-note">{{ i18n.t('dataops.judge.evidence_coverage', {examined: coverage('evidence_examined'), total: coverage('evidence_total')}) }} · {{ i18n.t('dataops.judge.unit_scope') }}</p>
      @if (evaluation.cost; as cost) { <p class="dp-note">{{ i18n.t('dataops.judge.cost') }}: {{ cost.amount == null ? i18n.t('dataops.unknown') : cost.amount }} {{ cost.currency }}</p> }
      </ng-template>
      @if (!compact()) { <ng-container [ngTemplateOutlet]="technical" /> }
      <ng-template #decision let-key="questionKey">
        @if (providerDecision(key); as native) {
          <details class="dp-section" data-testid="judge-provider-decision"><summary>{{ i18n.t('dataops.judge.provider_decision') }}</summary>
            @if (native.yes != null) { <p class="dp-note">{{ i18n.t('dataops.judge.provider_yes') }}: {{ percent(native.yes) }}</p> }
            @if (native.confidence != null) { <p class="dp-note">{{ i18n.t('dataops.judge.provider_confidence') }}: {{ percent(native.confidence) }}</p> }
            @for (option of native.distribution; track $index) { <p class="dp-note">{{ option.label }}: {{ percent(option.probability) }}</p> }
            <p class="dp-note">{{ i18n.t('dataops.judge.provider_decision_hint') }}</p>
          </details>
        }
      </ng-template>
      <ng-template #citation let-proof="proof">
        @if (proof.kind === 'image') { <p>{{ proof.description }}</p> }
        @else {
          @let read = readable(proof.quote);
          @if (read.fields.length) {
            <dl class="judge-proof-fields">@for (field of read.fields; track $index) { <div><dt>{{ field.label }}</dt><dd>{{ field.value }}</dd></div> }</dl>
          } @else { <p>{{ read.text }}</p> }
        }
      </ng-template>
      @for (entry of answers(); track entry.key) {
        @if (compact()) { <div class="dp-answer">
          <h3>{{ entry.question }}</h3><p class="dp-note">{{ i18n.t('dataops.status.' + entry.answer.status) }}@if (entry.answer.value != null) { · {{ display(entry.answer.value) }} }@if (entry.answer.reason) { · {{ reason(entry.answer.reason) }} }</p>
          <p class="dp-note">{{ explanation(entry.answer) }}</p>
          <ng-container [ngTemplateOutlet]="decision" [ngTemplateOutletContext]="{questionKey:entry.key}" />
          @if (entry.answer.evidence.length) { <details><summary>{{ i18n.t('dataops.judge.proofs') }} · {{ entry.answer.evidence.length }}</summary>
            @for (proof of entry.answer.evidence; track $index) { <blockquote><ng-container [ngTemplateOutlet]="citation" [ngTemplateOutletContext]="{ proof }" /><details class="judge-technical-proof"><summary>{{ i18n.t('dataops.judge.proof_technical') }}</summary><small>{{ proof.evidence_id }} · {{ proof.kind === 'image' ? proof.image_sha256 : sourceVersion(proof.evidence_id) }}</small>@if (proof.kind !== 'image' && readable(proof.quote).transformed) { <pre>{{ proof.quote }}</pre> }</details>
              @if (sourcePreview(proof); as source) {<details><summary>{{i18n.t('observability.assurance.source_context')}}</summary><p>{{source.before}}<mark>{{source.quote}}</mark>{{source.after}}</p></details>}
              @if (sourceInvocation(proof.evidence_id); as sourceId) { @if(runId()) { <p><a [navLink]="{type:'skill_invocation',runId:runId() || undefined,ref:sourceId}">{{t('invocation')}}</a></p> } }
            </blockquote> }
          </details> }
        </div> }
        @else { <details class="dp-section"><summary>{{ entry.question }} · {{ i18n.t('dataops.status.' + entry.answer.status) }} · {{ display(entry.answer.value) }}</summary>
        <p class="dp-note">{{ explanation(entry.answer) }}</p>@if (entry.answer.reason) { <p class="dp-note">{{ reason(entry.answer.reason) }}</p> }
        <ng-container [ngTemplateOutlet]="decision" [ngTemplateOutletContext]="{questionKey:entry.key}" />
        @for (proof of entry.answer.evidence; track $index) { <blockquote><ng-container [ngTemplateOutlet]="citation" [ngTemplateOutletContext]="{ proof }" /><details class="judge-technical-proof"><summary>{{ i18n.t('dataops.judge.proof_technical') }}</summary><small>{{ proof.evidence_id }} @if (proof.kind === 'image') { · {{ proof.image_sha256 }} · {{ display(proof.region) }} } @else { · {{ proof.start }}–{{ proof.end }} · {{ sourceVersion(proof.evidence_id) }} }</small>@if (proof.kind !== 'image' && readable(proof.quote).transformed) { <pre>{{ proof.quote }}</pre> }</details>
          @if (sourcePreview(proof); as source) {<details><summary>{{i18n.t('observability.assurance.source_context')}}</summary><p>{{source.before}}<mark>{{source.quote}}</mark>{{source.after}}</p></details>}
              @if (sourceInvocation(proof.evidence_id); as sourceId) { @if(runId()) { <p><a [navLink]="{type:'skill_invocation',runId:runId() || undefined,ref:sourceId}">{{t('invocation')}}</a></p> } }
        </blockquote> }
      </details> }
      }
      @if (compact()) { <details data-testid="judge-technical-details"><summary>{{ i18n.t('dataops.judge.technical_details') }}</summary><ng-container [ngTemplateOutlet]="technical" /></details> }
    </section>
  }`,
  styles: [`.judge-proof-fields{display:grid;gap:var(--ck-space-1);margin:0}.judge-proof-fields div{display:grid;grid-template-columns:minmax(120px,40%) 1fr;gap:var(--ck-space-2)}.judge-proof-fields dt{color:var(--ck-fg-3)}.judge-proof-fields dd{margin:0;overflow-wrap:anywhere}.judge-technical-proof{margin-top:var(--ck-space-2);font-size:12px;color:var(--ck-fg-3)}.judge-technical-proof pre{white-space:pre-wrap;overflow-wrap:anywhere;font-family:var(--ck-font-mono)}.judge-failure{margin:12px 0;padding:12px 14px;border-inline-start:2px solid var(--ck-signal-warn);background:var(--ck-bg-inset);border-radius:4px;overflow-wrap:anywhere}.judge-failure h3{margin:0 0 6px}.judge-failure p{margin:4px 0;font-size:12px;line-height:1.5}.judge-questions{margin:8px 0}.judge-questions ol{padding-inline-start:20px;list-style:decimal}.judge-questions li{margin:4px 0;overflow-wrap:anywhere}`],
})
export class TypedJudgeResultComponent {
  readonly readable = (quote: string | null | undefined) => readableQuote(quote, this.i18n.locale());
  providerDecision(key: string) { return typedDecisionObservation(this.result(), key); }
  percent(value: number): string { return `${Math.round(value * 1000) / 10} %`; }
  explanation(answer: TypedAnswer): string {
    const native = this.result()?.typed_decisions;
    return native?.protocol === 'typesafe-decisions-v1' && native.source === 'provider_reported'
      ? this.i18n.t('dataops.judge.native_explanation') : answer.explanation;
  }
  readonly i18n = inject(I18nService); readonly value = input<unknown>(null); readonly result = computed(() => typedResult(this.value()));
  readonly runId = input<string|null>(null); readonly invocationId = input<string|null>(null);
  readonly heading = input<string|null>(null);
  readonly evidenceSources = input<Array<{evidence_id:string;text?:string;sha256?:string;asset_ref?:{version?:number|string;digest?:string};invocation_id?:string|null}>>([]);
  t(key:QualityMessage):string{return qualityMessage(this.i18n,key);}
  sourceVersion(id:string):string{const source=this.evidenceSources().find(item=>item.evidence_id===id);return source?.asset_ref?.version!=null ? String(source.asset_ref.version) : source?.asset_ref?.digest || source?.sha256 || this.i18n.t('dataops.judge.source_version_unknown');}
  sourcePreview(proof:TypedAnswer['evidence'][number]):{before:string;quote:string;after:string}|null{const text=this.evidenceSources().find(item=>item.evidence_id===proof.evidence_id)?.text;const start=proof.start,end=proof.end;if(typeof text!=='string'||start==null||end==null||text.slice(start,end)!==proof.quote)return null;return {before:text.slice(Math.max(0,start-280),start),quote:proof.quote || '',after:text.slice(end,end+280)};}
  sourceInvocation(id:string):string|null{return this.evidenceSources().find(item=>item.evidence_id===id)?.invocation_id || this.invocationId();}
  readonly failure = computed(() => typedJudgeFailure(this.result()));
  readonly qualityLabel = computed(() => this.result()?.quality_status === 'failed' ? 'dataops.judge.criteria_failed' : 'dataops.status.' + this.result()?.quality_status);
  readonly failedQuestions = computed(() => {
    const questions = this.result()?.questions;
    return this.failure() && Array.isArray(questions) ? questions.flatMap(question => typeof question?.question === 'string' && question.question.trim() ? [question.question.slice(0, 2000)] : []) : [];
  });
  readonly compact = input(false);
  readonly answers = computed(() => Object.entries(this.result()?.answers ?? {}).filter(([,answer]) => !this.failure() || answer.status !== 'invalid').map(([key, answer]) => {
    const questions = this.result()?.questions;
    const label = Array.isArray(questions) ? questions.find(q => q && q.key === key)?.question : null;
    return { key, answer, question: typeof label === 'string' && label.trim() ? label.slice(0, 2000) : key };
  }));
  reason(value: string): string {
    return this.i18n.t(['insufficient_evidence', 'ambiguous', 'out_of_scope', 'unsupported_modality'].includes(value) ? 'dataops.judge.reason.' + value : 'dataops.judge.unavailable');
  }
  coverage(key: string): number | string { return this.result()?.coverage[key] ?? this.i18n.t('dataops.unknown'); }
  display(value: unknown): string { return value == null ? this.i18n.t('dataops.unknown') : typeof value === 'boolean' ? this.i18n.t(value ? 'dataops.yes' : 'dataops.no') : Array.isArray(value) ? value.join(', ') : String(value); }
}
