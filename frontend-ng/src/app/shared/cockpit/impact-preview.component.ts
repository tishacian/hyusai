import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { Subject, debounceTime, switchMap, tap } from 'rxjs';
import { toSignal } from '@angular/core/rxjs-interop';

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
            {{ label() }}
          </span>
          <ck-tag [tone]="previewTone()" variant="outline">{{ previewBadge() }}</ck-tag>
        </div>
        <span class="ck-mono ck-tnum" style="font-size:10px; color:var(--ck-fg-4);">
          {{ latencyMs() }}ms · debounce 250
        </span>
      </div>

      @if (!result()) {
        <div class="ck-mono" style="padding:12px 0; font-size:11px; color:var(--ck-fg-4); text-align:center;">
          ADJUST A LEVER TO PROJECT
        </div>
      } @else {
        <div class="grid grid-cols-4 gap-3">
          <ck-stat-readout
            label="COST"
            [value]="money(result()!.projected.total_cost)"
            tone="cool"
            [size]="14"
          />
          <ck-stat-readout
            label="VALUE"
            [value]="money(result()!.projected.estimated_value)"
            tone="pos"
            [size]="14"
          />
          <ck-stat-readout
            label="ROI"
            [value]="pct(result()!.projected.roi)"
            [tone]="roiTone(result()!.projected.roi)"
            [size]="14"
          />
          <ck-stat-readout
            label="LATENCY"
            [value]="idx(result()!.projected.latency_index) + 'x'"
            tone="violet"
            [size]="14"
          />
        </div>
        <div class="grid grid-cols-4 gap-3 mt-2">
          <div class="ck-mono ck-tnum" style="font-size:10px; text-align:center;" [style.color]="deltaColor(-(result()!.projected.total_cost - (result()!.base.total_cost ?? 0)))">
            {{ signed(result()!.projected.total_cost - (result()!.base.total_cost ?? 0)) }}
          </div>
          <div class="ck-mono ck-tnum" style="font-size:10px; text-align:center;" [style.color]="deltaColor(result()!.projected.estimated_value - (result()!.base.estimated_value ?? 0))">
            {{ signed(result()!.projected.estimated_value - (result()!.base.estimated_value ?? 0)) }}
          </div>
          <div class="ck-mono ck-tnum" style="font-size:10px; text-align:center;" [style.color]="deltaColor((result()!.projected.roi ?? 0) - (result()!.base.roi ?? 0))">
            {{ signedPct((result()!.projected.roi ?? 0) - (result()!.base.roi ?? 0)) }}
          </div>
          <div class="ck-mono ck-tnum" style="font-size:10px; text-align:center;" [style.color]="deltaColor(-(result()!.projected.latency_index - 1))">
            {{ signedPct(result()!.projected.latency_index - 1) }}
          </div>
        </div>
      }
    </div>
  `,
})
export class ImpactPreviewComponent {
  private readonly canonical = inject(CanonicalApiService);

  readonly scope = input<'portfolio' | 'capability' | 'system'>('portfolio');
  readonly targetId = input<string | null | undefined>(null);
  readonly levers = input<Record<string, number>>({
    resource: 0.5,
    velocity: 0.5,
    autonomy: 0.3,
    risk_tolerance: 0.4,
  });
  readonly label = input<string>('Impact preview');

  readonly result = signal<WhatIfResult | null>(null);
  readonly latencyMs = signal<number>(0);

  private readonly pulse = new Subject<number>();

  readonly previewTone = computed<'pos' | 'cool' | 'warn' | 'neg' | 'neutral'>(() => {
    const r = this.result();
    if (!r) return 'neutral';
    const roi = r.projected.roi ?? 0;
    if (roi >= 1) return 'pos';
    if (roi >= 0) return 'cool';
    return 'neg';
  });

  readonly previewBadge = computed(() => {
    const r = this.result();
    if (!r) return 'IDLE';
    const delta = (r.projected.estimated_value - (r.base.estimated_value ?? 0))
      - (r.projected.total_cost - (r.base.total_cost ?? 0));
    if (delta > 0) return 'NET +';
    if (delta < 0) return 'NET -';
    return 'NEUTRAL';
  });

  constructor() {
    const sims$ = this.pulse.pipe(
      debounceTime(250),
      switchMap((startedAt) =>
        this.canonical
          .hypervisorWhatIf({
            scope: this.scope(),
            target_id: this.targetId() ?? null,
            levers: this.levers(),
          })
          .pipe(
            tap(() => this.latencyMs.set(Math.round(performance.now() - startedAt))),
          ),
      ),
    );
    const sig = toSignal(sims$, { initialValue: null });
    effect(() => {
      const v = sig();
      if (v) this.result.set(v);
    });
    effect(() => {
      void this.scope();
      void this.targetId();
      void this.levers();
      this.pulse.next(performance.now());
    });
  }

  money(v: number): string {
    if (Math.abs(v) >= 1000) return `$${(v / 1000).toFixed(1)}k`;
    return `$${v.toFixed(2)}`;
  }
  signed(v: number): string {
    const sign = v > 0 ? '+' : v < 0 ? '-' : '';
    const abs = Math.abs(v);
    if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
    return `${sign}$${abs.toFixed(2)}`;
  }
  signedPct(v: number): string {
    const sign = v > 0 ? '+' : v < 0 ? '-' : '';
    return `${sign}${(Math.abs(v) * 100).toFixed(0)}pp`;
  }
  pct(v: number | null): string {
    if (v == null) return '—';
    return `${(v * 100).toFixed(0)}%`;
  }
  idx(v: number | null | undefined): string {
    if (v == null) return '—';
    return v.toFixed(2);
  }
  roiTone(v: number | null): 'pos' | 'cool' | 'neg' | 'neutral' {
    if (v == null) return 'neutral';
    if (v >= 1) return 'pos';
    if (v >= 0) return 'cool';
    return 'neg';
  }
  deltaColor(v: number): string {
    if (v > 0) return 'var(--ck-signal-pos)';
    if (v < 0) return 'var(--ck-signal-neg)';
    return 'var(--ck-fg-3)';
  }
}
