import {
  AfterViewInit,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnChanges,
  OnDestroy,
  Output,
  SimpleChanges,
  inject,
} from '@angular/core';

import {
  attrFromTarget,
  hostPointerPoint,
  observeHostWidth,
  shouldRebuildLayout,
} from './chart-interact';
import { CkChartTipComponent, type CkChartTipLine } from './chart-tip.component';
import { ckChartUid } from './chart.types';
import {
  layoutSankey,
  type CkSankeySource,
  type SankeyLabel,
  type SankeyLayout,
  type SankeyNode,
  type SankeyRibbon,
  type SankeyStub,
} from './sankey-layout';

export type { CkSankeySource } from './sankey-layout';

@Component({
  selector: 'ck-chart-sankey-flow',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CkChartTipComponent],
  template: `
    <svg
      [attr.viewBox]="'0 0 ' + drawWidth + ' ' + height"
      width="100%"
      [attr.height]="height"
      style="display:block;overflow:visible"
      (pointerdown)="onPointer($event)"
      (pointermove)="onPointer($event)"
      (pointerleave)="onLeave()"
      (focusin)="onPointer($event)"
      (focusout)="onLeave()"
      (click)="onClick($event)"
    >
      <defs>
        <linearGradient [attr.id]="runsId" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="var(--ck-fg-1)" stop-opacity="0.4" />
          <stop offset="1" stop-color="var(--ck-fg-1)" stop-opacity="0.15" />
        </linearGradient>
        <linearGradient [attr.id]="valueId" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="var(--ck-fg-1)" stop-opacity="0.15" />
          <stop offset="0.35" stop-color="var(--ck-signal-cool)" stop-opacity="0.55" />
          <stop offset="1" stop-color="var(--ck-signal-cool)" stop-opacity="0.85" />
        </linearGradient>
      </defs>
      @for (ribbon of ribbons; track $index) {
        <path
          class="ck-ribbon"
          [class.is-lit]="isRibbonLit(ribbon)"
          [class.is-dim]="isDimmed() && !isRibbonLit(ribbon)"
          [attr.d]="ribbon.d"
          [attr.fill]="ribbon.kind === 'value' ? 'url(#' + valueId + ')' : 'url(#' + runsId + ')'"
          [attr.data-system]="ribbon.sourceId || null"
          [attr.data-node]="ribbon.kind === 'value' ? 'hours' : null"
        />
      }
      @for (node of nodes; track $index) {
        <rect
          class="ck-node"
          [class.is-lit]="isNodeLit(node)"
          [class.is-dim]="isDimmed() && !isNodeLit(node)"
          [attr.x]="node.x"
          [attr.y]="node.y"
          [attr.width]="node.w"
          [attr.height]="node.h"
          rx="1.5"
          [attr.fill]="node.fill"
          [attr.data-system]="node.sourceId || null"
          [attr.data-node]="node.role && node.role !== 'source' && node.role !== 'stub' ? node.role : null"
          [attr.tabindex]="node.role === 'source' ? 0 : -1"
          [attr.aria-label]="ariaFor(node)"
        />
      }
      @for (stub of stubs; track $index) {
        <line
          [attr.x1]="stub.x1"
          [attr.y1]="stub.y1"
          [attr.x2]="stub.x2"
          [attr.y2]="stub.y2"
          stroke="var(--ck-fg-1)"
          stroke-opacity="0.35"
          stroke-width="1"
          stroke-dasharray="2 3"
        />
      }
      @for (label of labels; track $index) {
        <text
          class="ck-sankey-label"
          [class.is-lit]="isLabelLit(label)"
          [class.is-dim]="isDimmed() && !isLabelLit(label)"
          [attr.x]="label.x"
          [attr.y]="label.y"
          [attr.fill]="label.fill"
          [attr.font-family]="label.font === 'mono' ? 'var(--ck-font-mono)' : 'var(--ck-font-sans)'"
          [attr.font-size]="label.size"
          [attr.font-weight]="label.weight ?? 400"
          [attr.letter-spacing]="label.tracking ?? 0"
          [attr.text-anchor]="label.anchor"
          [attr.data-system]="label.sourceId || null"
          [attr.data-node]="label.role && label.role !== 'source' ? label.role : null"
          [style.text-transform]="label.tracking ? 'uppercase' : null"
        >@if (label.title) {<title>{{ label.title }}</title>}{{ label.text }}</text>
      }
    </svg>
    <ck-chart-tip
      [open]="tipOpen"
      [title]="tipTitle"
      [lines]="tipLines"
      [x]="tipX"
      [y]="tipY"
    />
  `,
  styles: [`
    :host { display: block; position: relative; width: 100%; }
    .ck-ribbon, .ck-node, .ck-sankey-label {
      transition: opacity 160ms var(--ck-ease-out, ease-out);
    }
    .is-dim { opacity: 0.3; }
    .is-lit { opacity: 1; }
    .ck-node { cursor: pointer; }
    :host-context(.hv2-enter) .ck-ribbon {
      opacity: 0;
      transform: translateX(-16px);
      animation: ckRibbonIn 500ms var(--ck-ease-out, ease-out) forwards;
    }
    @keyframes ckRibbonIn { to { opacity: 1; transform: none; } }
    @media (prefers-reduced-motion: reduce) {
      .ck-ribbon, .ck-node, .ck-sankey-label { transition: none; }
      :host-context(.hv2-enter) .ck-ribbon { animation: none; opacity: 1; transform: none; }
    }
  `],
})
export class CkChartSankeyFlowComponent implements OnChanges, AfterViewInit, OnDestroy {
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly cdr = inject(ChangeDetectorRef);

  @Input() sources: CkSankeySource[] = [];
  @Input() middleLabel = '';
  @Input() rightLabel = '';
  @Input() leftCaption = '';
  @Input() middleCaption = '';
  @Input() rightCaption = '';
  @Input() width = 336;
  @Input() height = 336;
  @Input() nodeWidth = 6;
  @Input() hoverSystem: string | null = null;
  @Input() middleTip: { title: string; lines: readonly CkChartTipLine[] } | null = null;
  @Input() rightTip: { title: string; lines: readonly CkChartTipLine[] } | null = null;
  @Output() readonly systemHover = new EventEmitter<string | null>();
  @Output() readonly systemClick = new EventEmitter<string>();

  readonly runsId = ckChartUid('ck-sankey-runs');
  readonly valueId = ckChartUid('ck-sankey-val');

  tipOpen = false;
  tipTitle = '';
  tipLines: CkChartTipLine[] = [];
  tipX = 0;
  tipY = 0;
  drawWidth = 336;
  private localSystem: string | null = null;
  private localNode: 'hours' | 'value' | null = null;
  private built: SankeyLayout | null = null;
  private stopWidth: (() => void) | null = null;

  get ribbons(): SankeyRibbon[] {
    return this.layout().ribbons;
  }

  get nodes(): SankeyNode[] {
    return this.layout().nodes;
  }

  get labels(): SankeyLabel[] {
    return this.layout().labels;
  }

  get stubs(): SankeyStub[] {
    return this.layout().stubs;
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (shouldRebuildLayout(Object.keys(changes)) || !this.built) {
      this.built = this.compute();
    }
  }

  ngAfterViewInit(): void {
    this.stopWidth = observeHostWidth(this.host.nativeElement, (width) => {
      const next = Math.max(336, Math.round(width));
      if (next === this.drawWidth) return;
      this.drawWidth = next;
      this.built = this.compute();
      this.cdr.markForCheck();
    });
  }

  ngOnDestroy(): void {
    this.stopWidth?.();
  }

  isDimmed(): boolean {
    return this.activeSystem() != null || this.localNode != null;
  }

  isRibbonLit(ribbon: SankeyRibbon): boolean {
    if (this.localNode) return ribbon.kind === 'value' || Boolean(ribbon.sourceId && this.isConverting(ribbon.sourceId));
    const system = this.activeSystem();
    if (!system) return false;
    return ribbon.sourceId === system;
  }

  isNodeLit(node: SankeyNode): boolean {
    if (this.localNode) {
      return node.role === this.localNode || (node.role === 'source' && Boolean(node.sourceId && this.isConverting(node.sourceId)));
    }
    const system = this.activeSystem();
    if (!system) return false;
    return node.sourceId === system;
  }

  isLabelLit(label: SankeyLabel): boolean {
    if (this.localNode) return label.role === this.localNode || label.sourceId != null && this.isConverting(label.sourceId);
    const system = this.activeSystem();
    if (!system) return false;
    return label.sourceId === system;
  }

  ariaFor(node: SankeyNode): string {
    if (node.role === 'source') {
      const source = this.sources.find((row) => row.id === node.sourceId);
      return source?.tip?.title || source?.label || '';
    }
    if (node.role === 'hours') return this.middleTip?.title || this.middleLabel;
    if (node.role === 'value') return this.rightTip?.title || this.rightLabel;
    return '';
  }

  onPointer(event: PointerEvent | FocusEvent): void {
    if (event instanceof PointerEvent && event.pointerType === 'touch' && event.type === 'pointermove') return;
    const system = attrFromTarget(event.target, 'data-system');
    const node = attrFromTarget(event.target, 'data-node') as 'hours' | 'value' | null;
    if (system) {
      if (event instanceof PointerEvent && event.pointerType === 'touch' && event.type === 'pointerdown') {
        this.toggleSystem(system);
      } else {
        this.setSystem(system);
      }
      this.showSystemTip(system, event);
      return;
    }
    if (node === 'hours' || node === 'value') {
      this.localNode = node;
      this.setSystem(null);
      this.showNodeTip(node, event);
      return;
    }
    if (event.type === 'pointermove') return;
    this.onLeave();
  }

  onClick(event: MouseEvent): void {
    const system = attrFromTarget(event.target, 'data-system');
    if (system) this.systemClick.emit(system);
  }

  onLeave(): void {
    this.localNode = null;
    this.setSystem(null);
    this.tipOpen = false;
  }

  private activeSystem(): string | null {
    return this.localSystem ?? this.hoverSystem;
  }

  private toggleSystem(id: string): void {
    this.setSystem(this.localSystem === id ? null : id);
    if (this.localSystem == null) this.tipOpen = false;
  }

  private setSystem(id: string | null): void {
    this.localNode = null;
    if (this.localSystem === id) return;
    this.localSystem = id;
    this.systemHover.emit(id);
  }

  private isConverting(id: string): boolean {
    return !this.sources.find((row) => row.id === id)?.stubLabel;
  }

  private showSystemTip(id: string, event: Event): void {
    const source = this.sources.find((row) => row.id === id);
    const tip = source?.tip;
    this.tipTitle = tip?.title || source?.label || '';
    this.tipLines = tip ? [...tip.lines] : [];
    this.placeTip(event);
    this.tipOpen = true;
  }

  private showNodeTip(node: 'hours' | 'value', event: Event): void {
    const tip = node === 'hours' ? this.middleTip : this.rightTip;
    this.tipTitle = tip?.title || (node === 'hours' ? this.middleLabel : this.rightLabel);
    this.tipLines = tip ? [...tip.lines] : [];
    this.placeTip(event);
    this.tipOpen = true;
  }

  private placeTip(event: Event): void {
    if (event instanceof PointerEvent) {
      const pt = hostPointerPoint(this.host.nativeElement, event.clientX, event.clientY);
      this.tipX = pt.x;
      this.tipY = pt.y;
      return;
    }
    const el = event.target instanceof Element ? event.target : null;
    const rect = el?.getBoundingClientRect();
    const host = this.host.nativeElement.getBoundingClientRect();
    this.tipX = rect ? rect.left + rect.width / 2 - host.left : 0;
    this.tipY = rect ? rect.top - host.top : 0;
  }

  private layout(): SankeyLayout {
    return this.built ?? (this.built = this.compute());
  }

  private compute(): SankeyLayout {
    return layoutSankey(this.sources, {
      width: this.drawWidth || this.width,
      height: this.height,
      nodeWidth: this.nodeWidth,
      middleLabel: this.middleLabel,
      rightLabel: this.rightLabel,
      leftCaption: this.leftCaption,
      middleCaption: this.middleCaption,
      rightCaption: this.rightCaption,
    });
  }
}
