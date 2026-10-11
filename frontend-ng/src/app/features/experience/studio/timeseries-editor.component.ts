import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { type ExperienceNode } from '../runtime/model';
import { timeseriesMapping } from '../runtime/timeseries';
@Component({
  selector: 'xp-timeseries-editor', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <label>{{ i18n.t('experience.timeseries.kind') }}
      <select [value]="node().props?.['kind'] || 'bar'" (change)="prop('kind', $event)">
        <option value="bar">{{ i18n.t('experience.timeseries.bar') }}</option><option value="donut">{{ i18n.t('experience.timeseries.donut') }}</option><option value="timeseries">{{ i18n.t('experience.timeseries.kind.timeseries') }}</option>
      </select>
    </label>
    @if (node().props?.['kind'] === 'timeseries') {
      <label>{{ i18n.t('experience.timeseries.mode') }}
        <select [value]="dataset() ? 'dataset' : 'inline'" (change)="mode($event)">
          <option value="inline">{{ i18n.t('experience.timeseries.inline') }}</option><option value="dataset">{{ i18n.t('experience.timeseries.dataset') }}</option>
        </select>
      </label>
      @if (dataset()) {
        <label>{{ i18n.t('experience.editor.data.component') }}<select [value]="datasetField('componentId')" (change)="setDataset('componentId', $event)">
          <option value="">{{ i18n.t('experience.editor.data.choose_component') }}</option>
          @for (source of sources(); track source.id) { <option [value]="source.id" [selected]="datasetField('componentId') === source.id">{{ source.id }}</option> }
        </select></label>
        <label>{{ i18n.t('experience.timeseries.reference') }}<input [value]="datasetField('selector')" (input)="setDataset('selector', $event)" /></label>
        <p>{{ i18n.t('experience.timeseries.security') }}</p>
      }
      @for (field of fields; track field) {
        <label>{{ i18n.t('experience.timeseries.mapping.' + field) }}<input [value]="mapping()[field]" (input)="map(field, $event)" /></label>
      }
      <label>{{ i18n.t('experience.timeseries.unit') }}<input [value]="node().props?.['unit'] || ''" (input)="prop('unit', $event)" /></label>
    }
  `,
  styles: [`:host{display:grid;gap:12px}label{display:grid;gap:5px;font-size:12px;color:var(--ck-fg-2)}input,select{width:100%;min-height:32px;padding:6px 8px;background:var(--ck-bg-panel);color:var(--ck-fg-1);border:1px solid var(--ck-stroke-2);border-radius:var(--ck-radius-sm,4px)}p{margin:0;color:var(--ck-fg-3);font-size:11px;line-height:1.5}`],
})
export class TimeseriesEditorComponent {
  readonly i18n = inject(I18nService); readonly node = input.required<ExperienceNode>(); readonly sources = input<ExperienceNode[]>([]);
  readonly changed = output<{ key: string; value: unknown }>();
  readonly fields = ['time', 'value', 'actual', 'lower', 'upper', 'series'] as const;
  readonly mapping = computed(() => timeseriesMapping(this.node().props?.['mapping']));
  readonly dataset = computed(() => !!this.node().props?.['datasetSource']);
  prop(key: string, event: Event): void { const value = (event.target as HTMLInputElement).value; this.changed.emit({key, value}); if (key === 'kind' && value === 'timeseries' && !this.node().props?.['mapping']) this.changed.emit({key:'mapping',value:this.mapping()}); }
  map(key: string, event: Event): void { this.changed.emit({key:'mapping', value:{...this.mapping(), [key]:(event.target as HTMLInputElement).value}}); }
  mode(event: Event): void { this.changed.emit({key:'datasetSource', value:(event.target as HTMLSelectElement).value === 'dataset' ? {source:'run-output',selector:'dataset_id',componentId:''} : null}); }
  datasetField(key: string): string { return String((this.node().props?.['datasetSource'] as Record<string, unknown> | undefined)?.[key] ?? ''); }
  setDataset(key: string, event: Event): void { this.changed.emit({key:'datasetSource',value:{...(this.node().props?.['datasetSource'] as object),source:'run-output',[key]:(event.target as HTMLInputElement).value}}); }
}
