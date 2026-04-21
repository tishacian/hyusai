import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { CanonicalApiService, type Skill } from '@app/core/canonical-api.service';
import {
  GlyphComponent,
  KbdComponent,
  MicroBarComponent,
  PageFrameComponent,
  StatReadoutComponent,
  TagComponent,
} from '@app/shared/cockpit';

type CertFilter = 'all' | 'basic' | 'production' | 'enterprise';

@Component({
  selector: 'app-skills',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PageFrameComponent, GlyphComponent, KbdComponent, StatReadoutComponent, MicroBarComponent, TagComponent],
  template: `
    <ck-page-frame
      eyebrow="Registry · Skills"
      title="Certified atomic operations"
      description="Every skill carries a typed contract, a certification badge, version history and live perf metrics aggregated from all skill invocations."
    >
      <div class="flex flex-col gap-6">
        <!-- Filter bar -->
        <div class="flex items-center justify-between flex-wrap gap-4">
          <div class="flex items-center gap-1 ck-surface rounded-md" style="padding:4px;">
            @for (c of certs; track c.id) {
              <button
                type="button"
                (click)="cert.set(c.id)"
                class="ck-mono"
                style="padding:6px 12px; border-radius:4px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase;"
                [style.background]="cert() === c.id ? 'var(--ck-bg-inset)' : 'transparent'"
                [style.color]="cert() === c.id ? 'var(--ck-fg-1)' : 'var(--ck-fg-4)'"
                [style.boxShadow]="cert() === c.id ? 'inset 0 0 0 1px var(--ck-stroke-strong)' : 'none'"
              >
                {{ c.label }}
                @if (cert() === c.id) {
                  <span class="ck-tnum" style="margin-left:6px; color:var(--ck-fg-3);">
                    {{ filtered().length }}
                  </span>
                }
              </button>
            }
          </div>
          <div class="flex items-center gap-2">
            <ck-kbd>⌘F</ck-kbd>
            <input
              type="search"
              [value]="query()"
              (input)="query.set(asInput($event).value)"
              placeholder="Filter skills…"
              class="ck-mono"
              style="padding:6px 12px; font-size:11px; border-radius:4px; background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-1); width:220px;"
            />
          </div>
        </div>

        <!-- Portfolio summary -->
        <section class="ck-surface rounded-md ck-hero-ambient relative overflow-hidden" style="padding:20px 24px;">
          <div class="ck-mono flex items-center gap-2" style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:14px;">
            <ck-glyph name="ledger" [size]="12" />
            REGISTRY TOTALS
          </div>
          <div style="display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:24px;">
            <ck-stat-readout label="SKILLS" [value]="skills().length.toString()" tone="cool" [size]="20" />
            <ck-stat-readout label="TOTAL CALLS" [value]="formatNum(totals().calls)" tone="pos" [size]="20" />
            <ck-stat-readout label="AVG LATENCY" [value]="formatLatency(totals().avgLatency)" tone="warn" [size]="20" />
            <ck-stat-readout label="SUCCESS RATE" [value]="formatPct(totals().successRate)" tone="pos" [size]="20" />
          </div>
        </section>

        <!-- Table -->
        @if (loading()) {
          <div class="ck-mono" style="font-size:11px; color:var(--ck-fg-4); text-align:center; padding:40px;">
            Loading registry…
          </div>
        } @else if (!filtered().length) {
          <div class="ck-surface rounded-md" style="padding:40px; text-align:center;">
            <div class="ck-mono" style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
              NO SKILL MATCHES
            </div>
          </div>
        } @else {
          <div class="ck-surface rounded-md" style="overflow:hidden;">
            <!-- header -->
            <div
              class="ck-mono"
              style="display:grid; grid-template-columns: 80px 2fr 1fr 100px 110px 110px 110px 100px; gap:12px; padding:12px 16px; font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); background:var(--ck-bg-inset); border-bottom:1px solid var(--ck-stroke-soft);"
            >
              <span>CERT</span>
              <span>SKILL</span>
              <span>TYPE</span>
              <span style="text-align:right;">CALLS</span>
              <span style="text-align:right;">AVG LAT</span>
              <span style="text-align:right;">COST</span>
              <span style="text-align:right;">SUCCESS</span>
              <span style="text-align:right;">UNIT PRICE</span>
            </div>
            @for (sk of filtered(); track sk.id) {
              <div
                (click)="selected.set(selected()?.id === sk.id ? null : sk)"
                style="display:grid; grid-template-columns: 80px 2fr 1fr 100px 110px 110px 110px 100px; gap:12px; padding:12px 16px; align-items:center; cursor:pointer; border-bottom:1px solid var(--ck-hair); transition: background 120ms ease;"
                [style.background]="selected()?.id === sk.id ? 'var(--ck-bg-inset)' : 'transparent'"
                onmouseover="this.style.background='var(--ck-bg-inset)'"
                onmouseout="this.style.background=this.dataset.sel==='1'?'var(--ck-bg-inset)':'transparent'"
              >
                <ck-tag [tone]="certTone(sk.certification_level)" variant="outline">
                  {{ (sk.certification_level || 'basic').slice(0, 4).toUpperCase() }}
                </ck-tag>
                <div class="min-w-0">
                  <div class="text-sm text-white font-medium">{{ sk.name }}</div>
                  <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
                    {{ sk.slug }}<span style="color:var(--ck-fg-5); margin:0 4px;">·</span>{{ sk.version || 'v1' }}
                  </div>
                </div>
                <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-3);">{{ sk.type || '—' }}</span>
                <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2); text-align:right;">
                  {{ formatNum(sk.metrics?.calls) }}
                </span>
                <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2); text-align:right;">
                  {{ formatLatency(sk.metrics?.avg_latency_ms) }}
                </span>
                <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2); text-align:right;">
                  {{ formatPrice(sk.metrics?.total_cost) }}
                </span>
                <span class="ck-mono ck-tnum" style="font-size:11px; text-align:right;" [style.color]="successColor(sk.metrics?.success_rate)">
                  {{ formatPct(sk.metrics?.success_rate) }}
                </span>
                <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-1); text-align:right;">
                  {{ formatPrice(sk.pricing?.unit_price) }}
                </span>
              </div>
            }
          </div>
        }

        <!-- Drill-down -->
        @if (selected(); as sk) {
          <section class="ck-surface rounded-md" style="padding:24px 28px;">
            <div class="flex items-start justify-between gap-4 mb-4">
              <div>
                <div class="flex items-center gap-2 mb-2">
                  <ck-tag [tone]="certTone(sk.certification_level)" variant="solid">
                    {{ (sk.certification_level || 'basic').toUpperCase() }}
                  </ck-tag>
                  <ck-tag tone="cool" variant="outline">{{ sk.type || 'GENERIC' }}</ck-tag>
                  <ck-tag tone="violet" variant="outline">{{ sk.version || 'v1' }}</ck-tag>
                </div>
                <h3 class="text-xl font-medium text-white">{{ sk.name }}</h3>
                <p class="ck-mono" style="font-size:11px; color:var(--ck-fg-4); margin-top:4px;">{{ sk.slug }}</p>
              </div>
              <button
                type="button"
                (click)="selected.set(null)"
                class="ck-mono"
                style="padding:6px 10px; border-radius:4px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-bg-inset); color:var(--ck-fg-3); border:1px solid var(--ck-stroke-soft);"
              >
                CLOSE
              </button>
            </div>

            <p class="text-sm text-white mb-6" style="line-height:1.6;">{{ sk.description || '—' }}</p>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                  INPUT CONTRACT
                </div>
                <pre class="ck-mono" style="font-size:10px; color:var(--ck-fg-2); margin:0; background:var(--ck-bg-inset); padding:12px; border-radius:4px; white-space:pre-wrap; max-height:180px; overflow:auto;">{{ formatJson(sk.input_schema) }}</pre>
              </div>
              <div>
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                  OUTPUT CONTRACT
                </div>
                <pre class="ck-mono" style="font-size:10px; color:var(--ck-fg-2); margin:0; background:var(--ck-bg-inset); padding:12px; border-radius:4px; white-space:pre-wrap; max-height:180px; overflow:auto;">{{ formatJson(sk.output_schema) }}</pre>
              </div>

              <div>
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                  EXECUTION
                </div>
                <div class="ck-surface rounded-md" style="padding:12px; display:flex; flex-direction:column; gap:6px;">
                  @for (row of execRows(sk); track row.k) {
                    <div class="flex items-center justify-between">
                      <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">{{ row.k }}</span>
                      <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-1);">{{ row.v }}</span>
                    </div>
                  }
                </div>
              </div>

              <div>
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                  LIVE PERFORMANCE
                </div>
                <div class="ck-surface rounded-md" style="padding:14px 16px; display:flex; flex-direction:column; gap:10px;">
                  <div class="flex items-center justify-between">
                    <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">SUCCESS RATE</span>
                    <div style="display:flex; align-items:center; gap:8px;">
                      <ck-micro-bar
                        [value]="(sk.metrics?.success_rate ?? 0) * 100"
                        [max]="100"
                        [width]="100"
                        [tone]="(sk.metrics?.success_rate ?? 0) >= 0.95 ? 'pos' : ((sk.metrics?.success_rate ?? 0) >= 0.85 ? 'warn' : 'neg')"
                      />
                      <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-1); min-width:44px; text-align:right;">
                        {{ formatPct(sk.metrics?.success_rate) }}
                      </span>
                    </div>
                  </div>
                  <div class="flex items-center justify-between">
                    <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">CALLS</span>
                    <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-1);">{{ formatNum(sk.metrics?.calls) }}</span>
                  </div>
                  <div class="flex items-center justify-between">
                    <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">AVG LATENCY</span>
                    <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-1);">{{ formatLatency(sk.metrics?.avg_latency_ms) }}</span>
                  </div>
                  <div class="flex items-center justify-between">
                    <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">TOTAL COST</span>
                    <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-1);">{{ formatPrice(sk.metrics?.total_cost) }}</span>
                  </div>
                  <div class="flex items-center justify-between">
                    <span class="ck-mono" style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);">PROVIDER</span>
                    <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-2);">{{ sk.provider || 'omnirag' }}</span>
                  </div>
                </div>
              </div>
            </div>
          </section>
        }
      </div>
    </ck-page-frame>
  `,
})
export class SkillsComponent implements OnInit {
  private readonly canonical = inject(CanonicalApiService);

  readonly certs: { id: CertFilter; label: string }[] = [
    { id: 'all', label: 'ALL' },
    { id: 'basic', label: 'BASIC' },
    { id: 'production', label: 'PRODUCTION' },
    { id: 'enterprise', label: 'ENTERPRISE' },
  ];

  readonly skills = signal<Skill[]>([]);
  readonly loading = signal(true);
  readonly cert = signal<CertFilter>('all');
  readonly query = signal('');
  readonly selected = signal<Skill | null>(null);

  readonly filtered = computed(() => {
    const c = this.cert();
    const q = this.query().trim().toLowerCase();
    return this.skills().filter((s) => {
      if (c !== 'all' && (s.certification_level || 'basic') !== c) return false;
      if (!q) return true;
      return (
        s.name.toLowerCase().includes(q) ||
        (s.slug || '').toLowerCase().includes(q) ||
        (s.description || '').toLowerCase().includes(q) ||
        (s.type || '').toLowerCase().includes(q)
      );
    });
  });

  readonly totals = computed(() => {
    const list = this.skills();
    if (!list.length) return { calls: 0, avgLatency: 0, successRate: 0 };
    let calls = 0;
    let latSum = 0;
    let latN = 0;
    let okSum = 0;
    let okN = 0;
    for (const s of list) {
      const m = s.metrics ?? {};
      calls += m.calls ?? 0;
      if (m.avg_latency_ms != null) {
        latSum += m.avg_latency_ms;
        latN += 1;
      }
      if (m.success_rate != null) {
        okSum += m.success_rate;
        okN += 1;
      }
    }
    return {
      calls,
      avgLatency: latN ? latSum / latN : 0,
      successRate: okN ? okSum / okN : 0,
    };
  });

  ngOnInit(): void {
    this.canonical.listSkills().subscribe((list) => {
      this.skills.set(list);
      this.loading.set(false);
    });
  }

  execRows(sk: Skill): Array<{ k: string; v: string }> {
    const e = sk.execution ?? {};
    const rows: Array<{ k: string; v: string }> = [];
    rows.push({ k: 'MODE', v: (e.mode || 'sync').toUpperCase() });
    rows.push({ k: 'TIMEOUT', v: e.timeout_ms != null ? `${e.timeout_ms} ms` : '—' });
    rows.push({ k: 'RETRYABLE', v: e.retryable ? 'YES' : 'NO' });
    rows.push({ k: 'IDEMPOTENT', v: e.idempotent ? 'YES' : 'NO' });
    return rows;
  }

  certTone(cert: string | undefined): 'pos' | 'cool' | 'violet' {
    if (cert === 'enterprise') return 'violet';
    if (cert === 'production') return 'pos';
    return 'cool';
  }

  successColor(rate: number | undefined): string {
    if (rate == null) return 'var(--ck-fg-3)';
    if (rate >= 0.95) return 'var(--ck-pos)';
    if (rate >= 0.85) return 'var(--ck-warn)';
    return 'var(--ck-neg)';
  }

  formatNum(v: number | undefined): string {
    if (v == null) return '—';
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
    if (v >= 1_000) return `${(v / 1_000).toFixed(1)}k`;
    return v.toString();
  }

  formatLatency(v: number | undefined): string {
    if (v == null) return '—';
    if (v >= 1000) return `${(v / 1000).toFixed(2)} s`;
    return `${Math.round(v)} ms`;
  }

  formatPct(v: number | undefined): string {
    if (v == null) return '—';
    return `${(v * 100).toFixed(1)}%`;
  }

  formatPrice(v: number | null | undefined): string {
    if (v == null) return '—';
    if (v < 0.01) return `$${v.toFixed(4)}`;
    if (v < 1) return `$${v.toFixed(3)}`;
    if (v < 100) return `$${v.toFixed(2)}`;
    return `$${Math.round(v)}`;
  }

  formatJson(v: Record<string, unknown> | undefined): string {
    if (!v || Object.keys(v).length === 0) return '—';
    return JSON.stringify(v, null, 2);
  }

  asInput(ev: Event): HTMLInputElement {
    return ev.target as HTMLInputElement;
  }
}
