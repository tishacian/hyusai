import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import { I18nService } from '@app/core/i18n.service';
import { DataPrepEditorComponent } from '@app/features/data/data-prep-editor.component';
import { TypedJudgeEditorComponent } from '@app/features/data/typed-judge-editor.component';
import { DataService, type DatasetDto } from '@app/features/data/data.service';
import { newJudgeDraft, newPrepDraft, prepNodePatch, type PrepDraft, type TypedJudgeDraft } from '@app/features/data/dataops.models';
import { FlowStore } from './flow.store';

@Component({
  selector: 'app-flow-dataops-inspector', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DataPrepEditorComponent, TypedJudgeEditorComponent],
  template: `@if (slug() === 'data_prep_v1') {
    @if (failed()) { <p role="alert">{{ i18n.t('dataops.error.load') }}</p> }
    <app-data-prep-editor [value]="prep()" [datasets]="datasets()" (valueChange)="savePrep($event)" />
  } @else if (slug() === 'evaluate_v2') { <app-typed-judge-editor [value]="judge()" (valueChange)="saveJudge($event)" /> }`,
})
export class FlowDataOpsInspectorComponent {
  readonly node = input.required<CanonicalFlowNode>(); readonly i18n = inject(I18nService);
  private readonly store = inject(FlowStore); private readonly data = inject(DataService);
  readonly datasets = signal<DatasetDto[]>([]); readonly failed = signal(false);
  readonly slug = computed(() => (this.node().config as Record<string, unknown>)?.['skill_slug']);
  readonly prep = computed(() => ((this.node().config as Record<string, unknown>)?.['data_prep'] as PrepDraft | undefined) ?? newPrepDraft());
  readonly judge = computed(() => ((this.node().config as Record<string, unknown>)?.['typed_evaluation'] as TypedJudgeDraft | undefined) ?? newJudgeDraft());
  constructor() { effect(() => { if (this.slug() === 'data_prep_v1') void this.loadDatasets(); }); }
  private async loadDatasets(): Promise<void> { this.failed.set(false); try { this.datasets.set(await this.data.refresh()); } catch { this.failed.set(true); } }
  savePrep(value: PrepDraft): void { this.store.patchNode(this.node().id, prepNodePatch(this.node(), value)); }
  saveJudge(value: TypedJudgeDraft): void { this.store.updateNodeConfig(this.node().id, 'typed_evaluation', value); }
}
