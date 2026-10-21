import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
} from '@angular/core';
import { Subscription, timeout } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { WorkspaceService, type WorkspaceRequestScope } from '@app/core/workspace.service';
import { I18nService } from '@app/core/i18n.service';

import {
  CanonicalApiService,
  type WhatIfResult,
} from '@app/core/canonical-api.service';
import { StatReadoutComponent } from './stat-readout.component';
import { TagComponent } from './tag.component';

/**
 * Universal Impact Preview — a drop-in card that feeds four canonical
 * levers (resource / velocity / autonomy / risk_tolerance) to the
 * `/hypervisor/what-if` endpoint with a <300ms debounce and renders
 * Base → Projected + delta for cost / value / ROI / latency.
 */
@Component({
  selector: 'ck-impact-preview',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [StatReadoutComponent, TagComponent],
  template: `
    <div class="ck-surface rounded-md" style="padding:14px 18px;">
      <div class="flex items-center justify-between mb-3">
        <div class="flex items-center gap-2">
          <span class="ck-mono" style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
            {{ label() || i18n.t('governance.preview.title') }}
          </span>
          <ck-tag [tone]="previewTone()" variant="outline">{{ previewBadge() }}</ck-tag>
        </div>
        @if (latencyMs() !== null) { <span class="ck-mono ck-tnum" style="font-size:10px; color:var(--ck-fg-4);">{{ latencyMs() }} ms</span> }
      </div>

      @if (state() === 'loading') {
        <p role="status">{{ i18n.t('governance.preview.loading') }}</p>
      } @else if (state() === 'error' || state() === 'denied') {
        <p role="alert" data-testid="impact-preview-error">{{ i18n.t(state() === 'denied' ? 'governance.preview.denied' : 'governance.preview.error') }}</p>
        <button type="button" (click)="refresh()">{{ i18n.t('common.retry') }}</button>
      } @else if (!result()) {
        <p>{{ i18n.t('governance.preview.adjust') }}</p>
      } @else {
        <div class="grid grid-cols-4 gap-3">
          <ck-stat-readout
            [label]="i18n.t('governance.preview.cost')"
            [value]="money(result()!.projected.total_cost)"
            tone="cool"
            [size]="14"
          />
          <ck-stat-readout
            [label]="i18n.t('governance.preview.value')"
            [value]="money(result()!.projected.estimated_value)"
            tone="pos"
            [size]="14"
          />
          <ck-stat-readout
            [label]="i18n.t('governance.preview.roi')"
            [value]="pct(result()!.projected.roi)"
            [tone]="roiTone(result()!.projected.roi)"
            [size]="14"
          />
          <ck-stat-readout
            [label]="i18n.t('governance.preview.latency')"
            [value]="latencyIndex(result()!.projected.latency_index)"
            tone="violet"
            [size]="14"
          />
        </div>
        <div class="grid grid-cols-4 gap-3 mt-2">
          <div class="ck-mono ck-tnum" style="font-size:10px; text-align:center;" [style.color]="deltaColor(invertDelta(measurementDelta(result()!.projected.total_cost, result()!.base.total_cost)))">
            {{ signed(measurementDelta(result()!.projected.total_cost, result()!.base.total_cost)) }}
          </div>
          <div class="ck-mono ck-tnum" style="font-size:10px; text-align:center;" [style.color]="deltaColor(measurementDelta(result()!.projected.estimated_value, result()!.base.estimated_value))">
            {{ signed(measurementDelta(result()!.projected.estimated_value, result()!.base.estimated_value)) }}
          </div>
          <div class="ck-mono ck-tnum" style="font-size:10px; text-align:center;" [style.color]="deltaColor(measurementDelta(result()!.projected.roi, result()!.base.roi))">
            {{ signedPct(measurementDelta(result()!.projected.roi, result()!.base.roi)) }}
          </div>
          <div class="ck-mono ck-tnum" style="font-size:10px; text-align:center;" [style.color]="deltaColor(invertDelta(measurementDelta(result()!.projected.latency_index, 1)))">
            {{ signedPct(measurementDelta(result()!.projected.latency_index, 1)) }}
          </div>
        </div>
      }
    </div>
  `,
})
export class ImpactPreviewComponent {
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroyRef = inject(DestroyRef);
  readonly i18n = inject(I18nService);

  readonly scope = input<'portfolio' | 'capability' | 'system'>('portfolio');
  readonly targetId = input<string | null | undefined>(null);
  readonly levers = input<Record<string, number>>({
    resource: 0.5,
    velocity: 0.5,
    autonomy: 0.3,
    risk_tolerance: 0.4,
  });
  readonly label = input<string>('');

  readonly result = signal<WhatIfResult | null>(null);
  readonly latencyMs = signal<number | null>(null);
  readonly state = signal<'idle'|'loading'|'ready'|'denied'|'error'>('idle');
  private requestSequence = 0;
  private request: Subscription | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;

  readonly previewTone = computed<'pos' | 'cool' | 'warn' | 'neg' | 'neutral'>(() => {
    const r = this.result();
    if (!r) return this.state() === 'error' || this.state() === 'denied' ? 'warn' : 'neutral';
    const roi = r.projected.roi;
    if (roi == null || !Number.isFinite(roi)) return 'neutral';
    if (roi >= 1) return 'pos';
    if (roi >= 0) return 'cool';
    return 'neg';
  });

  readonly previewBadge = computed(() => {
    const r = this.result();
    if (!r) return this.i18n.t(this.state() === 'loading' ? 'governance.preview.loading' : this.state() === 'error' || this.state() === 'denied' ? 'governance.preview.unavailable' : 'governance.preview.idle');
    const valueDelta = this.measurementDelta(
      r.projected.estimated_value,
      r.base.estimated_value,
    );
    const costDelta = this.measurementDelta(
      r.projected.total_cost,
      r.base.total_cost,
    );
    if (valueDelta == null || costDelta == null) return this.i18n.t('governance.preview.unmeasured');
    const delta = valueDelta - costDelta;
    if (delta > 0) return 'NET +';
    if (delta < 0) return 'NET -';
    return this.i18n.t('governance.preview.neutral');
  });

  constructor() {
    this.destroyRef.onDestroy(this.workspace.registerContextReset(() => this.clear()));
    this.destroyRef.onDestroy(() => this.cancel());
    effect(onCleanup => {
      void this.scope(); void this.targetId(); void this.levers();
      this.workspace.captureRequestScope();
      untracked(() => {
        this.clear(); this.state.set('loading');
        this.timer = setTimeout(() => this.refresh(), 250);
      });
      onCleanup(() => this.cancel());
    });
  }

  private cancel(): void {
    ++this.requestSequence;
    this.request?.unsubscribe(); this.request = null;
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  private clear(): void {
    this.cancel(); this.result.set(null); this.latencyMs.set(null); this.state.set('idle');
  }

  refresh(): void {
    this.clear(); this.state.set('loading');
    const sequence = this.requestSequence;
    const workspace = this.workspace.captureRequestScope();
    const startedAt = performance.now();
    this.request = this.canonical.hypervisorWhatIf({scope:this.scope(), target_id:this.targetId() ?? null, levers:{...this.levers()}}, {propagateErrors:true})
      .pipe(timeout({first:15_000}), takeUntilDestroyed(this.destroyRef)).subscribe({
        next: result => {
          if (!this.isCurrent(sequence,workspace)) return;
          if (!result?.base || !result?.projected) { this.state.set('error'); return; }
          this.result.set(result); this.state.set('ready');
          this.latencyMs.set(Math.round(performance.now()-startedAt));
        },
        error: error => {
          if (!this.isCurrent(sequence,workspace)) return;
          this.result.set(null); this.latencyMs.set(null);
          this.state.set(error?.status === 401 || error?.status === 403 ? 'denied' : 'error');
        },
        complete: () => { if (this.isCurrent(sequence,workspace) && this.state() === 'loading') this.state.set('error'); },
      });
  }

  private isCurrent(sequence:number, workspace:WorkspaceRequestScope): boolean {
    return sequence === this.requestSequence && this.workspace.isRequestScopeCurrent(workspace);
  }

  latencyIndex(value:number | null | undefined): string {
    return typeof value === 'number' && Number.isFinite(value) ? this.idx(value) + 'x' : '—';
  }

  money(v: number | null | undefined): string {
    if (v == null || !Number.isFinite(v)) return '—';
    if (Math.abs(v) >= 1000) return `$${(v / 1000).toFixed(1)}k`;
    return `$${v.toFixed(2)}`;
  }
  signed(v: number | null | undefined): string {
    if (v == null || !Number.isFinite(v)) return '—';
    const sign = v > 0 ? '+' : v < 0 ? '-' : '';
    const abs = Math.abs(v);
    if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
    return `${sign}$${abs.toFixed(2)}`;
  }
  signedPct(v: number | null | undefined): string {
    if (v == null || !Number.isFinite(v)) return '—';
    const sign = v > 0 ? '+' : v < 0 ? '-' : '';
    return `${sign}${(Math.abs(v) * 100).toFixed(0)}pp`;
  }
  pct(v: number | null): string {
    if (v == null || !Number.isFinite(v)) return '—';
    return `${(v * 100).toFixed(0)}%`;
  }
  idx(v: number | null | undefined): string {
    if (v == null || !Number.isFinite(v)) return '—';
    return v.toFixed(2);
  }
  roiTone(v: number | null): 'pos' | 'cool' | 'neg' | 'neutral' {
    if (v == null || !Number.isFinite(v)) return 'neutral';
    if (v >= 1) return 'pos';
    if (v >= 0) return 'cool';
    return 'neg';
  }
  measurementDelta(
    projected: number | null | undefined,
    base: number | null | undefined,
  ): number | null {
    if (projected == null || base == null || !Number.isFinite(projected) || !Number.isFinite(base)) return null;
    return projected - base;
  }
  invertDelta(v: number | null | undefined): number | null {
    return v == null ? null : -v;
  }
  deltaColor(v: number | null | undefined): string {
    if (v == null || !Number.isFinite(v)) return 'var(--ck-fg-3)';
    if (v > 0) return 'var(--ck-signal-pos)';
    if (v < 0) return 'var(--ck-signal-neg)';
    return 'var(--ck-fg-3)';
  }
}
