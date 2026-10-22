import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { IconComponent } from '@app/shared/ui/icon.component';
import { FlowObservationService } from './flow-observation.service';
import { FlowObservationDatasetService } from './flow-observation-dataset.service';
import { FlowObservationWindowsService } from './flow-observation-windows.service';
import { FlowResultViewerComponent } from './flow-result-viewer.component';
import { type FlowResultPresentation } from './flow-result.vm';
import { formatObservationDate } from './flow-observation-bar.component';
import { observationRunVersion, type FlowObservedAttempt } from './flow-observation.vm';
import type { FlowObservationPinInput } from './flow-observation-windows.vm';
import { formatDuration } from './flow-node-run.vm';

@Component({
  selector:'app-flow-observation-panel',
  standalone:true,
  imports:[IconComponent,NavLinkDirective,FlowResultViewerComponent],
  providers:[FlowObservationDatasetService],
  changeDetection:ChangeDetectionStrategy.OnPush,
  styleUrl:'./flow-observation-ui.scss',
  template:`
    <section class="fo-panel" tabindex="-1" aria-labelledby="flow-observation-panel-title" data-testid="flow-observation-panel">
      <header class="fo-panel__header"><div><span class="fo-eyebrow">{{i18n.t('flow.observation.read_only')}}</span><h2 id="flow-observation-panel-title">{{title()}}</h2></div>
        <button type="button" class="fo-icon" (click)="closed.emit()" [attr.aria-label]="i18n.t('common.close')"><app-icon name="x" [size]="15" /></button>
      </header>
      @if (observation.detailStatus()==='loading') { <p class="fo-empty" role="status">{{i18n.t('common.loading')}}</p> }
      @else if (observation.detailError()) { <p class="fo-empty" role="alert">{{i18n.t(observation.detailError()==='forbidden'?'flow.observation.forbidden':'flow.observation.unavailable')}}</p><button type="button" class="fo-text-button" (click)="observation.refresh()">{{i18n.t('common.retry')}}</button> }
      @else if (observation.currentRun(); as run) {
        <div class="fo-provenance"><span>{{date(run.started_at)}} · {{i18n.t('runs.status.'+run.status)}}</span><a [navLink]="{type:'run',ref:run.id}">{{i18n.t('flow.observation.open_run')}} · {{run.id.slice(0,8)}}</a></div>
        <details class="fo-provenance-details"><summary>{{i18n.t('flow.observation.provenance')}}</summary><dl><dt>{{i18n.t('flow.observation.run')}}</dt><dd>{{run.id}}</dd><dt>{{i18n.t('flow.observation.node')}}</dt><dd>{{observation.selectedNodeId()}}</dd><dt>{{i18n.t('flow.observation.version_label')}}</dt><dd>{{version()||i18n.t('flow.observation.unknown')}}</dd><dt>{{i18n.t('flow.observation.flow_hash')}}</dt><dd>{{run.flow_sha256||i18n.t('flow.observation.unknown')}}</dd></dl></details>
        @if (run.result_held) { <p class="fo-empty" role="status">{{i18n.t('flow.observation.held')}}</p> }
        @else if (!observation.currentNode()) {
          <div class="fo-empty"><app-icon name="search" [size]="22" /><strong>{{i18n.t('flow.observation.no_node_result')}}</strong><p>{{i18n.t('flow.observation.no_node_result_body')}}</p>
            <button type="button" class="fo-text-button" [disabled]="observation.searchStatus()==='loading'" (click)="searchLatest()">{{i18n.t(observation.searchStatus()==='loading'?'flow.observation.searching':'flow.observation.search_latest')}}</button>
            @if (observation.searchStatus()==='not-found') { <span role="status">{{i18n.t('flow.observation.search_not_found')}}</span> }
            @if (observation.searchStatus()==='error') { <span role="alert">{{i18n.t('flow.observation.unavailable')}}</span> }
          </div>
        } @else {
          @if (observation.currentNode(); as node) {
            <label class="fo-attempt"><span>{{i18n.t('flow.observation.attempt')}}</span><select data-testid="flow-observation-attempt-select" [value]="observation.currentAttempt()?.id??''" (change)="selectAttempt($event)">
              @if (!observation.currentAttempt()) { <option value="">{{i18n.t('flow.observation.choose_attempt')}}</option> }
              @for (attempt of node.attempts; track attempt.id) { <option [value]="attempt.id" [selected]="observation.currentAttempt()?.id===attempt.id">{{attemptLabel(attempt)}}</option> }
            </select></label>
          }
          @if (observation.currentAttempt(); as attempt) {
            <div class="fo-panel__tools"><div class="fo-tabs" role="group" [attr.aria-label]="i18n.t('flow.observation.content')">
              <button type="button" [attr.aria-pressed]="mode()==='output'" (click)="mode.set('output')">{{i18n.t('flow.observation.output')}}</button>
              <button type="button" [attr.aria-pressed]="mode()==='input'" (click)="mode.set('input')">{{i18n.t('flow.observation.input')}}</button>
            </div><div class="fo-actions">
              <button type="button" class="fo-icon" [disabled]="!canCapture()" data-testid="flow-observation-pin-action" (click)="pin()" [attr.aria-label]="i18n.t('flow.observation.pin')" [title]="i18n.t('flow.observation.pin')"><app-icon name="pin" [size]="14" /></button>
              <button type="button" class="fo-icon" [disabled]="!canCapture()" data-testid="flow-observation-expand-action" (click)="expand()" [attr.aria-label]="i18n.t('flow.observation.expand',{name:title()})" [title]="i18n.t('flow.observation.expand',{name:title()})"><app-icon name="maximize" [size]="14" /></button>
            </div></div>
            <label class="fo-presentation"><span>{{i18n.t('flow.observation.presentation_label')}}</span><select data-testid="flow-observation-presentation-select" [value]="presentation()" (change)="setPresentation($event)">
              @for (kind of presentations(); track kind) { <option [value]="kind">{{i18n.t('flow.observation.presentation.'+kind)}}</option> }
            </select></label>
            @if (windows.pinNotice()) { <p class="fo-note" role="status">{{i18n.t(windows.pinNotice()==='limit'?'flow.observation.pin_limit':'flow.observation.pin_unavailable')}}</p> }
            @if (attempt.outputState==='held') { <p class="fo-empty">{{i18n.t('flow.observation.held')}}</p> }
            @else {
              @if (mode()==='output' && dataset.available()) { <div class="fo-dataset-action"><button type="button" class="fo-text-button" [disabled]="datasetLoading()" data-testid="flow-observation-dataset-preview" (click)="dataset.load()"><app-icon name="table" [size]="14" />{{i18n.t(datasetLoading()?'common.loading':dataset.status()==='ready'?'flow.observation.dataset_refresh':dataset.status()==='error'?'common.retry':'flow.observation.dataset_preview')}}</button><span>{{i18n.t('flow.observation.dataset_retained_preview')}}</span></div> }
              @if (mode()==='output' && dataset.unavailableReason()==='not-pinned') { <p class="fo-note">{{i18n.t('flow.observation.dataset_not_pinned')}}</p> }
              @if (mode()==='output' && dataset.status()==='error') { <p class="fo-note" role="alert">{{i18n.t('flow.observation.dataset_unavailable')}}</p> }
              @if (currentValue() !== null) {
                <app-flow-result-viewer [value]="currentValue()" [run]="mode()==='output'?run:null" [nodeId]="observation.selectedNodeId()" [invocationId]="attempt.id" [title]="title()" [presentation]="presentation()" [loading]="datasetLoading()" [datasetPreview]="mode()==='output'?dataset.preview():null" [selectedSeriesName]="selectedSeriesName()" (selectedSeriesNameChange)="selectedSeriesName.set($event)" />
              } @else { <p class="fo-empty" role="status">{{i18n.t('flow.observation.result.'+(mode()==='input'?'input_missing':attempt.outputState))}}</p> }
            }
          }
        }
      } @else { <p class="fo-empty">{{i18n.t('flow.observation.select_run')}}</p> }
    </section>
  `,
})
export class FlowObservationPanelComponent {
  readonly observation=inject(FlowObservationService);
  readonly windows=inject(FlowObservationWindowsService);
  readonly dataset=inject(FlowObservationDatasetService);
  readonly i18n=inject(I18nService);
  readonly nodeTitle=input('');
  readonly pinPosition=input({x:480,y:40});
  readonly closed=output<void>();
  readonly mode=signal<'output'|'input'>('output');
  readonly presentation=signal<FlowResultPresentation>('auto');
  readonly selectedSeriesName=signal<string|null>(null);
  readonly presentations=computed<FlowResultPresentation[]>(()=>this.mode()==='input'?['auto','chart','table','metric','document']:['auto','chart','table','metric','document','decisions']);
  readonly title=computed(()=>this.nodeTitle().trim()||this.observation.selectedNodeId()||this.i18n.t('flow.observation.node'));
  readonly version=computed(()=>{const run=this.observation.currentRun();return run?observationRunVersion(run):null;});
  readonly currentValue=computed(()=>{const attempt=this.observation.currentAttempt();return this.mode()==='input'?attempt?.input??null:attempt?.output??null;});
  readonly datasetLoading=computed(()=>this.mode()==='output' && this.dataset.available() && ['idle','loading'].includes(this.dataset.status()));
  readonly canCapture=computed(()=>this.currentValue()!==null && !this.datasetLoading() && this.observation.currentAttempt()?.outputState!=='held' && !this.observation.currentRun()?.result_held);

  constructor(){
    effect(()=>{
      this.observation.selectedNodeId();this.observation.selectedRunId();
      untracked(()=>{this.mode.set('output');this.presentation.set('auto');});
    });
    effect(()=>{
      this.observation.selectedNodeId();this.observation.selectedRunId();this.observation.currentAttempt()?.id;
      untracked(()=>this.selectedSeriesName.set(null));
    });
    effect(()=>{
      const run=this.observation.currentRun(),nodeId=this.observation.selectedNodeId(),attempt=this.observation.currentAttempt();
      untracked(()=>this.dataset.setSelection(run&&nodeId&&attempt?{run,nodeId,attempt}:null));
    });
    effect(()=>{
      // Opening a retained result is the reader action. Only the exact dataset
      // reference is read; ready/error states never trigger an automatic retry.
      const reference=this.dataset.reference(),mode=this.mode(),status=this.dataset.status();
      if(reference && mode==='output' && status==='idle')untracked(()=>{void this.dataset.load();});
    });
    effect(()=>{if(this.mode()==='input'&&this.presentation()==='decisions')this.presentation.set('auto');});
    effect(()=>{
      const denied=this.dataset.error()==='forbidden'||this.dataset.error()==='missing';
      const reference=this.dataset.reference();
      if(denied&&reference)untracked(()=>this.windows.revokeDataset(reference.datasetId));
    });
  }

  date(value:string|null|undefined):string{return formatObservationDate(value,this.i18n.locale(),this.i18n.t('flow.observation.date_unknown'));}
  attemptLabel(attempt:FlowObservedAttempt):string{
    const parts=[this.date(attempt.startedAt),this.i18n.t('runs.status.'+attempt.status)];
    if(attempt.iteration!==null)parts.push(this.i18n.t('flow.observation.iteration',{number:attempt.iteration}));
    if(attempt.attemptIndex!==null)parts.push(this.i18n.t('flow.observation.attempt_number',{number:attempt.attemptIndex}));
    if(attempt.latencyMs!==null)parts.push(formatDuration(attempt.latencyMs,this.i18n.locale()));
    parts.push(attempt.id.slice(0,8));return parts.join(' · ');
  }
  selectAttempt(event:Event):void{this.observation.selectAttempt((event.target as HTMLSelectElement).value);}
  setPresentation(event:Event):void{const value=(event.target as HTMLSelectElement).value as FlowResultPresentation;if(this.presentations().includes(value))this.presentation.set(value);}
  searchLatest():void{const node=this.observation.selectedNodeId();if(node)this.observation.findLatestForNode(node);}
  pin():void{const value=this.capture();if(value)this.windows.pin(value);}
  expand():void{const value=this.capture();if(value)this.windows.showCurrent(value);}
  private capture():FlowObservationPinInput|null{
    const run=this.observation.currentRun(),attempt=this.observation.currentAttempt(),nodeId=this.observation.selectedNodeId();
    if(!run||!attempt||!nodeId||!this.canCapture())return null;
    const point=this.pinPosition(),offset=this.windows.pins().length*32;
    return{run,attempt,nodeId,title:this.title(),mode:this.mode(),presentation:this.presentation(),position:{x:point.x+offset,y:point.y+offset},datasetPreview:this.mode()==='output'?this.dataset.preview():null,selectedSeriesName:this.selectedSeriesName()};
  }
}
