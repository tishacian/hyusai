import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import type { DatasetDto } from './data.service';
import { changePrepOperation, movePrepStep, PREP_ACTIONS, PREP_OPERATIONS, prepColumnsBefore, prepDraftPorts, type PrepAction, type PrepDraft, type PrepOperation } from './dataops.models';
import { prepNumber, prepStepDefaults } from './prep-fields';
import { PrepParamsComponent } from './prep-params.component';

@Component({
  selector: 'app-data-prep-editor', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PrepParamsComponent], styleUrl: './dataops-editor.scss',
  template: `
    <label class="dp-field"><span>{{ i18n.t('dataops.operation') }}</span><select class="dp-input" [value]="value().spec.operation" (change)="operation(val($event))">@for (op of operations; track op) { <option [value]="op">{{ i18n.t('dataops.operation.' + op) }}</option> }</select></label>
    <div class="dp-grid">@for (port of ports(); track port) {
      <div><label class="dp-field"><span>{{ i18n.t('dataops.input') }} · {{ port }}</span><select class="dp-input" [value]="value().inputs[port]?.dataset_id ?? ''" (change)="dataset(port, val($event))"><option value="">{{ i18n.t('dataops.choose') }}</option>@for (row of datasets(); track row.id) { <option [value]="row.id" [disabled]="row.status !== 'ready'">{{ row.name }} · v{{ row.version }}</option> }</select></label>@if (value().spec.operation === 'union' && port !== 'in_1' && port !== 'in_2') { <button type="button" class="dp-button" (click)="removeInput(port)">{{ i18n.t('dataops.remove') }}</button> }</div>
    }</div>
    @if (value().spec.operation === 'union') { <button type="button" class="dp-button" [disabled]="ports().length >= 16" (click)="addInput()">{{ i18n.t('dataops.add_input') }}</button> }
    <app-prep-params [kind]="value().spec.operation" [params]="value().spec.params" [columns]="columns()" [rightColumns]="rightColumns()" (paramsChange)="params($event)" />
    @if (value().spec.operation === 'split' || value().spec.operation === 'sample') {
      <label class="dp-field"><span>{{ i18n.t('dataops.seed') }}</span><input class="dp-input" type="number" min="0" max="2147483647" step="1" [value]="value().spec.seed" (input)="seed(number($event))" /></label>
    }
    @if (value().spec.operation === 'prepare') { <section class="dp-section"><h3>{{ i18n.t('dataops.steps') }}</h3>
      @for (step of value().spec.steps; track $index; let n = $index) {
        <div class="dp-section"><div class="dp-row"><label class="dp-field"><span>{{ i18n.t('dataops.step') }} {{ n + 1 }}</span><select class="dp-input" [value]="step.action" (change)="stepAction(n, val($event))">@for (action of actions; track action) { <option [value]="action">{{ i18n.t('dataops.step.' + action) }}</option> }</select></label>
          <button type="button" class="dp-button" [disabled]="n === 0" (click)="move(n, -1)" [attr.aria-label]="i18n.t('dataops.up')">↑</button>
          <button type="button" class="dp-button" [disabled]="n === value().spec.steps.length - 1" (click)="move(n, 1)" [attr.aria-label]="i18n.t('dataops.down')">↓</button>
          <button type="button" class="dp-button" (click)="remove(n)">{{ i18n.t('dataops.remove') }}</button></div>
          <app-prep-params [kind]="step.action" [params]="step.params" [columns]="columnsBefore(n)" (paramsChange)="stepParams(n, $event)" />
        </div>
      }
      <button type="button" class="dp-button" [disabled]="value().spec.steps.length >= 100" (click)="addStep()">{{ i18n.t('dataops.add_step') }}</button>
    </section> }
    <section class="dp-section"><h3>{{ i18n.t('dataops.outputs') }}</h3>
      @for (out of value().spec.outputs; track $index; let n = $index) {
        <div class="dp-row"><label class="dp-field"><span>{{ i18n.t('dataops.port') }}</span><input class="dp-input" [disabled]="value().spec.operation !== 'split'" [value]="out.port" (input)="outputField(n, 'port', val($event))" /></label>
        <label class="dp-field"><span>{{ i18n.t('dataops.output_name') }}</span><input class="dp-input" [value]="out.name" (input)="outputField(n, 'name', val($event))" /></label>
        <label class="dp-field"><span>{{ i18n.t('dataops.version_of') }}</span><select class="dp-input" [value]="out.append_version_of ?? ''" (change)="outputField(n, 'append_version_of', val($event))"><option value="">{{ i18n.t('dataops.new_dataset') }}</option>@for (row of datasets(); track row.id) { <option [value]="row.id">{{ row.name }} · v{{ row.version }}</option> }</select></label>
        @if (value().spec.operation === 'split') { <label class="dp-field"><span>{{ i18n.t('dataops.ratio') }}</span><input class="dp-input" type="number" min="0" max="1" step="0.01" [value]="ratio(n)" (input)="setRatio(n, number($event))" /></label><button type="button" class="dp-button" [disabled]="value().spec.outputs.length <= 2" (click)="removeOutput(n)">{{ i18n.t('dataops.remove') }}</button> }</div>
      }
      @if (value().spec.operation === 'split') { <button type="button" class="dp-button" [disabled]="value().spec.outputs.length >= 8" (click)="addOutput()">{{ i18n.t('dataops.add_output') }}</button> }
    </section>
  `,
})
export class DataPrepEditorComponent {
  readonly i18n = inject(I18nService); readonly value = input.required<PrepDraft>(); readonly datasets = input<DatasetDto[]>([]);
  readonly valueChange = output<PrepDraft>(); readonly operations = PREP_OPERATIONS; readonly actions = PREP_ACTIONS;
  readonly ports = computed(() => prepDraftPorts(this.value()));
  readonly columns = computed(() => this.datasetColumns(this.value().spec.operation === 'join' ? 'left' : this.ports()[0]));
  readonly rightColumns = computed(() => this.datasetColumns('right'));
  val(event: Event): string { return (event.target as HTMLInputElement).value; }
  number(event: Event): number { return prepNumber(this.val(event)) ?? Number.NaN; }
  private change(fn: (draft: PrepDraft) => void): void { const draft = structuredClone(this.value()); fn(draft); this.valueChange.emit(draft); }
  datasetColumns(port: string): string[] { return this.datasets().find(d => d.id === this.value().inputs[port]?.dataset_id)?.schema.map(c => c.name) ?? []; }
  columnsBefore(index: number): string[] {
    return prepColumnsBefore(this.value(), this.columns(), this.rightColumns(), index);
  }
  operation(value: string): void { this.valueChange.emit(changePrepOperation(this.value(), value as PrepOperation)); }
  dataset(port: string, id: string): void { this.change(d => { d.inputs[port] = { dataset_id: id }; }); }
  addInput(): void { if (this.value().spec.operation !== 'union' || this.ports().length >= 16) return; this.change(d => { let n = 3; while (d.inputs[`in_${n}`]) n++; d.inputs[`in_${n}`] = { dataset_id: '' }; }); }
  removeInput(port: string): void { this.change(d => { delete d.inputs[port]; }); }
  params(params: Record<string, unknown>): void { this.change(d => { d.spec.params = params; }); }
  seed(seed: number): void { this.change(d => { d.spec.seed = seed; }); }
  addStep(): void { if (this.value().spec.operation !== 'prepare' || this.value().spec.steps.length >= 100) return; this.change(d => d.spec.steps.push({ action: 'select', params: { columns: this.columnsBefore(d.spec.steps.length) } })); }
  remove(index: number): void { this.change(d => d.spec.steps.splice(index, 1)); }
  move(index: number, direction: -1 | 1): void { this.valueChange.emit(movePrepStep(this.value(), index, direction)); }
  stepAction(index: number, action: string): void { this.change(d => { d.spec.steps[index] = { action: action as PrepAction, params: prepStepDefaults(action) }; }); }
  stepParams(index: number, params: Record<string, unknown>): void { this.change(d => { d.spec.steps[index].params = params; }); }
  outputField(index: number, key: 'port' | 'name' | 'append_version_of', value: string): void { this.change(d => { if (key === 'append_version_of' && !value) delete d.spec.outputs[index][key]; else d.spec.outputs[index][key] = value; }); }
  ratio(index: number): number { return ((this.value().spec.params['ratios'] ?? []) as number[])[index] ?? 0; }
  setRatio(index: number, ratio: number): void { this.change(d => { const ratios = [...((d.spec.params['ratios'] ?? []) as number[])]; ratios[index] = ratio; d.spec.params['ratios'] = ratios; }); }
  addOutput(): void { this.change(d => { let n = 3; while (d.spec.outputs.some(out => out.port === `out_${n}`)) n++; d.spec.outputs.push({ port: `out_${n}`, name: '' }); d.spec.params['ratios'] = d.spec.outputs.map(() => 1 / d.spec.outputs.length); }); }
  removeOutput(index: number): void { this.change(d => { d.spec.outputs.splice(index, 1); d.spec.params['ratios'] = d.spec.outputs.map(() => 1 / d.spec.outputs.length); }); }
}
