import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  CanonicalApiService,
  type Capability,
  type ControlPolicy,
  type AdaptivePolicy,
  type SimulateResult,
} from '@app/core/canonical-api.service';
import {
  GlyphComponent,
  HelpTooltipComponent,
  KbdComponent,
  LiveDotComponent,
  MicroBarComponent,
  PageFrameComponent,
  StatReadoutComponent,
  TagComponent,
} from '@app/shared/cockpit';
import { I18nService } from '@app/core/i18n.service';
import { measuredImpactDelta } from '@app/features/hypervisor/hypervisor-impact';

/**
 * Steering Cockpit — the control plane.
 *
 * Three canonical levers (resource / velocity / autonomy) feed the
 * `/control-plane/simulate` endpoint with a <300ms debounce so the
 * operator sees the projected cost / value / ROI / latency / risk live
 * as they move the sliders. Changes are NOT persisted — persistence
 * happens when the operator clicks "Apply to capability".
 */
@Component({
  selector: 'app-steering',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
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
      [eyebrow]="i18n.t('steering.page.eyebrow')"
      [title]="i18n.t('steering.page.title')"
      [description]="i18n.t('steering.page.description')"
    >
      <div class="flex flex-col gap-6">
        <!-- Scope selector -->
        <section class="ck-surface rounded-md" style="padding:14px 22px;">
          <div class="flex items-center gap-4 flex-wrap">
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
              {{ i18n.t('steering.scope.label') }}
            </span>
            <div class="flex items-center gap-1 ck-surface rounded" style="padding:3px; background:var(--ck-bg-inset);">
              <button
                type="button"
                (click)="selectCapability(null)"
                class="ck-mono"
                style="padding:5px 10px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase;"
                [style.background]="!targetCapability() ? 'var(--ck-bg-raised)' : 'transparent'"
                [style.color]="!targetCapability() ? 'var(--ck-fg-1)' : 'var(--ck-fg-4)'"
              >
                {{ i18n.t('hypervisor.scope.portfolio') }}
              </button>
              @for (c of capabilities(); track c.id) {
                <button
                  type="button"
                  (click)="selectCapability(c)"
                  class="ck-mono"
                  style="padding:5px 10px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase;"
                  [style.background]="targetCapability()?.id === c.id ? 'var(--ck-bg-raised)' : 'transparent'"
                  [style.color]="targetCapability()?.id === c.id ? 'var(--ck-fg-1)' : 'var(--ck-fg-4)'"
                >
                  {{ c.slug }}
                </button>
              }
            </div>
            <span class="ml-auto flex items-center gap-3">
              <ck-live-dot [tone]="sim() ? 'cool' : 'warn'" [label]="sim() ? i18n.t('steering.state.live_sim') : i18n.t('steering.state.no_data')" />
              <ck-kbd>⌘↵</ck-kbd>
            </span>
          </div>
        </section>

        @if (legacyPreviewEnabled) {
        <!-- Retired legacy projection + levers (kept gate-off during migration). -->
        <section class="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <!-- Levers -->
          <div class="lg:col-span-2 ck-surface rounded-md" style="padding:24px 28px;">
            <div class="flex items-center gap-2 mb-6">
              <ck-glyph name="sliders" [size]="14" />
              <h3 class="ck-mono" style="font-size:11px; letter-spacing:0.18em; text-transform:uppercase; color:var(--ck-fg-2);">
                LEVERS
              </h3>
            </div>

            <div class="flex flex-col gap-6">
              <!-- Resource lever -->
              <div>
                <div class="flex items-center justify-between mb-2">
                  <div class="flex items-center gap-2">
                    <ck-tag tone="cool" variant="outline">RESOURCE</ck-tag>
                    <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-3);">
                      {{ leverLabel('resource', resource()) }}
                    </span>
                    <ck-help id="steering.levers.resource" />
                  </div>
                  <span class="ck-mono ck-tnum" style="font-size:12px; color:var(--ck-signal-cool);">
                    {{ (resource() * 100).toFixed(0) }}%
                  </span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  [ngModel]="resource()"
                  (ngModelChange)="resource.set($event); onLeverChanged()"
                  class="w-full accent-cyan-400"
                />
                <div class="flex justify-between ck-mono" style="font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4); margin-top:4px;">
                  <span>LEAN</span>
                  <span>BALANCED</span>
                  <span>DEEP</span>
                </div>
              </div>

              <!-- Velocity lever -->
              <div>
                <div class="flex items-center justify-between mb-2">
                  <div class="flex items-center gap-2">
                    <ck-tag tone="violet" variant="outline">VELOCITY</ck-tag>
                    <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-3);">
                      {{ leverLabel('velocity', velocity()) }}
                    </span>
                    <ck-help id="steering.levers.velocity" />
                  </div>
                  <span class="ck-mono ck-tnum" style="font-size:12px; color:var(--ck-signal-violet);">
                    {{ (velocity() * 100).toFixed(0) }}%
                  </span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  [ngModel]="velocity()"
                  (ngModelChange)="velocity.set($event); onLeverChanged()"
                  class="w-full accent-sky-400"
                />
                <div class="flex justify-between ck-mono" style="font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4); margin-top:4px;">
                  <span>THOROUGH</span>
                  <span>NORMAL</span>
                  <span>RAPID</span>
                </div>
              </div>

              <!-- Autonomy lever -->
              <div>
                <div class="flex items-center justify-between mb-2">
                  <div class="flex items-center gap-2">
                    <ck-tag [tone]="autonomy() > 0.7 ? 'warn' : 'pos'" variant="outline">AUTONOMY</ck-tag>
                    <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-3);">
                      {{ leverLabel('autonomy', autonomy()) }}
                    </span>
                    <ck-help id="steering.levers.autonomy" />
                  </div>
                  <span
                    class="ck-mono ck-tnum"
                    style="font-size:12px;"
                    [style.color]="autonomy() > 0.7 ? 'var(--ck-signal-warn)' : 'var(--ck-signal-pos)'"
                  >
                    {{ (autonomy() * 100).toFixed(0) }}%
                  </span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  [ngModel]="autonomy()"
                  (ngModelChange)="autonomy.set($event); onLeverChanged()"
                  class="w-full accent-emerald-400"
                />
                <div class="flex justify-between ck-mono" style="font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4); margin-top:4px;">
                  <span>HITL</span>
                  <span>SUPERVISED</span>
                  <span>FULL</span>
                </div>
              </div>

              <!-- Risk tolerance lever (4th canonical axis) -->
              <div>
                <div class="flex items-center justify-between mb-2">
                  <div class="flex items-center gap-2">
                    <ck-tag [tone]="riskTolerance() > 0.7 ? 'warn' : 'cool'" variant="outline">RISK TOLERANCE</ck-tag>
                    <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-3);">
                      {{ leverLabel('risk_tolerance', riskTolerance()) }}
                    </span>
                    <ck-help id="steering.levers.risk-tolerance" />
                  </div>
                  <span
                    class="ck-mono ck-tnum"
                    style="font-size:12px;"
                    [style.color]="riskTolerance() > 0.7 ? 'var(--ck-signal-warn)' : 'var(--ck-fg-1)'"
                  >
                    {{ (riskTolerance() * 100).toFixed(0) }}%
                  </span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  [ngModel]="riskTolerance()"
                  (ngModelChange)="riskTolerance.set($event); onLeverChanged()"
                  class="w-full accent-amber-400"
                />
                <div class="flex justify-between ck-mono" style="font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4); margin-top:4px;">
                  <span>CAUTIOUS</span>
                  <span>BALANCED</span>
                  <span>BOLD</span>
                </div>
              </div>
            </div>

            <div class="flex items-center justify-between mt-6 pt-5" style="border-top:1px solid var(--ck-hair);">
              <button
                type="button"
                (click)="reset()"
                class="ck-mono"
                style="padding:6px 12px; border-radius:4px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-bg-inset); color:var(--ck-fg-3); border:1px solid var(--ck-stroke-soft);"
              >
                RESET
              </button>
              <button
                type="button"
                (click)="apply()"
                [disabled]="applying() || !sim()"
                class="ck-mono"
                style="padding:8px 16px; border-radius:4px; font-size:11px; letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-signal-pos); color:var(--ck-on-signal); font-weight:600;"
                [style.opacity]="applying() || !sim() ? '0.4' : '1'"
              >
                <ck-glyph name="bolt" [size]="12" />
                {{ applying() ? 'APPLYING…' : 'APPLY TO ' + (targetCapability()?.slug ?? 'PORTFOLIO').toUpperCase() }}
              </button>
            </div>
          </div>

          <!-- Projection -->
          <div class="ck-surface rounded-md ck-hero-ambient relative overflow-hidden" style="padding:22px 24px;">
            <div class="flex items-center gap-2 mb-5">
              <ck-glyph name="telemetry" [size]="14" />
              <h3 class="ck-mono" style="font-size:11px; letter-spacing:0.18em; text-transform:uppercase; color:var(--ck-fg-2);">
                PROJECTION
              </h3>
            </div>

            <div class="flex flex-col gap-4">
              <div>
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:4px;">
                  NET VALUE DELTA
                </div>
                <div class="flex items-baseline gap-2">
                  <span
                    class="ck-mono ck-tnum"
                    style="font-size:32px; font-weight:300; letter-spacing:-0.01em;"
                    [style.color]="deltaColor(netDelta())"
                  >
                    {{ formatSigned(netDelta()) }}
                  </span>
                  <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-3);">vs base</span>
                </div>
              </div>

              <div class="grid grid-cols-2 gap-3 pt-3" style="border-top: 1px solid var(--ck-hair);">
                <ck-stat-readout label="COST" [value]="formatCurrency(projected('total_cost'))" tone="cool" [size]="14" />
                <ck-stat-readout label="VALUE" [value]="formatCurrency(projected('estimated_value'))" tone="pos" [size]="14" />
                <ck-stat-readout label="ROI" [value]="formatRoi(projectedRoi())" [tone]="roiTone(projectedRoi())" [size]="14" />
                <ck-stat-readout label="LATENCY" [value]="formatIndex(projected('latency_index'))" tone="violet" [size]="14" />
              </div>

              <div class="pt-3" style="border-top: 1px solid var(--ck-hair);">
                <div class="flex items-center justify-between mb-1">
                  <span class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
                    RISK INDEX
                  </span>
                  <span class="ck-mono ck-tnum" style="font-size:11px;" [style.color]="riskColor()">
                    {{ formatIndex(projected('risk_index')) }}
                  </span>
                </div>
                <ck-micro-bar
                  [value]="(projected('risk_index') ?? 0) * 100"
                  [max]="100"
                  [width]="180"
                  [tone]="projected('risk_index') && (projected('risk_index') ?? 0) > 0.7 ? 'warn' : 'pos'"
                  [glow]="true"
                />
              </div>
            </div>
          </div>
        </section>
        } @else {
          <section class="ck-surface rounded-md" style="padding:22px 26px; border-color:var(--ck-signal-warn);">
            <div class="flex items-center gap-2 mb-2">
              <ck-glyph name="shield" [size]="14" />
              <h3 class="ck-mono" style="font-size:11px; letter-spacing:0.16em; color:var(--ck-fg-2);">
                {{ i18n.t('steering.value_loop.title') }}
              </h3>
            </div>
            <p class="ck-mono" style="font-size:11px; color:var(--ck-fg-3);">
              {{ i18n.t('steering.value_loop.not_configured') }}
            </p>
          </section>
        }

        <!-- Active policies -->
        <section class="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div class="ck-surface rounded-md" style="padding:18px 22px;">
            <div class="flex items-center justify-between mb-4">
              <div class="flex items-center gap-2">
                <ck-glyph name="ledger" [size]="14" />
                <h3 class="ck-mono" style="font-size:11px; letter-spacing:0.18em; text-transform:uppercase; color:var(--ck-fg-2);">
                  {{ i18n.t('steering.control.title') }}
                </h3>
              </div>
              <span class="ck-mono ck-tnum" style="font-size:10px; color:var(--ck-fg-4);">
                {{ controlPolicies().length }}
              </span>
            </div>
            @if (!controlPolicies().length) {
              <div class="ck-mono" style="font-size:11px; padding:24px 0; text-align:center; color:var(--ck-fg-4);">
                {{ i18n.t('steering.control.empty') }}
              </div>
            } @else {
              <ul style="display:flex; flex-direction:column; gap:6px;">
                @for (p of controlPolicies(); track p.id) {
                  <li class="ck-surface rounded" style="padding:10px 12px; background:var(--ck-bg-inset);">
                    <div class="flex items-center gap-2 mb-1">
                      <ck-tag tone="cool" variant="soft">{{ scopeLabel(p.scope) }}</ck-tag>
                      <span class="text-sm text-white font-medium">{{ p.name }}</span>
                    </div>
                    <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-3); line-height:1.6;">
                      @if (p.max_cost_per_decision != null) {
                        {{ i18n.t('steering.control.max_cost') }} <span class="ck-tnum" style="color:var(--ck-fg-1);">\${{ p.max_cost_per_decision.toFixed(2) }}</span> ·
                      }
                      @if (p.max_latency_ms != null) {
                        {{ i18n.t('steering.control.max_latency') }} <span class="ck-tnum" style="color:var(--ck-fg-1);">{{ p.max_latency_ms }} ms</span> ·
                      }
                      @if (p.mandatory_hitl_if_confidence_below != null) {
                        HITL &lt; <span class="ck-tnum" style="color:var(--ck-fg-1);">{{ p.mandatory_hitl_if_confidence_below.toFixed(2) }}</span>
                      }
                    </div>
                  </li>
                }
              </ul>
            }
          </div>

          <div class="ck-surface rounded-md" style="padding:18px 22px;">
            <div class="flex items-center justify-between mb-4">
              <div class="flex items-center gap-2">
                <ck-glyph name="orbit" [size]="14" />
                <h3 class="ck-mono" style="font-size:11px; letter-spacing:0.18em; text-transform:uppercase; color:var(--ck-fg-2);">
                  {{ i18n.t('steering.adaptive.title') }}
                </h3>
              </div>
              <span class="ck-mono ck-tnum" style="font-size:10px; color:var(--ck-fg-4);">
                {{ adaptivePolicies().length }}
              </span>
            </div>
            @if (!adaptivePolicies().length) {
              <div class="ck-mono" style="font-size:11px; padding:24px 0; text-align:center; color:var(--ck-fg-4);">
                {{ i18n.t('steering.adaptive.empty') }}
              </div>
            } @else {
              <ul style="display:flex; flex-direction:column; gap:6px;">
                @for (p of adaptivePolicies(); track p.id) {
                  <li class="ck-surface rounded" style="padding:10px 12px; background:var(--ck-bg-inset);">
                    <div class="flex items-center gap-2 mb-1">
                      <ck-tag [tone]="p.enabled ? 'pos' : 'neutral'" variant="soft">
                        {{ p.enabled ? i18n.t('steering.policy.live') : i18n.t('steering.policy.off') }}
                      </ck-tag>
                      <ck-tag [tone]="adaptationTone(p.adaptation_level)" variant="outline">
                        {{ adaptationLabel(p.adaptation_level) }}
                      </ck-tag>
                      @if (p.scope) {
                        <ck-tag tone="cool" variant="outline">{{ scopeLabel(p.scope) }}</ck-tag>
                      }
                      <span class="text-sm text-white font-medium">{{ p.name }}</span>
                      <span class="ml-auto flex items-center gap-1">
                        <button
                          type="button"
                          (click)="toggleAdaptive(p)"
                          [disabled]="pendingAdaptiveId() === p.id"
                          class="ck-mono"
                          style="padding:4px 8px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-2); background:var(--ck-bg-raised);"
                          [title]="p.enabled ? i18n.t('steering.policy.disable_hint') : i18n.t('steering.policy.enable_hint')"
                        >
                          {{ p.enabled ? i18n.t('steering.policy.disable') : i18n.t('steering.policy.enable') }}
                        </button>
                        <button
                          type="button"
                          (click)="deleteAdaptive(p)"
                          [disabled]="pendingAdaptiveId() === p.id"
                          class="ck-mono"
                          style="padding:4px 8px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-signal-neg); background:transparent;"
                          [title]="i18n.t('steering.policy.delete_hint')"
                        >
                          {{ i18n.t('steering.policy.delete_short') }}
                        </button>
                      </span>
                    </div>
                    @if (p.allowed_actions?.length) {
                      <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-3);">
                        {{ i18n.t('steering.policy.actions') }} <span class="ck-tnum" style="color:var(--ck-fg-1);">{{ p.allowed_actions?.join(' · ') }}</span>
                      </div>
                    }
                  </li>
                }
              </ul>
            }
            <div style="margin-top:14px; padding-top:12px; border-top:1px solid var(--ck-hair);">
              <button
                type="button"
                (click)="quickCreateAdaptive()"
                [disabled]="creatingAdaptive()"
                class="ck-mono"
                style="padding:6px 10px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-2); background:var(--ck-bg-inset);"
              >
                {{ creatingAdaptive() ? i18n.t('steering.adaptive.creating') : i18n.t('steering.adaptive.add') }}
              </button>
            </div>
          </div>
        </section>

        @if (legacyPreviewEnabled) {
        <!-- Retired legacy before/after preview. -->
        <section class="ck-surface rounded-md" style="padding:22px 26px;">
          <div class="flex items-center justify-between mb-4">
            <div class="flex items-center gap-2">
              <ck-glyph name="crosshair" [size]="14" />
              <h3 class="ck-mono" style="font-size:11px; letter-spacing:0.18em; text-transform:uppercase; color:var(--ck-fg-2);">
                SIMULATE · BEFORE / AFTER
              </h3>
            </div>
            <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
              Preview the levers' impact before committing
            </span>
          </div>
          @if (!sim()) {
            <div class="ck-mono" style="font-size:11px; padding:24px 0; text-align:center; color:var(--ck-fg-4);">
              ADJUST A LEVER TO SIMULATE
            </div>
          } @else {
            <div class="grid grid-cols-4 gap-4">
              <div>
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:4px;">COST</div>
                <div class="flex items-baseline gap-2">
                  <span class="ck-mono ck-tnum" style="font-size:13px; color:var(--ck-fg-4);">
                    {{ formatCurrency(sim()!.base.total_cost ?? null) }}
                  </span>
                  <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">→</span>
                  <span class="ck-mono ck-tnum" style="font-size:14px; color:var(--ck-fg-1);">
                    {{ formatCurrency(sim()!.projected.total_cost) }}
                  </span>
                </div>
                <div class="ck-mono ck-tnum" style="font-size:10px; margin-top:2px;" [style.color]="deltaColor(negateDelta(impactDelta(sim()!.projected.total_cost, sim()!.base.total_cost)))">
                  {{ formatSigned(impactDelta(sim()!.projected.total_cost, sim()!.base.total_cost)) }}
                </div>
              </div>
              <div>
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:4px;">VALUE</div>
                <div class="flex items-baseline gap-2">
                  <span class="ck-mono ck-tnum" style="font-size:13px; color:var(--ck-fg-4);">
                    {{ formatCurrency(sim()!.base.estimated_value ?? null) }}
                  </span>
                  <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">→</span>
                  <span class="ck-mono ck-tnum" style="font-size:14px; color:var(--ck-fg-1);">
                    {{ formatCurrency(sim()!.projected.estimated_value) }}
                  </span>
                </div>
                <div class="ck-mono ck-tnum" style="font-size:10px; margin-top:2px;" [style.color]="deltaColor(impactDelta(sim()!.projected.estimated_value, sim()!.base.estimated_value))">
                  {{ formatSigned(impactDelta(sim()!.projected.estimated_value, sim()!.base.estimated_value)) }}
                </div>
              </div>
              <div>
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:4px;">ROI</div>
                <div class="flex items-baseline gap-2">
                  <span class="ck-mono ck-tnum" style="font-size:13px; color:var(--ck-fg-4);">
                    {{ formatRoi(sim()!.base.roi ?? null) }}
                  </span>
                  <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">→</span>
                  <span class="ck-mono ck-tnum" style="font-size:14px; color:var(--ck-fg-1);">
                    {{ formatRoi(sim()!.projected.roi ?? null) }}
                  </span>
                </div>
                <div class="ck-mono ck-tnum" style="font-size:10px; margin-top:2px;" [style.color]="deltaColor(impactDelta(sim()!.projected.roi, sim()!.base.roi))">
                  {{ formatPercentagePointDelta(sim()!.projected.roi, sim()!.base.roi) }}
                </div>
              </div>
              <div>
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:4px;">LATENCY IDX</div>
                <div class="flex items-baseline gap-2">
                  <span class="ck-mono ck-tnum" style="font-size:13px; color:var(--ck-fg-4);">1.00</span>
                  <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">→</span>
                  <span class="ck-mono ck-tnum" style="font-size:14px; color:var(--ck-fg-1);">
                    {{ formatIndex(sim()!.projected.latency_index) }}
                  </span>
                </div>
                <div class="ck-mono ck-tnum" style="font-size:10px; margin-top:2px;" [style.color]="deltaColor(-(sim()!.projected.latency_index - 1))">
                  {{ formatSigned((sim()!.projected.latency_index - 1) * 100) }}%
                </div>
              </div>
            </div>
          }
        </section>
        }
      </div>
    </ck-page-frame>
  `,
})
export class SteeringComponent implements OnInit {
  readonly i18n = inject(I18nService);
  private readonly canonical = inject(CanonicalApiService);

  readonly capabilities = signal<Capability[]>([]);
  readonly targetCapability = signal<Capability | null>(null);
  readonly sim = signal<SimulateResult | null>(null);
  readonly applying = signal(false);
  readonly controlPolicies = signal<ControlPolicy[]>([]);
  readonly adaptivePolicies = signal<AdaptivePolicy[]>([]);
  readonly pendingAdaptiveId = signal<string | null>(null);
  readonly creatingAdaptive = signal(false);
  readonly legacyPreviewEnabled = false;

  // Levers are plain signals so templates can drive them via [ngModel].
  // Canonical 4-axis ControlPlaneVector (mental model §23.8).
  readonly resource = signal(0.5);
  readonly velocity = signal(0.5);
  readonly autonomy = signal(0.3);
  readonly riskTolerance = signal(0.4);

  readonly netDelta = computed(() => {
    const s = this.sim();
    if (
      !s
      || s.base.estimated_value == null
      || s.base.total_cost == null
      || s.projected.estimated_value == null
      || s.projected.total_cost == null
    ) return null;
    const baseNet = s.base.estimated_value - s.base.total_cost;
    const projNet = s.projected.estimated_value - s.projected.total_cost;
    return projNet - baseNet;
  });

  readonly projectedRoi = computed(() => this.sim()?.projected.roi ?? null);

  ngOnInit(): void {
    this.canonical.listCapabilities().subscribe((caps) => this.capabilities.set(caps));
    this.refreshPolicies();
  }

  private refreshPolicies(): void {
    const cap = this.targetCapability();
    const filter = cap
      ? { scope: 'capability' as const, target_id: cap.id }
      : undefined;
    this.canonical.controlPolicies(filter).subscribe((p) => this.controlPolicies.set(p));
    this.canonical.adaptivePolicies(filter).subscribe((p) => this.adaptivePolicies.set(p));
  }

  selectCapability(c: Capability | null): void {
    this.targetCapability.set(c);
    this.refreshPolicies();
  }

  onLeverChanged(): void {
    // Legacy preview is intentionally retired; no network request is issued.
  }

  reset(): void {
    this.resource.set(0.5);
    this.velocity.set(0.5);
    this.autonomy.set(0.3);
    this.riskTolerance.set(0.4);
  }

  apply(): void {
    if (this.applying() || !this.sim()) return;
    this.applying.set(true);
    const target = this.targetCapability();
    // Persist a ControlPolicy mirroring the levers so the next runs pick it up.
    const s = this.sim()!;
    const body = {
      name: `Levers · ${target?.slug ?? 'portfolio'} · ${new Date().toISOString().slice(0, 10)}`,
      // Canonical scopes: portfolio | capability | system. Never 'workspace'.
      scope: target ? 'capability' : 'portfolio',
      target_id: target?.id ?? null,
      max_cost_per_decision: s.projected.total_cost != null
        && s.projected.total_cost > 0
        && s.base.runs_count
        ? (s.projected.total_cost / s.base.runs_count) * 1.2
        : null,
      max_latency_ms: Math.round(8000 * s.projected.latency_index),
      mandatory_hitl_if_confidence_below: this.autonomy() < 0.4 ? 0.7 : null,
      allowed_models: [],
      allowed_skills: [],
      extra: {
        levers: {
          resource: this.resource(),
          velocity: this.velocity(),
          autonomy: this.autonomy(),
          risk_tolerance: this.riskTolerance(),
        },
      },
    };
    this.canonical.createControlPolicy(body).subscribe({
      next: (p) => {
        this.applying.set(false);
        if (p) this.controlPolicies.update((list) => [p, ...list]);
      },
      error: () => this.applying.set(false),
    });
  }

  protected leverLabel(
    kind: 'resource' | 'velocity' | 'autonomy' | 'risk_tolerance',
    v: number,
  ): string {
    if (kind === 'resource') {
      if (v < 0.3) return 'LEAN';
      if (v < 0.7) return 'BALANCED';
      return 'DEEP';
    }
    if (kind === 'velocity') {
      if (v < 0.3) return 'THOROUGH';
      if (v < 0.7) return 'NORMAL';
      return 'RAPID';
    }
    if (kind === 'risk_tolerance') {
      if (v < 0.3) return 'CAUTIOUS';
      if (v < 0.7) return 'BALANCED';
      return 'BOLD';
    }
    if (v < 0.3) return 'HITL ON EVERY STEP';
    if (v < 0.7) return 'SUPERVISED';
    return 'FULL AUTONOMY';
  }

  protected projected(
    key: 'total_cost' | 'estimated_value' | 'latency_index' | 'risk_index',
  ): number | null {
    const p = this.sim()?.projected;
    if (!p) return null;
    const v = (p as unknown as Record<string, number | null | undefined>)[key];
    return v == null ? null : Number(v);
  }

  protected formatCurrency(v: number | null): string {
    if (v == null) return '—';
    if (Math.abs(v) >= 1000) return `$${(v / 1000).toFixed(1)}k`;
    return `$${v.toFixed(2)}`;
  }

  protected formatSigned(v: number | null): string {
    if (v == null) return '—';
    const sign = v > 0 ? '+' : v < 0 ? '-' : '';
    const abs = Math.abs(v);
    if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
    return `${sign}$${abs.toFixed(2)}`;
  }

  protected formatRoi(v: number | null): string {
    if (v == null) return '—';
    return `${(v * 100).toFixed(0)}%`;
  }

  protected formatIndex(v: number | null): string {
    if (v == null) return '—';
    return v.toFixed(2);
  }

  protected deltaColor(v: number | null): string {
    if (v == null) return 'var(--ck-fg-3)';
    if (v > 0) return 'var(--ck-signal-pos)';
    if (v < 0) return 'var(--ck-signal-neg)';
    return 'var(--ck-fg-2)';
  }

  protected impactDelta(
    projected: number | null | undefined,
    base: number | null | undefined,
  ): number | null {
    return measuredImpactDelta(projected, base);
  }

  protected negateDelta(value: number | null): number | null {
    return value == null ? null : -value;
  }

  protected formatPercentagePointDelta(
    projected: number | null | undefined,
    base: number | null | undefined,
  ): string {
    const delta = measuredImpactDelta(projected, base);
    if (delta == null) return '—';
    const points = delta * 100;
    const sign = points > 0 ? '+' : points < 0 ? '-' : '';
    return `${sign}${Math.abs(points).toFixed(1)} pp`;
  }

  protected roiTone(v: number | null): 'pos' | 'cool' | 'neg' | 'neutral' {
    if (v == null) return 'neutral';
    if (v >= 1) return 'pos';
    if (v >= 0) return 'cool';
    return 'neg';
  }

  protected riskColor(): string {
    const r = this.projected('risk_index');
    if (r == null) return 'var(--ck-fg-3)';
    if (r > 0.7) return 'var(--ck-signal-warn)';
    return 'var(--ck-signal-pos)';
  }

  protected adaptationTone(level: string): 'pos' | 'cool' | 'warn' {
    switch (level) {
      case 'aggressive':   return 'warn';
      case 'conservative': return 'pos';
      case 'moderate':
      default:             return 'cool';
    }
  }

  /** Map an API value through `<prefix><value>`, falling back to the raw value. */
  private apiValueLabel(prefix: string, value: string): string {
    const key = prefix + value;
    const label = this.i18n.t(key);
    return label === key ? value : label;
  }

  protected scopeLabel(scope: string): string {
    return this.apiValueLabel('hypervisor.scope.', scope);
  }

  protected adaptationLabel(level: string): string {
    return this.apiValueLabel('steering.adaptation.', level);
  }

  toggleAdaptive(p: AdaptivePolicy): void {
    if (this.pendingAdaptiveId()) return;
    this.pendingAdaptiveId.set(p.id);
    this.canonical.toggleAdaptivePolicy(p.id).subscribe({
      next: (updated) => {
        if (updated) {
          this.adaptivePolicies.update((list) =>
            list.map((x) => (x.id === p.id ? updated : x)),
          );
        }
        this.pendingAdaptiveId.set(null);
      },
      error: () => this.pendingAdaptiveId.set(null),
    });
  }

  deleteAdaptive(p: AdaptivePolicy): void {
    if (this.pendingAdaptiveId()) return;
    if (!confirm(this.i18n.t('steering.policy.delete_confirm', { name: p.name }))) return;
    this.pendingAdaptiveId.set(p.id);
    this.canonical.deleteAdaptivePolicy(p.id).subscribe({
      next: (ok) => {
        if (ok) {
          this.adaptivePolicies.update((list) => list.filter((x) => x.id !== p.id));
        }
        this.pendingAdaptiveId.set(null);
      },
      error: () => this.pendingAdaptiveId.set(null),
    });
  }

  quickCreateAdaptive(): void {
    if (this.creatingAdaptive()) return;
    this.creatingAdaptive.set(true);
    const target = this.targetCapability();
    const body: Partial<AdaptivePolicy> = {
      name: `Adaptive · ${target?.slug ?? 'portfolio'} · ${new Date().toISOString().slice(0, 10)}`,
      enabled: false,
      adaptation_level: 'moderate',
      scope: target ? 'capability' : 'portfolio',
      target_id: target?.id ?? null,
      triggers: { confidence_below: 0.7, latency_above_ms: 5000 },
      allowed_actions: ['switch_model', 'escalate_hitl'],
      constraints: {},
    };
    this.canonical.createAdaptivePolicy(body).subscribe({
      next: (p) => {
        if (p) this.adaptivePolicies.update((list) => [p, ...list]);
        this.creatingAdaptive.set(false);
      },
      error: () => this.creatingAdaptive.set(false),
    });
  }
}
