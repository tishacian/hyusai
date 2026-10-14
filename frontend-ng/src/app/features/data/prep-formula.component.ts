import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { CodeEditorComponent } from '@app/shared/ui/code-editor.component';
import { DataOpsApi } from './dataops.api';

@Component({selector: 'app-prep-formula', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CodeEditorComponent], styleUrl: './dataops-editor.scss', template: `
  <ck-code-editor language="sql" [value]="value()" [sqlSchema]="completion()" [sqlFunctions]="functions()" [ariaLabel]="i18n.t('dataops.formula')" (valueChange)="valueChange.emit($event)" />
  <p class="dp-note">{{i18n.t('dataops.formula_help')}}</p>
  @if (result(); as result) { <p class="dp-note" role="status" [class.dp-error]="!result.valid">{{i18n.t(result.valid ? 'dataops.expression_valid' : 'dataops.error.expression')}}@if (result.dtype) { · {{result.dtype}} }</p> }
  `})
export class PrepFormulaComponent {
  readonly i18n = inject(I18nService); private readonly api = inject(DataOpsApi);
  readonly functions=input<string[]>([]); readonly value = input(''); readonly columns = input<string[]>([]); readonly schema = input<Array<{name:string; dtype?:string}>>([]);
  readonly valueChange = output<string>(); readonly result = signal<{valid:boolean; dtype?:string}|null>(null);
  readonly completion = computed(() => ({input: this.columns()}));
  constructor() { effect(onCleanup => {
    const expression = this.value(), columns = this.columns(), schema = this.schema();
    this.result.set(null); let current = true;
    const timer = setTimeout(async () => {
      if (!expression.trim()) return;
      if (expression.length > 4000) { this.result.set({valid:false}); return; }
      try { const response = await this.api.validateExpression(expression, columns, schema.length ? schema : undefined); if(current) this.result.set(response); }
      catch { if(current) this.result.set({valid:false}); }
    }, 400);
    onCleanup(() => { current = false; clearTimeout(timer); });
  }); }
}
