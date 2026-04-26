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
  type WhatIfResult,
  type DecisionRow,
  type DecisionDetail,
} from '@app/core/canonical-api.service';
import {
  GlyphComponent,
  KbdComponent,
  LiveDotComponent,
  MicroBarComponent,
  PageFrameComponent,
  StatReadoutComponent,
  TagComponent,
  HelpTooltipComponent,
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
    HelpTooltipComponent,
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
                <ck-help id="hypervisor.balance-sheet.overview" />
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
              <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
                ranked by {{ rankByLabel() }}
              </span>
              <ck-help id="hypervisor.balance-sheet.scale-capability" />
            </div>
            <div class="flex items-center gap-3">
              <div class="flex items-center gap-1 ck-surface rounded" style="padding:2px; background:var(--ck-bg-inset);">
                @for (r of rankOptions; track r.id) {
                  <button
                    type="button"
                    (click)="setRankBy(r.id)"
                    class="ck-mono"
                    style="padding:4px 10px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase;"
                    [style.background]="rankBy() === r.id ? 'var(--ck-bg-raised)' : 'transparent'"
                    [style.color]="rankBy() === r.id ? 'var(--ck-fg-1)' : 'var(--ck-fg-4)'"
                  >
                    {{ r.label }}
                  </button>
                }
              </div>
              <a
                routerLink="/capabilities"
                class="ck-mono"
                style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-3);"
              >
                FULL CATALOG →
              </a>
            </div>
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
                  <th style="text-align:right; padding:8px 10px; font-weight:500; border-bottom: 1px solid var(--ck-hair); width:90px;">EFFICIENCY</th>
                  <th style="text-align:right; padding:8px 10px; font-weight:500; border-bottom: 1px solid var(--ck-hair); width:170px;">ACTIONS</th>
                </tr>
              </thead>
              <tbody>
                @for (c of rankedCapabilities(); track c.capability_id) {
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
                    <td class="ck-mono ck-tnum" style="padding:10px; font-size:12px; text-align:right;" [style.color]="efficiencyColor(c.avg_efficiency)">
                      {{ formatIndex(c.avg_efficiency) }}
                    </td>
                    <td style="padding:8px;" (click)="$event.stopPropagation()">
                      <div style="display:flex; gap:4px; justify-content:flex-end;">
                        <button
                          type="button"
                          (click)="openRuns(c)"
                          title="Drill into Runs for this capability"
                          class="ck-mono"
                          style="padding:4px 8px; border-radius:3px; font-size:9px; letter-spacing:0.12em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-3); background:transparent;"
                        >
                          RUNS
                        </button>
                        <button
                          type="button"
                          (click)="proposeScale(c)"
                          [disabled]="proposingFor() === c.capability_id"
                          title="Propose a scale decision for this capability"
                          class="ck-mono"
                          style="padding:4px 8px; border-radius:3px; font-size:9px; letter-spacing:0.12em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); background:var(--ck-bg-inset);"
                          [style.color]="proposingFor() === c.capability_id ? 'var(--ck-fg-4)' : 'var(--ck-signal-pos)'"
                        >
                          {{ proposingFor() === c.capability_id ? '…' : 'SCALE' }}
                        </button>
                        <button
                          type="button"
                          (click)="proposeAdjust(c)"
                          [disabled]="proposingFor() === c.capability_id"
                          title="Propose an adjust decision (tighten/relax policies)"
                          class="ck-mono"
                          style="padding:4px 8px; border-radius:3px; font-size:9px; letter-spacing:0.12em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); background:var(--ck-bg-inset);"
                          [style.color]="proposingFor() === c.capability_id ? 'var(--ck-fg-4)' : 'var(--ck-signal-cool)'"
                        >
                          ADJUST
                        </button>
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
              <button
                type="button"
                (click)="generateRecommendations()"
                [disabled]="generatingRecommendations()"
                class="ck-mono"
                style="padding:4px 8px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-2); background:var(--ck-bg-inset);"
              >
                {{ generatingRecommendations() ? 'SCANNING…' : 'SCAN' }}
              </button>
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

        <!-- Portfolio what-if: 4 global levers -->
        <section class="ck-surface rounded-md" style="padding:20px 24px;">
          <div class="flex items-center justify-between mb-5">
            <div class="flex items-center gap-2">
              <ck-glyph name="crosshair" [size]="14" />
              <h3 class="ck-mono" style="font-size:11px; letter-spacing:0.18em; text-transform:uppercase; color:var(--ck-fg-2);">
                PORTFOLIO WHAT-IF
              </h3>
              <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
                4 global levers · live projection
              </span>
              <ck-help id="hypervisor.what-if.run" />
            </div>
            <button
              type="button"
              (click)="resetLevers()"
              class="ck-mono"
              style="padding:5px 10px; border-radius:3px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-3); background:var(--ck-bg-inset);"
            >
              RESET
            </button>
          </div>
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- Levers -->
            <div class="flex flex-col gap-5">
              @for (l of leverList; track l.key) {
                <div>
                  <div class="flex items-center justify-between mb-1">
                    <div class="flex items-center gap-2">
                      <ck-tag [tone]="l.tone" variant="outline">{{ l.label }}</ck-tag>
                      <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">{{ l.hint }}</span>
                    </div>
                    <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2);">
                      {{ (leverValue(l.key) * 100).toFixed(0) }}%
                    </span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.01"
                    [value]="leverValue(l.key)"
                    (input)="onLeverInput(l.key, $event)"
                    class="w-full accent-cyan-400"
                  />
                </div>
              }
            </div>
            <!-- Projection -->
            <div class="ck-surface rounded" style="padding:16px 18px; background:var(--ck-bg-inset); min-height:200px;">
              <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:12px;">
                PROJECTED PORTFOLIO
              </div>
              @if (!whatIf()) {
                <div class="ck-mono" style="font-size:11px; color:var(--ck-fg-4); text-align:center; padding:18px 0;">
                  MOVE A LEVER TO PROJECT
                </div>
              } @else {
                <div class="grid grid-cols-2 gap-4">
                  <div>
                    <div class="ck-mono" style="font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">COST</div>
                    <div class="ck-mono ck-tnum" style="font-size:16px; color:var(--ck-fg-1); margin-top:2px;">
                      {{ formatCurrencyLarge(whatIf()!.projected.total_cost) }}
                    </div>
                    <div class="ck-mono ck-tnum" style="font-size:10px; margin-top:2px;" [style.color]="deltaColor(-(whatIf()!.projected.total_cost - (whatIf()!.base.total_cost ?? 0)))">
                      {{ formatSigned(whatIf()!.projected.total_cost - (whatIf()!.base.total_cost ?? 0)) }}
                    </div>
                  </div>
                  <div>
                    <div class="ck-mono" style="font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">VALUE</div>
                    <div class="ck-mono ck-tnum" style="font-size:16px; color:var(--ck-fg-1); margin-top:2px;">
                      {{ formatCurrencyLarge(whatIf()!.projected.estimated_value) }}
                    </div>
                    <div class="ck-mono ck-tnum" style="font-size:10px; margin-top:2px;" [style.color]="deltaColor(whatIf()!.projected.estimated_value - (whatIf()!.base.estimated_value ?? 0))">
                      {{ formatSigned(whatIf()!.projected.estimated_value - (whatIf()!.base.estimated_value ?? 0)) }}
                    </div>
                  </div>
                  <div>
                    <div class="ck-mono" style="font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">ROI</div>
                    <div class="ck-mono ck-tnum" style="font-size:16px; margin-top:2px;" [style.color]="roiColor(whatIf()!.projected.roi)">
                      {{ formatRoi(whatIf()!.projected.roi) }}
                    </div>
                  </div>
                  <div>
                    <div class="ck-mono" style="font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">LATENCY</div>
                    <div class="ck-mono ck-tnum" style="font-size:16px; color:var(--ck-fg-1); margin-top:2px;">
                      {{ formatIndex(whatIf()!.projected.latency_index) }}x
                    </div>
                    <div class="ck-mono ck-tnum" style="font-size:10px; margin-top:2px;" [style.color]="deltaColor(-(whatIf()!.projected.latency_index - 1))">
                      {{ formatSigned((whatIf()!.projected.latency_index - 1) * 100) }}%
                    </div>
                  </div>
                </div>
              }
            </div>
          </div>
        </section>

        <!-- Decisions feed -->
        <section class="ck-surface rounded-md" style="padding:18px 22px;">
          <div class="flex items-center justify-between mb-4">
            <div class="flex items-center gap-2">
              <ck-glyph name="ledger" [size]="14" />
              <h3 class="ck-mono" style="font-size:11px; letter-spacing:0.18em; text-transform:uppercase; color:var(--ck-fg-2);">
                DECISIONS
              </h3>
              <span class="ck-mono ck-tnum" style="font-size:10px; color:var(--ck-fg-4);">
                {{ decisions().length }}/{{ decisionsTotal() }}
              </span>
              <ck-help id="hypervisor.decisions.feed" />
            </div>
            <div class="flex items-center gap-1 ck-surface rounded" style="padding:2px; background:var(--ck-bg-inset);">
              @for (s of statusFilters; track s.id) {
                <button
                  type="button"
                  (click)="setDecisionStatus(s.id)"
                  class="ck-mono"
                  style="padding:4px 10px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase;"
                  [style.background]="decisionStatus() === s.id ? 'var(--ck-bg-raised)' : 'transparent'"
                  [style.color]="decisionStatus() === s.id ? 'var(--ck-fg-1)' : 'var(--ck-fg-4)'"
                >
                  {{ s.label }}
                </button>
              }
            </div>
          </div>
          @if (decisionsLoading() && !decisions().length) {
            <div class="ck-mono" style="padding:18px 0; font-size:11px; color:var(--ck-fg-4); text-align:center;">
              LOADING DECISIONS…
            </div>
          } @else if (!decisions().length) {
            <div class="ck-mono" style="padding:24px 0; font-size:11px; color:var(--ck-fg-4); text-align:center;">
              NO DECISION FOR THIS FILTER
            </div>
          } @else {
            <ul style="display:flex; flex-direction:column; gap:6px;">
              @for (d of decisions(); track d.id) {
                <li
                  class="ck-surface rounded"
                  style="padding:10px 12px; background:var(--ck-bg-inset); cursor:pointer;"
                  (click)="openDecision(d.id)"
                >
                  <div class="flex items-center gap-2 mb-1">
                    <ck-tag [tone]="decisionTone(d.status)" variant="soft">{{ d.status }}</ck-tag>
                    <ck-tag tone="cool" variant="outline">{{ d.kind }}</ck-tag>
                    <ck-tag tone="violet" variant="outline">{{ d.scope }}</ck-tag>
                    <span class="text-sm text-white font-medium truncate">{{ d.title }}</span>
                    <span class="ml-auto ck-mono ck-tnum" style="font-size:10px; color:var(--ck-fg-4);">
                      {{ formatRelative(d.created_at) }}
                    </span>
                  </div>
                  <div (click)="$event.stopPropagation()" style="display:flex; gap:4px; margin-top:6px;">
                    @if (d.status === 'proposed') {
                      <button
                        type="button"
                        (click)="accept(d.id)"
                        [disabled]="busyDecisionId() === d.id"
                        class="ck-mono"
                        style="padding:4px 10px; border-radius:3px; font-size:9px; letter-spacing:0.14em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-signal-pos); background:transparent;"
                      >ACCEPT</button>
                      <button
                        type="button"
                        (click)="reject(d.id)"
                        [disabled]="busyDecisionId() === d.id"
                        class="ck-mono"
                        style="padding:4px 10px; border-radius:3px; font-size:9px; letter-spacing:0.14em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-signal-neg); background:transparent;"
                      >REJECT</button>
                    } @else if (d.status === 'accepted') {
                      <button
                        type="button"
                        (click)="apply(d.id)"
                        [disabled]="busyDecisionId() === d.id"
                        class="ck-mono"
                        style="padding:4px 10px; border-radius:3px; font-size:9px; letter-spacing:0.14em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-1); background:var(--ck-bg-raised);"
                      >APPLY</button>
                    } @else if (d.status === 'applied' && d.applied_at) {
                      <span class="ck-mono" style="font-size:9px; color:var(--ck-fg-4); letter-spacing:0.12em;">
                        APPLIED {{ formatRelative(d.applied_at) }}
                      </span>
                    }
                  </div>
                </li>
              }
            </ul>
            @if (decisions().length < decisionsTotal()) {
              <div style="margin-top:12px; text-align:center;">
                <button
                  type="button"
                  (click)="loadMoreDecisions()"
                  [disabled]="decisionsLoading()"
                  class="ck-mono"
                  style="padding:6px 12px; border-radius:3px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-2); background:var(--ck-bg-inset);"
                >
                  {{ decisionsLoading() ? 'LOADING…' : 'LOAD MORE' }}
                </button>
              </div>
            }
          }
        </section>

        <!-- Decision drawer -->
        @if (selectedDecision(); as d) {
          <div
            style="position:fixed; inset:0; background:rgba(3,6,18,0.55); backdrop-filter:blur(6px); z-index:60; display:flex; justify-content:flex-end;"
            (click)="closeDecision()"
          >
            <aside
              class="ck-surface"
              style="width:min(480px, 92vw); height:100%; padding:22px 26px; overflow:auto; background:var(--ck-bg-panel); border-left:1px solid var(--ck-stroke-2);"
              (click)="$event.stopPropagation()"
            >
              <div class="flex items-center justify-between mb-3">
                <div class="ck-mono" style="font-size:10px; letter-spacing:0.18em; text-transform:uppercase; color:var(--ck-fg-4);">
                  DECISION · {{ d.id.slice(0, 8) }}
                </div>
                <button
                  type="button"
                  (click)="closeDecision()"
                  class="ck-mono"
                  style="padding:4px 8px; border-radius:3px; font-size:10px; color:var(--ck-fg-3); background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-soft);"
                >
                  CLOSE
                </button>
              </div>
              <h2 class="text-lg font-semibold text-white mb-1">{{ d.title }}</h2>
              <div class="flex items-center gap-2 mb-4">
                <ck-tag [tone]="decisionTone(d.status)" variant="soft">{{ d.status }}</ck-tag>
                <ck-tag tone="cool" variant="outline">{{ d.kind }}</ck-tag>
                <ck-tag tone="violet" variant="outline">{{ d.scope }}</ck-tag>
              </div>
              @if (d.impact_estimate && objectKeys(d.impact_estimate).length > 0) {
                <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-3); margin-bottom:12px;">
                  <div style="font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:6px;">IMPACT ESTIMATE</div>
                  <div style="display:flex; gap:14px; flex-wrap:wrap;">
                    @for (k of objectKeys(d.impact_estimate); track k) {
                      <span>
                        {{ k.toUpperCase() }}
                        <span class="ck-tnum" style="color:var(--ck-fg-1);">
                          {{ formatImpact(decisionImpactValue(d, k)) }}
                        </span>
                      </span>
                    }
                  </div>
                </div>
              }
              @if (d.rationale && objectKeys(d.rationale).length > 0) {
                <div class="mb-3">
                  <div class="ck-mono" style="font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:4px;">RATIONALE</div>
                  <pre class="ck-mono" style="font-size:11px; color:var(--ck-fg-2); white-space:pre-wrap; word-break:break-word; background:var(--ck-bg-inset); padding:10px; border-radius:4px;">{{ jsonText(d.rationale) }}</pre>
                </div>
              }
              @if (d.notes) {
                <div class="mb-3">
                  <div class="ck-mono" style="font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:4px;">NOTES</div>
                  <div class="text-sm text-gray-200 whitespace-pre-wrap">{{ d.notes }}</div>
                </div>
              }
              <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
                CREATED {{ d.created_at || '—' }}
                @if (d.approved_by) { · APPROVED BY {{ d.approved_by }} }
                @if (d.applied_at) { · APPLIED {{ formatRelative(d.applied_at) }} }
              </div>
              <div style="display:flex; gap:6px; margin-top:16px; align-items:center;">
                @if (d.status === 'proposed') {
                  <button
                    type="button"
                    (click)="accept(d.id, true)"
                    [disabled]="busyDecisionId() === d.id"
                    class="ck-mono"
                    style="padding:6px 14px; border-radius:3px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-signal-pos); background:transparent;"
                  >ACCEPT</button>
                  <ck-help id="hypervisor.decisions.accept" />
                  <button
                    type="button"
                    (click)="reject(d.id, true)"
                    [disabled]="busyDecisionId() === d.id"
                    class="ck-mono"
                    style="padding:6px 14px; border-radius:3px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-signal-neg); background:transparent;"
                  >REJECT</button>
                  <ck-help id="hypervisor.decisions.reject" />
                } @else if (d.status === 'accepted') {
                  <button
                    type="button"
                    (click)="apply(d.id, true)"
                    [disabled]="busyDecisionId() === d.id"
                    class="ck-mono"
                    style="padding:6px 14px; border-radius:3px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-1); background:var(--ck-bg-raised);"
                  >APPLY — enact</button>
                  <ck-help id="hypervisor.decisions.apply" />
                }
              </div>
              @if (d.applied_patch && objectKeys(d.applied_patch).length > 0) {
                <div class="mt-4">
                  <div class="ck-mono" style="font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:4px;">APPLIED PATCH</div>
                  <pre class="ck-mono" style="font-size:11px; color:var(--ck-fg-2); white-space:pre-wrap; word-break:break-word; background:var(--ck-bg-inset); padding:10px; border-radius:4px;">{{ jsonText(d.applied_patch) }}</pre>
                </div>
              }
            </aside>
          </div>
        }
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
  readonly generatingRecommendations = signal(false);

  // ---- Portfolio What-If ---------------------------------------------------
  readonly leverList = [
    { key: 'resource',  label: 'RESOURCE',  tone: 'cool'   as const, hint: 'lean → deep' },
    { key: 'velocity',  label: 'VELOCITY',  tone: 'violet' as const, hint: 'thorough → rapid' },
    { key: 'autonomy',  label: 'AUTONOMY',  tone: 'pos'    as const, hint: 'HITL → full' },
    { key: 'risk_tolerance', label: 'RISK', tone: 'warn'   as const, hint: 'cautious → bold' },
  ];
  readonly levers = signal<Record<string, number>>({
    resource: 0.5,
    velocity: 0.5,
    autonomy: 0.3,
    risk_tolerance: 0.4,
  });
  readonly whatIf = signal<WhatIfResult | null>(null);
  private whatIfTimer: number | null = null;

  // ---- Decisions feed ------------------------------------------------------
  readonly statusFilters: Array<{ id: 'all' | 'proposed' | 'accepted' | 'rejected' | 'applied'; label: string }> = [
    { id: 'all', label: 'ALL' },
    { id: 'proposed', label: 'PROPOSED' },
    { id: 'accepted', label: 'ACCEPTED' },
    { id: 'rejected', label: 'REJECTED' },
    { id: 'applied', label: 'APPLIED' },
  ];
  readonly decisionStatus = signal<'all' | 'proposed' | 'accepted' | 'rejected' | 'applied'>('all');
  readonly busyDecisionId = signal<string | null>(null);

  // ---- Capability ranking --------------------------------------------------
  readonly rankOptions: Array<{ id: 'efficiency' | 'roi' | 'value' | 'runs'; label: string }> = [
    { id: 'efficiency', label: 'EFFICIENCY' },
    { id: 'roi', label: 'ROI' },
    { id: 'value', label: 'VALUE' },
    { id: 'runs', label: 'RUNS' },
  ];
  readonly rankBy = signal<'efficiency' | 'roi' | 'value' | 'runs'>('efficiency');
  readonly proposingFor = signal<string | null>(null);
  readonly decisions = signal<DecisionRow[]>([]);
  readonly decisionsTotal = signal(0);
  readonly decisionsLoading = signal(false);
  readonly decisionsPage = signal(0);
  readonly pageSize = 20;

  readonly selectedDecision = signal<DecisionDetail | null>(null);

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
    this.refreshDecisions();
    this.runWhatIf();
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

  generateRecommendations(): void {
    if (this.generatingRecommendations()) return;
    this.generatingRecommendations.set(true);
    this.canonical.generateProactiveRecommendations({
      since_days: 7,
      min_evaluations: 3,
      min_breaches: 2,
      min_breach_rate: 0.5,
      actor: 'hypervisor',
    }).subscribe({
      next: () => {
        this.generatingRecommendations.set(false);
        this.loadAll();
        this.refreshDecisions();
      },
      error: () => this.generatingRecommendations.set(false),
    });
  }

  // ---- What-If -------------------------------------------------------------
  leverValue(key: string): number {
    return this.levers()[key] ?? 0.5;
  }

  onLeverInput(key: string, ev: Event): void {
    const target = ev.target as HTMLInputElement | null;
    if (!target) return;
    const value = Number(target.value);
    this.levers.update((l) => ({ ...l, [key]: value }));
    // Debounce so quick drags don't hammer the endpoint.
    if (this.whatIfTimer) window.clearTimeout(this.whatIfTimer);
    this.whatIfTimer = window.setTimeout(() => this.runWhatIf(), 200);
  }

  resetLevers(): void {
    this.levers.set({ resource: 0.5, velocity: 0.5, autonomy: 0.3, risk_tolerance: 0.4 });
    this.runWhatIf();
  }

  private runWhatIf(): void {
    this.canonical
      .hypervisorWhatIf({ scope: 'portfolio', target_id: null, levers: this.levers() })
      .subscribe((r) => this.whatIf.set(r));
  }

  // ---- Decisions feed ------------------------------------------------------
  setDecisionStatus(status: 'all' | 'proposed' | 'accepted' | 'rejected' | 'applied'): void {
    this.decisionStatus.set(status);
    this.decisionsPage.set(0);
    this.decisions.set([]);
    this.refreshDecisions();
  }

  rankByLabel = computed(() => this.rankOptions.find((o) => o.id === this.rankBy())?.label ?? 'EFFICIENCY');

  setRankBy(id: 'efficiency' | 'roi' | 'value' | 'runs'): void {
    this.rankBy.set(id);
  }

  readonly rankedCapabilities = computed<CapabilityRow[]>(() => {
    const rows = [...this.capabilities()];
    const key = this.rankBy();
    const get = (row: CapabilityRow): number => {
      switch (key) {
        case 'roi': return row.roi ?? -Infinity;
        case 'value': return row.estimated_value ?? 0;
        case 'runs': return row.runs_count ?? 0;
        case 'efficiency':
        default: return row.avg_efficiency ?? -Infinity;
      }
    };
    rows.sort((a, b) => get(b) - get(a));
    return rows;
  });

  openRuns(c: CapabilityRow): void {
    this.router.navigate(['/runs'], { queryParams: { capability_id: c.capability_id } });
  }

  proposeScale(c: CapabilityRow): void {
    this.proposingFor.set(c.capability_id);
    const factor = 1.15;
    this.canonical
      .hypervisorWhatIf({ scope: 'capability', target_id: c.capability_id, levers: { resource: 0.7, velocity: 0.5, autonomy: 0.4, risk_tolerance: 0.5 } })
      .subscribe((sim) => {
        const impact = sim?.projected
          ? {
              cost_delta: (sim.projected.total_cost ?? 0) - (sim.base.total_cost ?? 0),
              value_delta: (sim.projected.estimated_value ?? 0) - (sim.base.estimated_value ?? 0),
              roi: sim.projected.roi,
            }
          : {};
        this.canonical
          .createDecision({
            scope: 'capability',
            target_id: c.capability_id,
            kind: 'recommendation',
            title: `Scale ${c.name} (+${Math.round((factor - 1) * 100)}%)`,
            status: 'proposed',
            rationale: { action: 'scale', capability_id: c.capability_id, factor, source: 'hypervisor-cta' },
            impact_estimate: impact,
          })
          .subscribe(() => {
            this.proposingFor.set(null);
            this.refreshDecisions();
          });
      });
  }

  proposeAdjust(c: CapabilityRow): void {
    this.proposingFor.set(c.capability_id);
    this.canonical
      .createDecision({
        scope: 'capability',
        target_id: c.capability_id,
        kind: 'recommendation',
        title: `Tighten guardrails on ${c.name}`,
        status: 'proposed',
        rationale: {
          action: 'adjust',
          policy_updates: { mandatory_hitl_if_confidence_below: 0.7 },
          source: 'hypervisor-cta',
        },
        impact_estimate: { risk: -0.2 },
      })
      .subscribe(() => {
        this.proposingFor.set(null);
        this.refreshDecisions();
      });
  }

  efficiencyColor(v: number | null | undefined): string {
    if (v == null) return 'var(--ck-fg-3)';
    if (v >= 1.5) return 'var(--ck-signal-pos)';
    if (v >= 0.5) return 'var(--ck-signal-cool)';
    return 'var(--ck-signal-neg)';
  }

  accept(id: string, refreshDrawer = false): void {
    this.busyDecisionId.set(id);
    this.canonical.acceptDecision(id).subscribe((detail) => {
      this.busyDecisionId.set(null);
      if (detail && refreshDrawer) this.selectedDecision.set(detail);
      this.refreshDecisions();
    });
  }

  reject(id: string, refreshDrawer = false): void {
    this.busyDecisionId.set(id);
    this.canonical.rejectDecision(id).subscribe((detail) => {
      this.busyDecisionId.set(null);
      if (detail && refreshDrawer) this.selectedDecision.set(detail);
      this.refreshDecisions();
    });
  }

  apply(id: string, refreshDrawer = false): void {
    this.busyDecisionId.set(id);
    this.canonical.applyDecision(id, { enact: true }).subscribe((detail) => {
      this.busyDecisionId.set(null);
      if (detail && refreshDrawer) this.selectedDecision.set(detail);
      this.refreshDecisions();
    });
  }

  loadMoreDecisions(): void {
    this.decisionsPage.update((p) => p + 1);
    this.refreshDecisions({ append: true });
  }

  private refreshDecisions(opts: { append?: boolean } = {}): void {
    this.decisionsLoading.set(true);
    const status = this.decisionStatus();
    const offset = this.decisionsPage() * this.pageSize;
    this.canonical
      .listDecisions({
        status: status === 'all' ? undefined : status,
        limit: this.pageSize,
        offset,
      })
      .subscribe((res) => {
        if (opts.append) {
          this.decisions.update((list) => [...list, ...res.items]);
        } else {
          this.decisions.set(res.items);
        }
        this.decisionsTotal.set(res.total);
        this.decisionsLoading.set(false);
      });
  }

  openDecision(id: string): void {
    this.canonical.getDecision(id).subscribe((d) => this.selectedDecision.set(d));
  }

  closeDecision(): void {
    this.selectedDecision.set(null);
  }

  decisionImpactValue(d: DecisionDetail, key: string): number {
    const v = (d.impact_estimate || {})[key];
    return typeof v === 'number' ? v : Number(v ?? 0);
  }

  jsonText(v: unknown): string {
    try {
      return JSON.stringify(v, null, 2);
    } catch {
      return String(v);
    }
  }

  decisionTone(
    status: string,
  ): 'pos' | 'cool' | 'violet' | 'warn' | 'neg' | 'neutral' {
    switch (status) {
      case 'applied': return 'pos';
      case 'accepted': return 'cool';
      case 'rejected': return 'neg';
      case 'proposed':
      case 'open':
      default: return 'warn';
    }
  }

  formatRelative(ts: string | null | undefined): string {
    if (!ts) return '—';
    const d = new Date(ts);
    const diffSec = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (diffSec < 60) return `${Math.round(diffSec)}s ago`;
    if (diffSec < 3600) return `${Math.round(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.round(diffSec / 3600)}h ago`;
    return `${Math.round(diffSec / 86400)}d ago`;
  }

  formatSigned(v: number): string {
    const sign = v > 0 ? '+' : v < 0 ? '-' : '';
    const abs = Math.abs(v);
    if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
    return `${sign}$${abs.toFixed(2)}`;
  }

  deltaColor(v: number): string {
    if (v > 0) return 'var(--ck-signal-pos)';
    if (v < 0) return 'var(--ck-signal-neg)';
    return 'var(--ck-fg-2)';
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
