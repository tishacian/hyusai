import { AfterViewInit, ChangeDetectionStrategy, Component, ElementRef, OnDestroy, computed, input, output, viewChild } from '@angular/core';
import { FFlowModule, FCanvasComponent, EFConnectionType } from '@foblex/flow';
import { inputConnectorId, outputConnectorId } from '../orchestration/flow/flow-foblex.adapter';
import { executionGraphLayout, type RunExecutionView } from './run-execution.models';
/** Reuses the Flow rendering engine and connector identity, without any draft store/persistence provider. */
@Component({ selector: 'app-run-execution-graph', standalone: true, imports: [FFlowModule], changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<div #surface class="graph" data-testid="execution-graph"><f-flow (fLoaded)="fit()"><f-canvas fZoom [fZoomMinimum]="0.1" [fZoomMaximum]="3">
    @for (node of nodes(); track node.id) {
      <div fNode [fNodeId]="node.id" [fNodePosition]="node.position" class="execution-node" [class.selected]="selected() === node.id">
        <span fNodeInput [fInputId]="inputId(node.id)" class="port input"></span>
        <button type="button" (click)="select.emit(node.id)" [attr.aria-pressed]="selected() === node.id"><small>{{ node.kind }}</small><strong>{{ node.label }}</strong><span>{{ nodeStatus(node.id) }}</span></button>
        <span fNodeOutput [fOutputId]="outputId(node.id)" class="port output"></span>
      </div>
    }
    @for (edge of edges(); track edge.id) { <f-connection [fConnectionId]="edge.id" [fOutputId]="outputId(edge.source)" [fInputId]="inputId(edge.target)" [fType]="routing">@if(edge.label) { <span fConnectionContent [position]="0.5" class="edge-label">{{ edge.label }}</span> }</f-connection> }
  </f-canvas></f-flow></div>`,
  styles: `.graph{height:400px;min-width:0;overflow:hidden;border:1px solid var(--ck-stroke-2);background:var(--ck-bg-inset);border-radius:6px}.execution-node{width:225px;position:relative;border:1px solid var(--ck-stroke-2);border-radius:5px;background:var(--ck-bg-panel)}.execution-node.selected{outline:2px solid var(--ck-signal-cool)}button{padding:12px;display:grid;gap:5px;width:100%;text-align:left;color:var(--ck-fg-1);background:transparent;border:0;cursor:pointer}small{color:var(--ck-fg-3)}strong{overflow-wrap:anywhere}span{font-size:12px}.port{position:absolute;width:6px;height:6px;border-radius:2px;top:50%;background:var(--ck-fg-3)}.input{left:-3px}.output{right:-3px}.edge-label{font-size:11px;background:var(--ck-bg-panel);color:var(--ck-fg-2)}:host ::ng-deep .f-connection-path{stroke:var(--ck-fg-3);stroke-width:2;fill:none}`,
})
export class RunExecutionGraphComponent implements AfterViewInit, OnDestroy {
  readonly view = input.required<RunExecutionView>(); readonly selected = input(''); readonly labels = input<Record<string,string>>({}); readonly select = output<string>();
  readonly nodes = computed(() => executionGraphLayout(this.view().graph.nodes, this.view().graph.edges));
  readonly edges = computed(() => this.view().graph.edges.filter(edge => this.view().graph.nodes.some(node => node.id === edge.source) && this.view().graph.nodes.some(node => node.id === edge.target)));
  readonly inputId = inputConnectorId; readonly outputId = outputConnectorId; readonly routing = EFConnectionType.BEZIER;
  private readonly canvas = viewChild(FCanvasComponent);
  private readonly surface = viewChild<ElementRef<HTMLDivElement>>('surface');
  private observer?: ResizeObserver;
  private frame: number | undefined;
  ngAfterViewInit(): void {
    const surface = this.surface()?.nativeElement;
    if (surface && typeof ResizeObserver !== 'undefined') {
      this.observer = new ResizeObserver(() => this.fit());
      this.observer.observe(surface);
    }
  }
  ngOnDestroy(): void {
    this.observer?.disconnect();
    if (this.frame !== undefined) cancelAnimationFrame(this.frame);
  }
  nodeStatus(id: string): string { const status = this.view().nodes.find(node => node.node_id === id)?.status || 'not_started'; return this.labels()[status] || status; }
  fit(): void {
    if (this.frame !== undefined) cancelAnimationFrame(this.frame);
    this.frame = requestAnimationFrame(() => {
      this.frame = undefined;
      this.canvas()?.fitToScreen({ x: 25, y: 25 }, false);
    });
  }
}
