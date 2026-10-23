import { ChangeDetectionStrategy, Component, inject, input, output } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { FlowResultViewerComponent } from './flow-result-viewer.component';
import { observationPinValue, type FlowObservationPin } from './flow-observation-windows.vm';
import { formatObservationDate } from './flow-observation-bar.component';
import { FlowObservationWindowsService } from './flow-observation-windows.service';
import { runStatusLabel } from '@app/core/run-follow-up';

@Component({
  selector:'app-flow-observation-card',
  standalone:true,
  imports:[IconComponent,FlowResultViewerComponent],
  changeDetection:ChangeDetectionStrategy.OnPush,
  styleUrl:'./flow-observation-ui.scss',
  template:`
    <article class="fo-card" [class.fo-card--expanded]="expanded()" [attr.aria-label]="pin().title" data-testid="flow-observation-pin">
      <header class="fo-card__header f-drag-handle" [attr.tabindex]="expanded()?null:0" (pointerdown)="focusView($event)">
        <div><span class="fo-eyebrow"><app-icon name="pin" [size]="12" />{{i18n.t('flow.observation.consultative')}} · {{i18n.t('flow.observation.presentation.'+pin().presentation)}}</span><h3>{{pin().title}}</h3></div>
        <div class="fo-actions" (pointerdown)="$event.stopPropagation()" (mousedown)="$event.stopPropagation()">
          @if (!expanded()) { <button type="button" class="fo-icon" (click)="expand.emit(pin().id)" [attr.aria-label]="i18n.t('flow.observation.expand',{name:pin().title})" [title]="i18n.t('flow.observation.expand',{name:pin().title})"><app-icon name="maximize" [size]="14" /></button> }
          <button type="button" class="fo-icon" (click)="closed.emit(pin().id)" [attr.aria-label]="expanded()?i18n.t('common.close'):i18n.t('flow.observation.unpin',{name:pin().title})" [title]="expanded()?i18n.t('common.close'):i18n.t('flow.observation.unpin',{name:pin().title})"><app-icon name="x" [size]="14" /></button>
        </div>
      </header>
      <div class="fo-card__provenance"><span>{{date()}} · {{i18n.t('runs.status.'+pin().attempt.status)}}</span><span>{{i18n.t('flow.observation.'+pin().mode)}} · {{pin().run.id.slice(0,8)}}</span></div>
      <details class="fo-provenance-details fo-card__details" (pointerdown)="$event.stopPropagation()" (mousedown)="$event.stopPropagation()"><summary>{{i18n.t('flow.observation.provenance')}} · {{pin().run.flow_version_id?.slice(0,8)||i18n.t('flow.observation.unknown')}}</summary><dl><dt>{{i18n.t('flow.observation.run')}}</dt><dd>{{pin().run.id}} · {{runState()}}</dd><dt>{{i18n.t('flow.observation.node')}}</dt><dd>{{pin().nodeId}}</dd><dt>{{i18n.t('flow.observation.attempt')}}</dt><dd>{{pin().attempt.id}} · {{i18n.t('runs.status.'+pin().attempt.status)}}</dd><dt>{{i18n.t('flow.observation.version_label')}}</dt><dd>{{pin().run.flow_version_id||i18n.t('flow.observation.unknown')}}</dd><dt>{{i18n.t('flow.observation.flow_hash')}}</dt><dd>{{pin().run.flow_sha256||i18n.t('flow.observation.unknown')}}</dd></dl></details>
      <div class="fo-card__body" tabindex="-1" (pointerdown)="focusView($event);$event.stopPropagation()" (mousedown)="$event.stopPropagation()">
        <app-flow-result-viewer [value]="value()" [run]="pin().mode==='output'?pin().run:null" [nodeId]="pin().nodeId" [invocationId]="pin().attempt.id" [title]="pin().title" [presentation]="pin().presentation" [datasetPreview]="pin().mode==='output'?(pin().datasetPreview??null):null" [selectedSeriesName]="pin().selectedSeriesName??null" (selectedSeriesNameChange)="windows.selectSeries(pin().id,$event)" />
      </div>
    </article>
  `,
})
export class FlowObservationCardComponent {
  readonly i18n=inject(I18nService);
  readonly windows=inject(FlowObservationWindowsService);
  readonly pin=input.required<FlowObservationPin>();
  readonly expanded=input(false);
  readonly expand=output<string>();
  readonly closed=output<string>();
  readonly value=()=>observationPinValue(this.pin());
  readonly runState=()=>runStatusLabel(this.pin().run,this.i18n.t);
  focusView(event: PointerEvent): void {
    if (!(event.target as Element | null)?.closest('button, select, input, textarea, a, summary')) {
      (event.currentTarget as HTMLElement).focus({preventScroll:true});
    }
  }
  readonly date=()=>formatObservationDate(this.pin().run.started_at,this.i18n.locale(),this.i18n.t('flow.observation.date_unknown'));
}
