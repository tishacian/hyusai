import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import type { Skill } from '@app/core/canonical-api.service';
import { judgeGraphSources, judgeOutputPaths, nextRubricVersion } from './typed-judge-guidance';
import { changeQuestionType, newQuestion, JUDGE_BUDGET_LIMITS, validateJudgeDraft, type QuestionType, type TypedJudgeDraft, type TypedQuestion } from './dataops.models';

@Component({
  selector: 'app-typed-judge-editor', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush, styleUrl: './dataops-editor.scss',
  template: `
    <p class="dp-note">{{ i18n.t('dataops.judge.contract_hint') }}</p>
    <p class="dp-note">{{ i18n.t('flow.judge.guidance.identity') }} · {{ value().rubric_id }} · {{ value().rubric_version }}</p>
    <button type="button" class="dp-button" (click)="rubric('rubric_version', nextVersion())">{{ i18n.t('flow.judge.guidance.next', { version: nextVersion() }) }}</button>
    <details><summary>{{ i18n.t('dataops.advanced') }}</summary>
      <div class="dp-grid">@for (field of rubricFields; track field) {
        <label class="dp-field"><span>{{ i18n.t('dataops.judge.' + field) }}</span><input class="dp-input" [value]="value()[field]" (input)="rubric(field, val($event))" /></label>
      }</div>
      <label class="dp-field"><span>{{ i18n.t('flow.judge.guidance.json') }}</span><textarea class="dp-input" rows="8" [value]="jsonValue()" (change)="applyJson(val($event))"></textarea></label>
      @if (jsonError()) { <p class="dp-error" role="alert">{{ i18n.t('flow.judge.guidance.invalid_json') }}</p> }
    </details>
    <details class="dp-section"><summary>{{ i18n.t('dataops.judge.run_evidence') }}</summary>
      <p class="dp-note">{{ i18n.t('dataops.judge.run_evidence_hint') }}</p>
      <label class="dp-check"><input type="checkbox" [checked]="!!value().run_evidence" (change)="runEvidence(checked($event))" />{{ i18n.t('dataops.judge.run_evidence_enable') }}</label>
      @if (value().run_evidence; as binding) {
        @for (source of binding.sources; track $index; let n = $index) {
          <section class="dp-section">
            <label class="dp-field"><span>{{ i18n.t('dataops.judge.evidence_id') }}</span><input class="dp-input" [value]="source.id" (input)="evidenceField(n, 'id', val($event))" /></label>
            <label class="dp-field"><span>{{ i18n.t('dataops.judge.evidence_skill') }}</span><select class="dp-input" [value]="source.skill_slug" (change)="selectEvidenceSkill(n, val($event))"><option value="">{{ i18n.t('flow.judge.guidance.choose') }}</option>@for (slug of sourceSkills(); track slug) { <option [value]="slug">{{ skillName(slug) }}</option> }</select></label>
            <label class="dp-field"><span>{{ i18n.t('dataops.judge.evidence_node') }}</span><select class="dp-input" [value]="source.node_id ?? ''" (change)="evidenceField(n, 'node_id', val($event))"><option value="">{{ i18n.t('flow.judge.guidance.choose') }}</option>@for (node of sourceNodes(source.skill_slug); track node.nodeId) { <option [value]="node.nodeId">{{ node.label }}</option> }</select></label>
            @if (hasOutputContract(source.skill_slug)) {
              <label class="dp-field"><span>{{ i18n.t('dataops.judge.evidence_paths') }}</span><select class="dp-input" multiple (change)="selectEvidencePaths(n, selected($event))">@for (path of outputPaths(source.skill_slug); track path) { <option [value]="path" [selected]="source.paths.includes(path)">{{ path }}</option> }</select></label>
            } @else {
              <p class="dp-note">{{ i18n.t('flow.judge.guidance.free_path') }}</p>
              <label class="dp-field"><span>{{ i18n.t('dataops.judge.evidence_paths') }}</span><textarea class="dp-input" rows="3" [value]="source.paths.join('\n')" (change)="evidencePaths(n, val($event))"></textarea></label>
            }
            <button type="button" class="dp-button" [disabled]="binding.sources.length <= 1" (click)="removeEvidence(n)">{{ i18n.t('dataops.remove') }}</button>
          </section>
        }
        <button type="button" class="dp-button" [disabled]="binding.sources.length >= 16" (click)="addEvidence()">{{ i18n.t('dataops.judge.add_evidence') }}</button>
        <p class="dp-note">{{ i18n.t('dataops.judge.evidence_native_hint') }}</p>
        @for (ref of binding.native_refs; track $index; let n = $index) {
          <div class="dp-row"><label class="dp-field"><span>{{ i18n.t('dataops.judge.evidence_asset_kind') }}</span><select class="dp-input" [value]="ref.kind" (change)="nativeField(n, 'kind', val($event))">@for (kind of nativeKinds; track kind) { <option [value]="kind">{{ i18n.t('dataops.asset_kind.' + kind) }}</option> }</select></label>
            <label class="dp-field"><span>{{ i18n.t('dataops.judge.evidence_asset_id') }}</span><input class="dp-input" [value]="ref.id" (input)="nativeField(n, 'id', val($event))" /></label>
            <button type="button" class="dp-button" (click)="removeNative(n)">{{ i18n.t('dataops.remove') }}</button></div>
        }
        <button type="button" class="dp-button" [disabled]="binding.native_refs.length >= 32" (click)="addNative()">{{ i18n.t('dataops.judge.add_native') }}</button>
      }
    </details>
    @for (question of value().questions; track $index; let n = $index) {
      <section class="dp-section"><div class="dp-row"><label class="dp-field"><span>{{ i18n.t('dataops.judge.key') }}</span><input class="dp-input" [value]="question.key" (input)="questionField(n, 'key', val($event))" /></label>
        <label class="dp-field"><span>{{ i18n.t('dataops.judge.type') }}</span><select class="dp-input" [value]="question.type" (change)="type(n, val($event))">@for (kind of types; track kind) { <option [value]="kind">{{ i18n.t('dataops.judge.type.' + kind) }}</option> }</select></label>
        <button type="button" class="dp-button" [disabled]="value().questions.length === 1" (click)="remove(n)">{{ i18n.t('dataops.remove') }}</button></div>
        <label class="dp-field"><span>{{ i18n.t('dataops.judge.question') }}</span><textarea class="dp-input" rows="2" maxlength="2000" [value]="question.question" (input)="questionField(n, 'question', val($event))"></textarea></label>
        <div class="dp-row"><label class="dp-check"><input type="checkbox" [checked]="question.required" (change)="questionField(n, 'required', checked($event))" />{{ i18n.t('dataops.judge.required') }}</label>
          <label class="dp-check"><input type="checkbox" [checked]="question.requires_evidence" (change)="questionField(n, 'requires_evidence', checked($event))" />{{ i18n.t('dataops.judge.evidence_required') }}</label></div>
        @if (question.type === 'choice' || question.type === 'multi_choice') {
          @for (choice of question.choices; track $index; let c = $index) {
            <div class="dp-row"><label class="dp-field"><span>{{ i18n.t('dataops.judge.choice') }} {{ c + 1 }}</span><input class="dp-input" maxlength="120" [value]="choice" (input)="choiceValue(n, c, val($event))" /></label>
            <button type="button" class="dp-button" [disabled]="question.choices.length <= 2" (click)="removeChoice(n, c)">{{ i18n.t('dataops.remove') }}</button></div>
          }
          <button type="button" class="dp-button" [disabled]="question.choices.length >= 100" (click)="addChoice(n)">{{ i18n.t('dataops.judge.add_choice') }}</button>
          <label class="dp-field"><span>{{ i18n.t('dataops.judge.acceptable') }}</span><select class="dp-input" multiple (change)="questionField(n, 'acceptable_values', selected($event))">@for (choice of question.choices; track $index) { <option [value]="choice" [selected]="acceptable(question, choice)">{{ choice }}</option> }</select></label>
          <button type="button" class="dp-button" (click)="questionField(n, 'acceptable_values', null)">{{ i18n.t('dataops.judge.no_criterion') }}</button>
        }
        @if (question.type === 'boolean') {
          <label class="dp-field"><span>{{ i18n.t('dataops.judge.acceptable') }}</span><select class="dp-input" [value]="booleanCriterion(question)" (change)="booleanAcceptance(n, val($event))"><option value="">{{ i18n.t('dataops.judge.no_criterion') }}</option><option value="true">{{ i18n.t('dataops.yes') }}</option><option value="false">{{ i18n.t('dataops.no') }}</option></select></label>
        }
        @if (question.type === 'score' || question.type === 'probability') {
          <div class="dp-grid">@for (field of numericFields(question); track field) {
            <label class="dp-field"><span>{{ i18n.t('dataops.judge.' + field) }}</span><input class="dp-input" type="number" step="any" [value]="question[field] ?? ''" (input)="questionField(n, field, optionalNumber($event))" /></label>
          }</div>
        }
        <p class="dp-note">{{ i18n.t('dataops.judge.abstention') }}</p>
      </section>
    }
    <button type="button" class="dp-button" [disabled]="value().questions.length >= 32" (click)="add()">{{ i18n.t('dataops.judge.add_question') }}</button>
    @for (error of errors(); track error) { <p class="dp-error" role="status">{{ i18n.t(error) }}</p> }
    <section class="dp-section"><h3>{{ i18n.t('dataops.judge.budgets') }}</h3><p class="dp-note">{{ i18n.t('dataops.judge.budget_hint') }}</p><div class="dp-grid">
      @for (field of budgetFields; track field) { <label class="dp-field"><span>{{ i18n.t('dataops.judge.' + field) }}</span><input class="dp-input" type="number" [min]="budgetLimits[field].min" [max]="budgetLimits[field].max" [step]="budgetLimits[field].step" [value]="value().budget[field]" (input)="budget(field, number($event))" /></label> }
    </div></section>
    <section class="dp-section"><h3>{{ i18n.t('dataops.judge.tariff') }}</h3><div class="dp-grid">
      @for (field of tariffText; track field) { <label class="dp-field"><span>{{ i18n.t('dataops.judge.' + field) }}</span><input class="dp-input" [value]="value().tariff[field]" (input)="tariff(field, val($event))" /></label> }
      @for (field of tariffNumbers; track field) { <label class="dp-field"><span>{{ i18n.t('dataops.judge.' + field) }}</span><input class="dp-input" type="number" min="0" max="1000" step="any" [value]="value().tariff[field]" (input)="tariffNumber(field, number($event))" /></label> }
    </div></section>
  `,
})
export class TypedJudgeEditorComponent {
  readonly i18n = inject(I18nService); readonly value = input.required<TypedJudgeDraft>(); readonly valueChange = output<TypedJudgeDraft>();
  readonly graph = input<CanonicalFlowNode[]>([]);
  readonly nodeId = input('');
  readonly skills = input<Skill[]>([]);
  readonly sources = computed(() => judgeGraphSources(this.graph(), this.nodeId()));
  readonly sourceSkills = computed(() => [...new Set(this.sources().map(source => source.skillSlug))]);
  readonly nextVersion = computed(() => nextRubricVersion(this.value().rubric_version));
  readonly jsonValue = computed(() => JSON.stringify(this.value(), null, 2));
  readonly jsonError = signal(false);
  readonly types: QuestionType[] = ['boolean', 'choice', 'multi_choice', 'score', 'probability'];
  readonly rubricFields = ['rubric_id', 'rubric_version'] as const;
  readonly budgetFields = ['max_calls', 'max_tokens', 'max_cost_usd', 'max_output_tokens', 'timeout_s', 'max_prompt_bytes'] as const;
  readonly tariffText = ['provider', 'model', 'reference'] as const; readonly tariffNumbers = ['input_per_million', 'output_per_million'] as const;
  readonly budgetLimits = JUDGE_BUDGET_LIMITS;
  readonly nativeKinds = ['document_set', 'dataset', 'model'] as const;
  readonly errors = computed(() => [
    ...validateJudgeDraft(this.value()),
    ...(this.value().run_evidence?.sources.some(source => this.hasOutputContract(source.skill_slug) && source.paths.some(path => !this.outputPaths(source.skill_slug).includes(path))) ? ['flow.judge.guidance.invalid_path'] : []),
  ]);
  sourceNodes(slug: string) { return this.sources().filter(source => source.skillSlug === slug); }
  skillName(slug: string): string { return this.skills().find(skill => skill.slug === slug)?.name ?? slug; }
  hasOutputContract(slug: string): boolean { const schema = this.skills().find(skill => skill.slug === slug)?.output_schema; return !!schema && Object.keys(schema).length > 0; }
  outputPaths(slug: string): string[] { return judgeOutputPaths(this.skills().find(skill => skill.slug === slug)?.output_schema); }
  selectEvidenceSkill(n: number, slug: string): void {
    if (!this.sourceSkills().includes(slug)) return;
    this.change(draft => { if (draft.run_evidence) draft.run_evidence.sources[n] = { ...draft.run_evidence.sources[n], skill_slug: slug, node_id: this.sourceNodes(slug)[0]?.nodeId ?? null, paths: [] }; });
  }
  selectEvidencePaths(n: number, paths: string[]): void {
    const slug = this.value().run_evidence?.sources[n]?.skill_slug;
    if (slug && paths.every(path => this.outputPaths(slug).includes(path))) this.evidencePaths(n, paths.join('\n'));
  }
  applyJson(raw: string): void {
    try {
      const draft = JSON.parse(raw) as TypedJudgeDraft;
      if (validateJudgeDraft(draft).length || draft.run_evidence?.sources.some(source => this.hasOutputContract(source.skill_slug) && source.paths.some(path => !this.outputPaths(source.skill_slug).includes(path)))) throw new Error('invalid');
      this.jsonError.set(false); this.valueChange.emit(draft);
    } catch { this.jsonError.set(true); }
  }
  val(event: Event): string { return (event.target as HTMLInputElement).value; }
  checked(event: Event): boolean { return (event.target as HTMLInputElement).checked; }
  number(event: Event): number { const text = this.val(event); return text.trim() ? Number(text) : Number.NaN; }
  optionalNumber(event: Event): number | null { return this.val(event) === '' ? null : this.number(event); }
  selected(event: Event): string[] { return Array.from((event.target as HTMLSelectElement).selectedOptions, o => o.value); }
  private change(fn: (draft: TypedJudgeDraft) => void): void { const next = structuredClone(this.value()); fn(next); this.valueChange.emit(next); }
  runEvidence(enabled: boolean): void { this.change(d => { if (enabled) d.run_evidence = {sources: [{id: 'proposal', skill_slug: '', paths: [], required: true}], native_refs: []}; else delete d.run_evidence; }); }
  evidenceField(n: number, key: 'id'|'skill_slug'|'node_id', value: string): void { this.change(d => { if (d.run_evidence) d.run_evidence.sources[n] = {...d.run_evidence.sources[n], [key]: key === 'node_id' && !value ? null : value}; }); }
  evidencePaths(n: number, value: string): void { this.change(d => { if (d.run_evidence) d.run_evidence.sources[n].paths = value.split('\n').map(path => path.trim()).filter(Boolean); }); }
  addEvidence(): void { this.change(d => { if (d.run_evidence && d.run_evidence.sources.length < 16) d.run_evidence.sources.push({id: '', skill_slug: '', paths: [], required: true}); }); }
  removeEvidence(n: number): void { this.change(d => { if (d.run_evidence && d.run_evidence.sources.length > 1) d.run_evidence.sources.splice(n, 1); }); }
  nativeField(n: number, key: 'kind'|'id', value: string): void { this.change(d => { if (d.run_evidence) d.run_evidence.native_refs[n] = {...d.run_evidence.native_refs[n], [key]: value}; }); }
  addNative(): void { this.change(d => { if (d.run_evidence && d.run_evidence.native_refs.length < 32) d.run_evidence.native_refs.push({kind: 'document_set', id: ''}); }); }
  removeNative(n: number): void { this.change(d => { d.run_evidence?.native_refs.splice(n, 1); }); }
  questionField(index: number, key: keyof TypedQuestion, value: unknown): void { this.change(d => { d.questions[index] = { ...d.questions[index], [key]: value }; }); }
  type(index: number, type: string): void { this.change(d => { d.questions[index] = changeQuestionType(d.questions[index], type as QuestionType); }); }
  add(): void { if (this.value().questions.length >= 32) return; this.change(d => { let n = d.questions.length + 1; while (d.questions.some(q => q.key === `question_${n}`)) n++; d.questions.push(newQuestion(`question_${n}`)); }); }
  remove(index: number): void { this.change(d => d.questions.splice(index, 1)); }
  choiceValue(index: number, choice: number, value: string): void { this.change(d => { const old = d.questions[index].choices[choice]; d.questions[index].choices[choice] = value; d.questions[index].acceptable_values = d.questions[index].acceptable_values?.map(v => v === old ? value : v); }); }
  addChoice(index: number): void { if (this.value().questions[index].choices.length >= 100) return; this.change(d => d.questions[index].choices.push('')); }
  removeChoice(index: number, choice: number): void { this.change(d => { const [old] = d.questions[index].choices.splice(choice, 1); d.questions[index].acceptable_values = d.questions[index].acceptable_values?.filter(v => v !== old); }); }
  acceptable(question: TypedQuestion, value: string): boolean { return question.acceptable_values?.includes(value) ?? false; }
  booleanCriterion(question: TypedQuestion): string { return question.acceptable_values?.length === 1 ? String(question.acceptable_values[0]) : ''; }
  booleanAcceptance(index: number, value: string): void { this.questionField(index, 'acceptable_values', value === '' ? null : [value === 'true']); }
  numericFields(question: TypedQuestion): Array<'minimum' | 'maximum' | 'accept_minimum' | 'accept_maximum'> { return question.type === 'score' ? ['minimum', 'maximum', 'accept_minimum', 'accept_maximum'] : ['accept_minimum', 'accept_maximum']; }
  rubric(key: 'rubric_id' | 'rubric_version', value: string): void { this.change(d => { d[key] = value; }); }
  budget(key: keyof TypedJudgeDraft['budget'], value: number): void { this.change(d => { d.budget[key] = value; }); }
  tariff(key: 'provider' | 'model' | 'reference', value: string): void { this.change(d => { d.tariff[key] = value; }); }
  tariffNumber(key: 'input_per_million' | 'output_per_million', value: number): void { this.change(d => { d.tariff[key] = value; }); }
}
