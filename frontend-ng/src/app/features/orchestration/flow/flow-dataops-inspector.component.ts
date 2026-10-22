import { DataOpsApi } from '@app/features/data/dataops.api';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ApiService } from '@app/core/api.service';
import type { Skill } from '@app/core/canonical-api.service';
import type { ModelCatalogEntry } from '@app/core/model-catalog';
import { guidedJudgeIdentity } from '@app/features/data/typed-judge-guidance';
import { FlowPersistenceService } from './flow-persistence.service';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import { I18nService } from '@app/core/i18n.service';
import { FlowDataPrepWorkshopComponent } from './flow-data-prep-workshop.component';
import { prepSummary } from './flow-data-prep.vm';
import { FlowRunService } from './flow-run.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { TypedJudgeEditorComponent } from '@app/features/data/typed-judge-editor.component';
import { DataService, type DatasetDto } from '@app/features/data/data.service';
import { judgeDraftFromNode, judgeNodePatch, prepDraftFromNode, prepNodePatch, type PrepDraft, type TypedJudgeDraft } from '@app/features/data/dataops.models';
import { FlowStore } from './flow.store';

@Component({
  selector: 'app-flow-dataops-inspector', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FlowDataPrepWorkshopComponent, TypedJudgeEditorComponent, NavLinkDirective], styleUrl: '../../data/dataops-editor.scss',
  template: `@if (slug() === 'data_prep_v1') {
    @if (failed()) { <p role="alert">{{ i18n.t('dataops.error.load') }}</p> }
    @if(workspace.surfaceFeatureEnabled('data-preparation')) {
      <p class="dp-note" data-testid="prep-summary">{{i18n.t(summary().key,{count:summary().count})}}</p>
      <button class="dp-button" type="button" data-testid="open-prep-workshop" (click)="opened.set(true)">{{i18n.t('dataops.open_workshop')}}</button>
      @for(out of prep().spec.outputs;track $index;let n=$index){<label class="dp-field"><span>{{i18n.t('dataops.output_name')}} · {{out.port}}</span><input class="dp-input" [value]="out.name" (change)="name(n,val($event))" /></label>}
      <details><summary>{{i18n.t('dataops.advanced')}}</summary><label class="dp-field"><span>{{i18n.t('dataops.placement')}}</span><select class="dp-input" [value]="prep().placement??'auto'" (change)="placement(val($event))">@for(mode of placements();track mode){<option [value]="mode">{{mode}}</option>}</select></label><label class="dp-field"><span>{{i18n.t('dataops.timeout')}}</span><input class="dp-input" type="number" min="1" max="86400" [value]="prep().timeout_s??''" (change)="timeout(val($event))" /></label></details>
      @if(written().length){<label class="dp-field"><span>{{i18n.t('dataops.written_output')}}</span><select class="dp-input" [value]="selectedWrittenPort()" (change)="selectedPort.set(val($event))">@for(out of written();track out.port){<option [value]="out.port">{{out.port}}</option>}</select></label>@if(writtenId();as id){<a class="dp-button" [navLink]="{type:'dataset',ref:id}">{{i18n.t('dataops.open_written_output')}}</a>}}
      @if(opened()){<app-flow-data-prep-workshop [node]="node()" (close)="opened.set(false)" />}
    }
  } @else if (slug() === 'evaluate_v2') {
    @if (judgeCatalogState() === 'ready') { <app-typed-judge-editor [value]="judge()" [graph]="store.nodes()" [nodeId]="node().id" [skills]="judgeSkills()" [models]="judgeModels()" [modelCatalogState]="judgeModelsState()" (reloadModels)="loadJudgeModels()" (valueChange)="saveJudge($event)" /> }
    @else if (judgeCatalogState() === 'error') { <p role="alert">{{ i18n.t('dataops.error.load') }}</p><button type="button" (click)="loadJudgeCatalog()">{{ i18n.t('common.retry') }}</button> }
    @else { <p role="status">{{ i18n.t('common.loading') }}</p> }
  }`,
})
export class FlowDataOpsInspectorComponent {
  readonly node = input.required<CanonicalFlowNode>(); readonly i18n = inject(I18nService);
  readonly workspace=inject(WorkspaceService); private readonly run=inject(FlowRunService); readonly opened=signal(false); readonly selectedPort=signal('out'); readonly placements=signal(['auto','local']); private readonly api=inject(DataOpsApi);
  readonly summary=computed(()=>prepSummary(this.node()));
  readonly written=computed(()=>{const data=this.run.nodeRuns()[this.node().id]?.data;return Object.entries(data?.outputs??{}).flatMap(([port,ref])=>{const id=typeof ref==='string'?ref:ref.dataset_id;return id?[{port,id}]:[];});});
  readonly selectedWrittenPort=computed(()=>this.written().some(out=>out.port===this.selectedPort())?this.selectedPort():this.written()[0]?.port??'');
  readonly writtenId=computed(()=>this.written().find(out=>out.port===this.selectedWrittenPort())?.id??null);
  val(e:Event):string{return(e.target as HTMLInputElement).value;}
  name(index:number,name:string):void{const draft=structuredClone(this.prep());draft.spec.outputs[index].name=name;this.savePrep(draft);}
  placement(value:string):void{this.savePrep({...this.prep(),placement:value});}
  timeout(value:string):void{this.savePrep({...this.prep(),timeout_s:value.trim()?Number(value):null});}
  readonly store = inject(FlowStore); private readonly data = inject(DataService);
  private readonly persistence = inject(FlowPersistenceService);
  private readonly catalogApi = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  readonly judgeSkills = signal<Skill[]>([]);
  readonly judgeModels = signal<ModelCatalogEntry[]>([]);
  readonly judgeModelsState = signal<'loading' | 'ready' | 'error'>('loading');
  private judgeModelsGeneration = 0;
  readonly judgeCatalogState = signal<'loading' | 'ready' | 'error'>('loading');
  private judgeCatalogGeneration = 0;
  readonly datasets = signal<DatasetDto[]>([]); readonly failed = signal(false);
  readonly slug = computed(() => (this.node().config as Record<string, unknown>)?.['skill_slug']);
  readonly prep = computed(() => prepDraftFromNode(this.node()));
  readonly judge = computed(() => guidedJudgeIdentity(judgeDraftFromNode(this.node()), this.persistence.systemId(), this.node().id));
  constructor() {
    effect(() => { if (this.slug() === 'data_prep_v1') void this.loadDatasets(); });
    effect(() => { if (this.slug() === 'evaluate_v2') { this.loadJudgeCatalog(); this.loadJudgeModels(); } });
  }
  loadJudgeCatalog(): void {
    const generation = ++this.judgeCatalogGeneration;
    this.judgeCatalogState.set('loading');
    this.judgeSkills.set([]);
    const scope = this.workspace.captureRequestScope();
    const current = () => generation === this.judgeCatalogGeneration && this.workspace.isRequestScopeCurrent(scope);
    this.catalogApi.get<{ skills: Skill[] }>('/skills').pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: result => { if (current()) { this.judgeSkills.set(result.skills ?? []); this.judgeCatalogState.set('ready'); } },
      error: () => { if (current()) this.judgeCatalogState.set('error'); },
    });
  }
  loadJudgeModels(): void {
    const generation = ++this.judgeModelsGeneration;
    const scope = this.workspace.captureRequestScope();
    const current = () => generation === this.judgeModelsGeneration && this.workspace.isRequestScopeCurrent(scope);
    this.judgeModelsState.set('loading');
    this.judgeModels.set([]);
    this.catalogApi.get<{models: ModelCatalogEntry[]} | ModelCatalogEntry[]>('/models').pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: result => { if (current()) { this.judgeModels.set(Array.isArray(result) ? result : result.models ?? []); this.judgeModelsState.set('ready'); } },
      error: () => { if (current()) this.judgeModelsState.set('error'); },
    });
  }
  private async loadDatasets(): Promise<void> { this.failed.set(false); try { const [datasets,catalog]=await Promise.all([this.data.refresh(),this.api.catalog()]);this.datasets.set(datasets);this.placements.set([...new Set(['auto',...(catalog.feature?.placements??catalog.placements)])]); } catch { this.failed.set(true); } }
  savePrep(value: PrepDraft): void { this.store.patchNode(this.node().id, prepNodePatch(this.node(), value)); }
  saveJudge(value: TypedJudgeDraft): void { this.store.patchNode(this.node().id, judgeNodePatch(this.node(), value)); }
}
