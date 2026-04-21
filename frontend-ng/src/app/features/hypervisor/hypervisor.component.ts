import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import {
  CanonicalApiService,
  type HypervisorBalance,
  type HypervisorSignal,
  type Recommendation,
  type CapabilityRow,
  type ImpactAggregate,
} from '@app/core/canonical-api.service';
import {
  GlyphComponent,
  KbdComponent,
  LiveDotComponent,
  MicroBarComponent,
  PageFrameComponent,
  StatReadoutComponent,
  TagComponent,
} from '@app/shared/cockpit';

type PeriodKey = 'wtd' | 'mtd' | 'qtd' | 'rolling_30d' | 'rolling_90d';

const PERIOD_LABELS: Record<PeriodKey, string> = {
  wtd: 'W',
  mtd: 'M',
  qtd: 'Q',
  rolling_30d: '30d',
  rolling_90d: '90d',
};

@Component({
  selector: 'app-hypervisor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    PageFrameComponent,
    StatReadoutComponent,
    MicroBarComponent,
    TagComponent,
    LiveDotComponent,
    GlyphComponent,
    KbdComponent,
  ],
  template: `
    <ck-page-frame
      eyebrow="Hypervisor · Balance sheet"
      title="Net value generated"
      description="The executive view onto your AI portfolio. Cost, value, ROI and signals — live, per capability and per system."
    >
      <div class="flex flex-col gap-6">
        <!-- Period selector -->
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-1 ck-surface rounded-md" style="padding:4px;">
            @for (p of periods; track p.id) {
              <button
                type="button"
                (click)="setPeriod(p.id)"
                class="ck-mono"
                [style.padding]="'6px 12px'"
                [style.borderRadius.px]="4"
                [style.fontSize.px]="10"
                [style.letterSpacing]="'0.16em'"
                [style.textTransform]="'uppercase'"
                [style.background]="period() === p.id ? 'var(--ck-bg-inset)' : 'transparent'"
                [style.color]="period() === p.id ? 'var(--ck-fg-1)' : 'var(--ck-fg-4)'"
                [style.boxShadow]="period() === p.id ? 'inset 0 0 0 1px var(--ck-stroke-strong)' : 'none'"
              >
                {{ p.label }}
              </button>
            }
          </div>
          <div class="flex items-center gap-3">
            <ck-live-dot [tone]="balance() ? 'pos' : 'warn'" [label]="balance() ? 'LIVE' : 'OFFLINE'" />
            <ck-kbd>⌘R</ck-kbd>
          </div>
        </div>

        <!-- Hero Balance Sheet -->
        <section
          class="ck-surface ck-hero-ambient rounded-md relative overflow-hidden"
          style="padding: 32px; min-height:200px;"
        >
          <div class="ck-ambient-grid" style="position:absolute; inset:0; opacity:0.3; pointer-events:none;"></div>
          <div class="relative z-10 grid grid-cols-1 lg:grid-cols-5 gap-8">
            <div class="lg:col-span-2">
              <div class="ck-mono flex items-center gap-2 mb-3" style="font-size:10px; letter-spacing:0.18em; text-transform:uppercase; color:var(--ck-fg-4);">
                <ck-glyph name="telemetry" [size]="12" />
                NET VALUE · {{ periodLabel() }}
              </div>
              <div class="flex items-baseline gap-3">
                <span
                  class="ck-mono ck-tnum"
                  [style.fontSize.px]="56"
                  [style.fontWeight]="300"
                  [style.letterSpacing]="'-0.02em'"
                  [style.color]="netValue() >= 0 ? 'var(--ck-signal-pos)' : 'var(--ck-signal-neg)'"
                  [style.lineHeight]="'1'"
                >
                  {{ formatCurrencyLarge(netValue()) }}
                </span>
                <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); letter-spacing:0.08em;">
                  {{ netValue() >= 0 ? 'surplus' : 'deficit' }}
                </span>
              </div>
              <div class="ck-mono" style="font-size:10px; letter-spacing:0.08em; color:var(--ck-fg-4); margin-top:8px; line-height:1.7;">
                VALUE <span class="ck-tnum" style="color:var(--ck-fg-2);">{{ formatCurrency(portfolio()?.estimated_value) }}</span>
                · COST <span class="ck-tnum" style="color:var(--ck-fg-2);">{{ formatCurrency(portfolio()?.total_cost) }}</span>
                · RUNS <span class="ck-tnum" style="color:var(--ck-fg-2);">{{ portfolio()?.runs_count || 0 }}</span>
              </div>
            </div>

            <div class="lg:col-span-3 grid grid-cols-2 md:grid-cols-4 gap-6">
              <ck-stat-readout
                label="ROI"
                [value]="formatRoi(portfolio()?.roi)"
                [tone]="roiTone()"
                [size]="22"
              />
              <ck-stat-readout
                label="CONFIDENCE"
                [value]="formatPercent(portfolio()?.avg_confidence)"
                [tone]="confidenceTone()"
                [size]="22"
              />
              <ck-stat-readout
                label="EFFICIENCY"
                [value]="formatIndex(portfolio()?.avg_efficiency)"
                tone="cool"
                [size]="22"
              />
              <ck-stat-readout
                label="CAPABILITIES"
                [value]="capabilities().length.toString()"
                tone="violet"
                [size]="22"
              />
            </div>
          </div>
        </section>

        <!-- Capabilities portfolio -->
        <section class="ck-surface rounded-md" style="padding: 18px 22px;">
          <div class="flex items-center justify-between mb-4">
            <div class="flex items-center gap-2">
              <ck-glyph name="cube" [size]="14" />
              <h3 class="ck-mono" style="font-size:11px; letter-spacing:0.18em; text-transform:uppercase; color:var(--ck-fg-2);">
                CAPABILITIES · {{ periodLabel() }}
              </h3>
            </div>
            <a
              routerLink="/capabilities"
              class="ck-mono"
              style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-3);"
            >
              FULL CATALOG →
            </a>
          </div>

          @if (loading()) {
            <div class="ck-mono" style="padding:24px 0; font-size:11px; color:var(--ck-fg-4); text-align:center;">Loading…</div>
          } @else if (capabilities().length === 0) {
            <div class="ck-mono" style="padding:32px 0; font-size:11px; color:var(--ck-fg-4); text-align:center;">
              NO CAPABILITY HAS PRODUCED A RUN YET
            </div>
          } @else {
            <table style="width:100%; border-collapse: collapse;">
              <thead>
                <tr
                  class="ck-mono"
                  style="font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);"
                >
                  <th style="text-align:left; padding:8px 10px; font-weight:500; border-bottom: 1px solid var(--ck-hair);">CAPABILITY</th>
                  <th style="text-align:left; padding:8px 10px; font-weight:500; border-bottom: 1px solid var(--ck-hair); width:80px;">TIER</th>
                  <th style="text-align:right; padding:8px 10px; font-weight:500; border-bottom: 1px solid var(--ck-hair);">RUNS</th>
                  <th style="text-align:right; padding:8px 10px; font-weight:500; border-bottom: 1px solid var(--ck-hair);">COST</th>
                  <th style="text-align:right; padding:8px 10px; font-weight:500; border-bottom: 1px solid var(--ck-hair);">VALUE</th>
                  <th style="text-align:right; padding:8px 10px; font-weight:500; border-bottom: 1px solid var(--ck-hair);">ROI</th>
                  <th style="text-align:right; padding:8px 10px; font-weight:500; border-bottom: 1px solid var(--ck-hair); width:120px;">CONFIDENCE</th>
                </tr>
              </thead>
              <tbody>
                @for (c of capabilities(); track c.capability_id) {
                  <tr
                    style="border-bottom: 1px solid var(--ck-hair); cursor:pointer; transition: background 120ms ease;"
                    (click)="drillDown(c)"
                    onmouseover="this.style.background='var(--ck-bg-inset)'"
                    onmouseout="this.style.background='transparent'"
                  >
                    <td style="padding:10px; font-size:13px; color:var(--ck-fg-1);">
                      <div class="flex items-center gap-2">
                        <ck-glyph name="cube" [size]="12" />
                        <div class="flex flex-col">
                          <span style="font-weight:500;">{{ c.name }}</span>
                          <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">{{ c.slug }}</span>
                        </div>
                      </div>
                    </td>
                    <td style="padding:10px;">
                      <ck-tag [tone]="tierTone(c.tier)" variant="soft">{{ c.tier || '—' }}</ck-tag>
                    </td>
                    <td class="ck-mono ck-tnum" style="padding:10px; font-size:12px; text-align:right; color:var(--ck-fg-2);">
                      {{ c.runs_count ?? 0 }}
                    </td>
                    <td class="ck-mono ck-tnum" style="padding:10px; font-size:12px; text-align:right; color:var(--ck-signal-cool);">
                      {{ formatCurrency(c.total_cost) }}
                    </td>
                    <td class="ck-mono ck-tnum" style="padding:10px; font-size:12px; text-align:right; color:var(--ck-signal-pos);">
                      {{ formatCurrency(c.estimated_value) }}
                    </td>
                    <td class="ck-mono ck-tnum" style="padding:10px; font-size:12px; text-align:right;" [style.color]="roiColor(c.roi)">
                      {{ formatRoi(c.roi) }}
                    </td>
                    <td style="padding:10px;">
                      <div style="display:flex; align-items:center; gap:8px; justify-content:flex-end;">
                        <ck-micro-bar
                          [value]="(c.avg_confidence ?? 0) * 100"
                          [max]="100"
                          [width]="60"
                          [tone]="confidenceToneFor(c.avg_confidence)"
                        />
                        <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2); min-width:34px; text-align:right;">
                          {{ formatPercent(c.avg_confidence) }}
                        </span>
                      </div>
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          }
        </section>

        <!-- Signals + Recommendations -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <section class="ck-surface rounded-md" style="padding:18px 22px;">
            <div class="flex items-center justify-between mb-4">
              <div class="flex items-center gap-2">
                <ck-glyph name="pulse" [size]="14" />
                <h3 class="ck-mono" style="font-size:11px; letter-spacing:0.18em; text-transform:uppercase; color:var(--ck-fg-2);">
                  SIGNALS · last 20
                </h3>
              </div>
              <ck-live-dot [tone]="signals().length ? 'cool' : 'warn'" label="" />
            </div>
            @if (!signals().length) {
              <div class="ck-mono" style="padding:24px 0; font-size:11px; color:var(--ck-fg-4); text-align:center;">
                SILENCE — no recent runs
              </div>
            } @else {
              <ul style="display:flex; flex-direction:column; gap:6px;">
                @for (s of signals(); track s.id) {
                  <li
                    style="display:grid; grid-template-columns: 12px 1fr auto; gap:10px; align-items:center; padding:6px 8px; border-radius:4px; background:var(--ck-bg-inset);"
                  >
                    <span
                      [style.backgroundColor]="signalDot(s.tone)"
                      style="width:6px; height:6px; border-radius:999px; justify-self:center;"
                    ></span>
                    <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                      {{ s.label }}
                    </span>
                    <span class="ck-mono ck-tnum" style="font-size:10px; color:var(--ck-fg-4);">
                      {{ formatTime(s.timestamp) }}
                    </span>
                  </li>
                }
              </ul>
            }
          </section>

          <section class="ck-surface rounded-md" style="padding:18px 22px;">
            <div class="flex items-center justify-between mb-4">
              <div class="flex items-center gap-2">
                <ck-glyph name="bolt" [size]="14" />
                <h3 class="ck-mono" style="font-size:11px; letter-spacing:0.18em; text-transform:uppercase; color:var(--ck-fg-2);">
                  RECOMMENDATIONS
                </h3>
              </div>
              <span class="ck-mono ck-tnum" style="font-size:10px; color:var(--ck-fg-4);">
                {{ recommendations().length }}
              </span>
            </div>
            @if (!recommendations().length) {
              <div class="ck-mono" style="padding:24px 0; font-size:11px; color:var(--ck-fg-4); text-align:center;">
                NO PENDING RECOMMENDATION
              </div>
            } @else {
              <ul style="display:flex; flex-direction:column; gap:8px;">
                @for (r of recommendations(); track r.id) {
                  <li class="ck-surface rounded" style="padding:10px 12px; background:var(--ck-bg-inset); display:flex; flex-direction:column; gap:4px;">
                    <div class="flex items-center gap-2">
                      <ck-tag [tone]="recoTone(r.status)" variant="outline">{{ r.status || 'pending' }}</ck-tag>
                      <span class="text-sm text-white" style="font-weight:500;">{{ r.title }}</span>
                    </div>
                    @if (r.impact_estimate && objectKeys(r.impact_estimate).length > 0) {
                      <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-3); display:flex; gap:14px; flex-wrap:wrap;">
                        @for (k of objectKeys(r.impact_estimate); track k) {
                          <span>
                            {{ k.toUpperCase() }}
                            <span class="ck-tnum" style="color:var(--ck-fg-1);">{{ formatImpact(r.impact_estimate[k]) }}</span>
                          </span>
                        }
                      </div>
                    }
                  </li>
                }
              </ul>
            }
          </section>
        </div>
      </div>
    </ck-page-frame>
  `,
})
export class HypervisorComponent implements OnInit {
  private readonly canonical = inject(CanonicalApiService);
  private readonly router = inject(Router);

  drillDown(c: CapabilityRow): void {
    // Semantic zoom: Portfolio > Capability. Single click navigates to the
    // catalog page with the capability pre-selected via query param.
    this.router.navigate(['/capabilities'], { queryParams: { focus: c.capability_id } });
  }

  readonly periods: { id: PeriodKey; label: string }[] = [
    { id: 'wtd', label: 'W' },
    { id: 'mtd', label: 'M' },
    { id: 'qtd', label: 'Q' },
    { id: 'rolling_30d', label: '30D' },
    { id: 'rolling_90d', label: '90D' },
  ];

  readonly period = signal<PeriodKey>('qtd');
  readonly loading = signal(true);
  readonly balance = signal<HypervisorBalance | null>(null);
  readonly recommendations = signal<Recommendation[]>([]);

  readonly portfolio = computed<ImpactAggregate | null>(() => this.balance()?.portfolio ?? null);
  readonly capabilities = computed<CapabilityRow[]>(() => this.balance()?.capabilities ?? []);
  readonly signals = computed<HypervisorSignal[]>(() => this.balance()?.signals ?? []);

  readonly netValue = computed(() => {
    const p = this.portfolio();
    if (!p) return 0;
    return (p.estimated_value ?? 0) - (p.total_cost ?? 0);
  });

  readonly periodLabel = computed(() => PERIOD_LABELS[this.period()]);

  readonly roiTone = computed(() => {
    const r = this.portfolio()?.roi;
    if (r == null) return 'neutral' as const;
    if (r >= 1) return 'pos' as const;
    if (r >= 0) return 'cool' as const;
    return 'neg' as const;
  });

  readonly confidenceTone = computed(() => this.confidenceToneFor(this.portfolio()?.avg_confidence));

  ngOnInit(): void {
    this.loadAll();
  }

  setPeriod(p: PeriodKey): void {
    this.period.set(p);
    this.loadAll();
  }

  private loadAll(): void {
    this.loading.set(true);
    forkJoin({
      balance: this.canonical.hypervisorBalanceSheet(this.period()).pipe(catchError(() => of(null))),
      recos: this.canonical.hypervisorRecommendations().pipe(catchError(() => of([] as Recommendation[]))),
    }).subscribe(({ balance, recos }) => {
      this.balance.set(balance);
      this.recommendations.set(recos);
      this.loading.set(false);
    });
  }

  protected confidenceToneFor(v: number | null | undefined): 'pos' | 'cool' | 'warn' | 'neg' | 'neutral' {
    if (v == null) return 'neutral';
    if (v >= 0.8) return 'pos';
    if (v >= 0.6) return 'cool';
    if (v >= 0.4) return 'warn';
    return 'neg';
  }

  protected formatCurrency(v: number | null | undefined): string {
    if (v == null) return '—';
    if (Math.abs(v) >= 1000) return `$${(v / 1000).toFixed(1)}k`;
    return `$${v.toFixed(2)}`;
  }

  protected formatCurrencyLarge(v: number): string {
    const sign = v < 0 ? '-' : '';
    const abs = Math.abs(v);
    if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
    if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
    return `${sign}$${abs.toFixed(2)}`;
  }

  protected formatPercent(v: number | null | undefined): string {
    if (v == null) return '—';
    return `${Math.round(v * 100)}%`;
  }

  protected formatRoi(v: number | null | undefined): string {
    if (v == null) return '—';
    return `${(v * 100).toFixed(0)}%`;
  }

  protected formatIndex(v: number | null | undefined): string {
    if (v == null) return '—';
    return v.toFixed(2);
  }

  protected formatImpact(v: number): string {
    if (Math.abs(v) >= 1000) return `$${(v / 1000).toFixed(1)}k`;
    if (Math.abs(v) < 1 && v !== 0) return `${(v * 100).toFixed(0)}%`;
    return v.toFixed(2);
  }

  protected formatTime(ts: string | null | undefined): string {
    if (!ts) return '—';
    const d = new Date(ts);
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
  }

  protected tierTone(tier: string | undefined): 'pos' | 'cool' | 'violet' | 'warn' {
    switch (tier) {
      case 'industry': return 'violet';
      case 'client':   return 'cool';
      case 'universal':
      default:         return 'pos';
    }
  }

  protected roiColor(r: number | null | undefined): string {
    if (r == null) return 'var(--ck-fg-3)';
    if (r >= 1) return 'var(--ck-signal-pos)';
    if (r >= 0) return 'var(--ck-signal-cool)';
    return 'var(--ck-signal-neg)';
  }

  protected recoTone(status: string | undefined): 'pos' | 'cool' | 'violet' | 'warn' | 'neg' | 'neutral' {
    switch (status) {
      case 'approved':
      case 'applied':  return 'pos';
      case 'rejected': return 'neg';
      case 'pending':
      default:         return 'warn';
    }
  }

  protected signalDot(tone: HypervisorSignal['tone']): string {
    switch (tone) {
      case 'pos': return 'var(--ck-signal-pos)';
      case 'neg': return 'var(--ck-signal-neg)';
      case 'warn': return 'var(--ck-signal-warn)';
      default: return 'var(--ck-fg-4)';
    }
  }

  protected objectKeys(o: Record<string, unknown>): string[] {
    return Object.keys(o);
  }
}
